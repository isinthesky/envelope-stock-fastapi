# -*- coding: utf-8 -*-
"""
Recommendation Rule Set Service

룰셋 등록/조회와 walk-forward 검증 실행+영속화를 담당하는 유즈케이스 레이어.
검증 자체의 계산 로직은 RecommendationRuleSetValidationService(T3)에 위임하고,
이 서비스는 DB 저장/트랜잭션 경계만 책임진다(스캔 경로에서는 재검증하지 않는다).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.repositories.recommendation_rule_set_repository import (
    RecommendationRuleSetRepository,
    RecommendationRuleValidationRepository,
)
from src.application.common.decorators import transaction
from src.application.common.exceptions import (
    InvalidInputError,
    ResourceNotFoundError,
    ValidationError,
)
from src.application.domain.backtest.service import BacktestService
from src.application.domain.backtest.validation import WalkForwardValidationError
from src.application.domain.recommendation.dto import (
    RecommendationRuleSetCreateRequestDTO,
    RecommendationRuleSetDTO,
    RecommendationRuleSetListDTO,
    RecommendationRuleSetValidationRequestDTO,
    RecommendationRuleSetValidationResultDTO,
    RuleSetStatus,
)
from src.application.domain.recommendation.rule_set_mapper import (
    candidates_to_json,
    rule_set_from_model,
)
from src.application.domain.recommendation.rule_set_validation_service import (
    RecommendationRuleSetValidationService,
)


def _parse_rule_set_id(rule_id: str) -> int:
    try:
        return int(rule_id)
    except ValueError as exc:
        raise InvalidInputError("rule_id", f"rule_id must be numeric, got {rule_id!r}") from exc


class RecommendationRuleSetService:
    """룰셋 CRUD(등록/조회) + walk-forward 검증 실행/영속화"""

    @transaction
    async def create_rule_set(
        self, session: AsyncSession, request: RecommendationRuleSetCreateRequestDTO
    ) -> RecommendationRuleSetDTO:
        repo = RecommendationRuleSetRepository()
        latest_version = await repo.get_latest_version_by_name(request.name, session=session)
        model = await repo.create(
            session=session,
            name=request.name,
            version=(latest_version or 0) + 1,
            status=RuleSetStatus.DRAFT.value,
            candidates_json=candidates_to_json(request.candidates),
            frozen_hash=None,
        )
        return rule_set_from_model(model)

    @transaction
    async def list_rule_sets(
        self, session: AsyncSession, limit: int = 100, offset: int = 0
    ) -> RecommendationRuleSetListDTO:
        repo = RecommendationRuleSetRepository()
        models = await repo.list_all(limit=limit, offset=offset, session=session)
        total_count = await repo.count(session=session)
        rule_sets = [rule_set_from_model(model) for model in models]
        return RecommendationRuleSetListDTO(rule_sets=rule_sets, total_count=total_count)

    @transaction
    async def validate_rule_set(
        self,
        session: AsyncSession,
        rule_id: str,
        request: RecommendationRuleSetValidationRequestDTO,
        backtest_service: BacktestService,
    ) -> RecommendationRuleSetValidationResultDTO:
        rule_set_repo = RecommendationRuleSetRepository()
        model = await rule_set_repo.get_by_id(_parse_rule_set_id(rule_id), session=session)
        if model is None:
            raise ResourceNotFoundError("RecommendationRuleSet", rule_id)
        rule_set = rule_set_from_model(model)

        validation_service = RecommendationRuleSetValidationService(backtest_service, session)
        try:
            result = await validation_service.validate(
                rule_set=rule_set,
                train_start=request.train_start,
                train_end=request.train_end,
                test_start=request.test_start,
                test_end=request.test_end,
                benchmark=request.benchmark,
                market=request.market,
                eligible_only=request.eligible_only,
                limit=request.limit,
                selection_metric=request.selection_metric,
            )
        except WalkForwardValidationError as exc:
            # WalkForwardValidationError는 ApplicationError가 아니라서 그대로 두면
            # 전역 핸들러가 500으로 반환한다 - 기간/유니버스 검증 실패는 클라이언트
            # 요청 문제(4xx)이지 서버 오류가 아니므로 ValidationError로 변환한다.
            raise ValidationError(str(exc)) from exc

        data_snooping_warning = len(rule_set.candidates) > 1
        selected = result.selected_candidate

        validation_repo = RecommendationRuleValidationRepository()
        await validation_repo.create(
            session=session,
            rule_set_id=model.id,
            benchmark=request.benchmark,
            selection_metric=request.selection_metric.value,
            train_start=request.train_start,
            train_end=request.train_end,
            test_start=request.test_start,
            test_end=request.test_end,
            selected_candidate_id=result.selected_candidate_id,
            selected_candidate_hash=result.selected_candidate_hash,
            data_snooping_warning=data_snooping_warning,
            train_metrics_json=selected.train_metrics.model_dump_json(),
            test_metrics_json=selected.test_metrics.model_dump_json(),
            report_markdown=result.to_markdown(),
        )
        await rule_set_repo.update_by_id(
            model.id,
            session=session,
            status=RuleSetStatus.ACTIVE.value,
            frozen_hash=result.selected_candidate_hash,
        )

        return RecommendationRuleSetValidationResultDTO(
            rule_id=rule_id,
            selected_candidate_id=result.selected_candidate_id,
            selected_candidate_hash=result.selected_candidate_hash,
            data_snooping_warning=data_snooping_warning,
            train_metrics=selected.train_metrics,
            test_metrics=selected.test_metrics,
            report_markdown=result.to_markdown(),
        )
