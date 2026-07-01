# -*- coding: utf-8 -*-
"""
Recommendation Domain DTO

가치주 스크리너 + 골든크로스 스캔 결과를 합성한 추천 후보 DTO 정의.
AI/실주문과 무관하며, readiness_label은 규칙 기반으로만 산출된다.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import Field

from src.application.common.dto import BaseDTO
from src.application.domain.backtest.validation import (
    CandidateRule,
    RuleMetric,
    RuleValue,
    WindowMetrics,
)


class ReadinessLabel(str, Enum):
    """
    추천 후보 준비도 라벨

    Phase 1(규칙 기반, AI 없음)에서는 WATCH/RESEARCH/BLOCKED만 산출된다.
    CANDIDATE/DECISION_READY/AVOID는 AI evidence pack(Phase 3)과
    리스크 게이트(Phase 2)가 붙어야 도달 가능하다.
    """

    WATCH = "WATCH"
    RESEARCH = "RESEARCH"
    CANDIDATE = "CANDIDATE"
    DECISION_READY = "DECISION_READY"
    AVOID = "AVOID"
    BLOCKED = "BLOCKED"


class RecommendationScorecardDTO(BaseDTO):
    """
    추천 후보 점수표

    Attributes:
        technical_score: 골든크로스 상태 기반 기술 점수 (0~100)
        fundamental_score: 가치주 스크리너 통과 여부 기반 재무 점수 (0~100), 미평가 시 None
        quant_score: 정량(기술) 점수. Phase 1에서는 technical_score와 동일
        final_score: 최종 합성 점수
    """

    technical_score: float = Field(description="기술 점수 (gc_state 기반, 0~100)")
    fundamental_score: float | None = Field(
        default=None, description="재무 점수 (가치주 스크리너 통과 시 100, 미평가 시 None)"
    )
    quant_score: float = Field(description="정량 점수 (Phase 1: technical_score와 동일)")
    final_score: float = Field(description="최종 합성 점수")


class RecommendationCandidateDTO(BaseDTO):
    """
    추천 후보

    Attributes:
        symbol: 종목코드
        name: 종목명
        market: 시장 구분
        current_price: 현재가
        technical_state: 골든크로스 상태 (gc_state)
        has_fundamental_evidence: 가치주 스크리너 결과 존재 여부
        scorecard: 점수표
        readiness_label: 준비도 라벨
        missing_evidence: 부족한 증거 목록
        blocked_actions: 차단된 액션 목록 (Phase 1은 항상 auto_order 포함)
    """

    symbol: str = Field(description="종목코드")
    name: str = Field(description="종목명")
    market: str = Field(description="시장 구분")
    current_price: Decimal = Field(description="현재가")
    technical_state: str = Field(description="골든크로스 상태 (gc_state)")
    has_fundamental_evidence: bool = Field(description="가치주 스크리너 결과 존재 여부")
    scorecard: RecommendationScorecardDTO = Field(description="점수표")
    readiness_label: ReadinessLabel = Field(description="준비도 라벨")
    missing_evidence: list[str] = Field(default_factory=list, description="부족한 증거 목록")
    blocked_actions: list[str] = Field(default_factory=list, description="차단된 액션 목록")


class RecommendationCandidateListDTO(BaseDTO):
    """
    추천 후보 목록

    Attributes:
        candidates: 추천 후보 목록
        total_scanned: 골든크로스 스캔 대상 종목 수
        candidate_count: 추천 후보 수
        generated_at: 생성 시각
        errors: 골든크로스 스캔 중 발생한 오류 메시지 (스캔 저하 여부 판단용)
    """

    candidates: list[RecommendationCandidateDTO] = Field(description="추천 후보 목록")
    total_scanned: int = Field(description="골든크로스 스캔 대상 종목 수")
    candidate_count: int = Field(description="추천 후보 수")
    generated_at: datetime = Field(description="생성 시각")
    errors: list[str] = Field(default_factory=list, description="스캔 중 발생한 오류 메시지")


class RuleSetStatus(str, Enum):
    """RecommendationRuleSet 상태. active 룰셋만 scan_candidates(rule_set_id=...)에서 사용 가능."""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


_ZERO_WINDOW_METRICS = WindowMetrics(
    cagr=0.0, benchmark_cagr=0.0, mdd=0.0, sharpe=0.0, turnover=0.0
)


def compute_rule_frozen_hash(candidate_id: str, name: str, rules: dict[str, RuleValue]) -> str:
    """
    후보(candidate_id/name/rules)의 frozen_hash를 계산한다.

    `backtest/validation.py`의 `CandidateRule.frozen_hash()`를 그대로 위임한다
    (train/test 지표는 해시 계산에 관여하지 않으므로 placeholder로 채운다) —
    sha256/정렬 규칙을 이 파일에서 다시 구현하지 않기 위함이다.
    """
    return CandidateRule(
        candidate_id=candidate_id,
        name=name,
        rules=rules,
        train_metrics=_ZERO_WINDOW_METRICS,
        test_metrics=_ZERO_WINDOW_METRICS,
    ).frozen_hash()


class RecommendationRuleCandidateDTO(BaseDTO):
    """
    추천 룰셋 후보 (walk-forward 검증 이전의 정의)

    Attributes:
        candidate_id: 후보 식별자 (룰셋 내에서 유일)
        name: 후보 이름
        rules: 골든크로스/가치주 스크리너 파라미터. 키는 `backtest_router.py`의
            `base_strategy_params`(short_period, long_period, stoch_k_period,
            stoch_d_period, stoch_oversold, stoch_overbought 등)와 동일한 체계를 따른다.
    """

    candidate_id: str = Field(min_length=1, description="후보 식별자")
    name: str = Field(min_length=1, description="후보 이름")
    rules: dict[str, RuleValue] = Field(
        min_length=1, description="골든크로스/가치주 스크리너 파라미터"
    )

    @property
    def frozen_hash(self) -> str:
        return compute_rule_frozen_hash(self.candidate_id, self.name, self.rules)


class RecommendationRuleSetDTO(BaseDTO):
    """
    추천 검색식 룰셋

    Attributes:
        rule_id: 룰셋 식별자
        name: 룰셋 이름
        version: 버전 (동일 이름 재등록 시 증가)
        status: draft/active/archived
        candidates: 룰셋에 속한 후보 목록 (walk-forward 검증 대상)
        frozen_hash: 검증(validate) 후 선택된 후보의 frozen_hash. 검증 전에는 None.
    """

    rule_id: str = Field(min_length=1, description="룰셋 식별자")
    name: str = Field(min_length=1, description="룰셋 이름")
    version: int = Field(default=1, ge=1, description="버전")
    status: RuleSetStatus = Field(default=RuleSetStatus.DRAFT, description="룰셋 상태")
    candidates: list[RecommendationRuleCandidateDTO] = Field(
        min_length=1, description="룰셋에 속한 후보 목록"
    )
    frozen_hash: str | None = Field(
        default=None, description="검증 후 선택된 후보의 frozen_hash (검증 전 None)"
    )


class RecommendationRuleSetCreateRequestDTO(BaseDTO):
    """룰셋 등록 요청. 등록 직후 상태는 항상 draft이며, validate 성공 시 active로 전환된다."""

    name: str = Field(min_length=1, description="룰셋 이름")
    candidates: list[RecommendationRuleCandidateDTO] = Field(
        min_length=1, description="검증 대상 후보 목록"
    )


class RecommendationRuleSetListDTO(BaseDTO):
    rule_sets: list[RecommendationRuleSetDTO] = Field(description="룰셋 목록")
    total_count: int = Field(description="전체 룰셋 수")


class RecommendationRuleSetValidationRequestDTO(BaseDTO):
    """
    walk-forward 검증 요청

    Attributes:
        train_start/train_end/test_start/test_end: 학습/검증 기간
            (train_end < test_start 검증은 WalkForwardPeriod가 수행)
        benchmark: 벤치마크 심볼 (CAGR 비교 기준)
        market: 유니버스 시장 필터
        eligible_only: 유니버스 적격 종목만 대상
        limit: 유니버스 최대 종목 수
        selection_metric: 후보 선정 기준 지표
    """

    train_start: date = Field(description="학습 기간 시작일")
    train_end: date = Field(description="학습 기간 종료일")
    test_start: date = Field(description="검증(OOS) 기간 시작일")
    test_end: date = Field(description="검증(OOS) 기간 종료일")
    benchmark: str = Field(description="벤치마크 심볼")
    market: str | None = Field(default=None, description="유니버스 시장 필터 (KOSPI/KOSDAQ)")
    eligible_only: bool = Field(default=True, description="유니버스 적격 종목만 대상")
    limit: int = Field(default=20, ge=1, le=100, description="유니버스 최대 종목 수")
    selection_metric: RuleMetric = Field(default=RuleMetric.CAGR, description="후보 선정 기준 지표")


class RecommendationRuleSetValidationResultDTO(BaseDTO):
    """walk-forward 검증 결과 (WalkForwardValidationResult를 API 응답 형태로 변환)"""

    rule_id: str = Field(description="룰셋 식별자")
    selected_candidate_id: str = Field(description="선정된 후보 ID")
    selected_candidate_hash: str = Field(description="선정된 후보의 frozen_hash")
    data_snooping_warning: bool = Field(description="후보 2개 이상 비교 시 data-snooping 경고")
    train_metrics: WindowMetrics = Field(description="선정 후보의 학습 기간 지표")
    test_metrics: WindowMetrics = Field(description="선정 후보의 검증(OOS) 기간 지표")
    report_markdown: str = Field(description="walk-forward 검증 리포트 (markdown)")
