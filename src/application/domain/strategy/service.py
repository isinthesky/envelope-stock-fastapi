# -*- coding: utf-8 -*-
"""
Strategy Service - 전략 관리 서비스
"""

import json
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.strategy import StrategyStatus, StrategyType
from src.adapters.database.repositories.strategy_repository import StrategyRepository
from src.application.common.decorators import transaction
from src.application.common.exceptions import StrategyError
from src.application.domain.strategy.dto import (
    StrategyConfigDTO,
    StrategyCreateRequestDTO,
    StrategyDetailResponseDTO,
    StrategyListResponseDTO,
    StrategyUpdateRequestDTO,
)
from src.settings.config import settings


class StrategyService:
    """
    전략 서비스

    전략 생성, 조회, 수정, 삭제 및 실행 관리
    """

    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session
        if session:
            self.strategy_repo = StrategyRepository(session)

    # ==================== 전략 생성 ====================

    @transaction
    async def create_strategy(
        self, session: AsyncSession, request: StrategyCreateRequestDTO
    ) -> StrategyDetailResponseDTO:
        """
        전략 생성

        Args:
            session: Database Session
            request: 전략 생성 요청

        Returns:
            StrategyDetailResponseDTO: 생성된 전략 정보
        """
        account_no = request.account_no or settings.current_kis_account_no

        # 전략명 중복 체크
        strategy_repo = StrategyRepository(session)
        existing = await strategy_repo.get_by_name(request.name)
        if existing:
            raise StrategyError(f"Strategy with name '{request.name}' already exists")

        # 종목 리스트 문자열 변환
        symbols_str = ",".join(request.symbols)

        # 설정 JSON 변환
        config_json = request.config.model_dump_json()

        # 전략 생성
        strategy = await strategy_repo.create(
            name=request.name,
            description=request.description or "",
            strategy_type=request.strategy_type,
            account_no=account_no,
            symbols=symbols_str,
            config_json=config_json,
            status=StrategyStatus.PAUSED.value,
        )

        return self._to_detail_dto(strategy)

    # ==================== 전략 조회 ====================

    async def get_strategy(self, strategy_id: int) -> StrategyDetailResponseDTO:
        """
        전략 상세 조회

        Args:
            strategy_id: 전략 ID

        Returns:
            StrategyDetailResponseDTO: 전략 상세 정보
        """
        if not self.session:
            raise StrategyError("Database session not provided")

        strategy_repo = StrategyRepository(self.session)
        strategy = await strategy_repo.get_by_id(strategy_id)

        if not strategy:
            raise StrategyError(f"Strategy not found: {strategy_id}")

        return self._to_detail_dto(strategy)

    async def get_strategy_list(
        self,
        account_no: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> StrategyListResponseDTO:
        """
        전략 목록 조회

        Args:
            account_no: 계좌번호
            status: 전략 상태 필터
            limit: 조회 개수
            offset: 오프셋

        Returns:
            StrategyListResponseDTO: 전략 목록
        """
        if not self.session:
            raise StrategyError("Database session not provided")

        account_no = account_no or settings.current_kis_account_no
        strategy_repo = StrategyRepository(self.session)

        if status:
            strategies = await strategy_repo.get_by_status(
                StrategyStatus(status), limit=limit, offset=offset
            )
        else:
            strategies = await strategy_repo.get_by_account(
                account_no, limit=limit, offset=offset
            )

        strategy_list = [self._to_detail_dto(s) for s in strategies]

        return StrategyListResponseDTO(
            strategies=strategy_list, total_count=len(strategy_list)
        )

    # ==================== 전략 수정 ====================

    @transaction
    async def update_strategy(
        self, session: AsyncSession, strategy_id: int, request: StrategyUpdateRequestDTO
    ) -> StrategyDetailResponseDTO:
        """
        전략 수정

        Args:
            session: Database Session
            strategy_id: 전략 ID
            request: 전략 수정 요청

        Returns:
            StrategyDetailResponseDTO: 수정된 전략 정보
        """
        strategy_repo = StrategyRepository(session)
        strategy = await strategy_repo.get_by_id(strategy_id)

        if not strategy:
            raise StrategyError(f"Strategy not found: {strategy_id}")

        # 수정할 필드 준비
        update_data = {}
        if request.name:
            update_data["name"] = request.name
        if request.description is not None:
            update_data["description"] = request.description
        if request.symbols:
            update_data["symbols"] = ",".join(request.symbols)
        if request.config:
            update_data["config_json"] = request.config.model_dump_json()
        if request.status:
            update_data["status"] = request.status

        # 전략 업데이트
        await strategy_repo.update(strategy_id, **update_data)

        # 업데이트된 전략 조회
        updated_strategy = await strategy_repo.get_by_id(strategy_id)
        if not updated_strategy:
            raise StrategyError("Failed to retrieve updated strategy")

        return self._to_detail_dto(updated_strategy)

    # ==================== 전략 삭제 ====================

    @transaction
    async def delete_strategy(self, session: AsyncSession, strategy_id: int) -> None:
        """
        전략 삭제 (Soft Delete)

        Args:
            session: Database Session
            strategy_id: 전략 ID
        """
        strategy_repo = StrategyRepository(session)
        strategy = await strategy_repo.get_by_id(strategy_id)

        if not strategy:
            raise StrategyError(f"Strategy not found: {strategy_id}")

        # 활성 상태 전략은 삭제 불가
        if strategy.is_active:
            raise StrategyError("Cannot delete active strategy. Stop it first.")

        await strategy_repo.delete(strategy_id)

    # ==================== 전략 상태 관리 ====================

    @transaction
    async def start_strategy(
        self, session: AsyncSession, strategy_id: int
    ) -> StrategyDetailResponseDTO:
        """전략 시작 (활성화)"""
        strategy_repo = StrategyRepository(session)
        await strategy_repo.activate_strategy(strategy_id)

        strategy = await strategy_repo.get_by_id(strategy_id)
        if not strategy:
            raise StrategyError("Failed to retrieve strategy")

        return self._to_detail_dto(strategy)

    @transaction
    async def pause_strategy(
        self, session: AsyncSession, strategy_id: int
    ) -> StrategyDetailResponseDTO:
        """전략 일시정지"""
        strategy_repo = StrategyRepository(session)
        await strategy_repo.pause_strategy(strategy_id)

        strategy = await strategy_repo.get_by_id(strategy_id)
        if not strategy:
            raise StrategyError("Failed to retrieve strategy")

        return self._to_detail_dto(strategy)

    @transaction
    async def stop_strategy(
        self, session: AsyncSession, strategy_id: int
    ) -> StrategyDetailResponseDTO:
        """전략 중지"""
        strategy_repo = StrategyRepository(session)
        await strategy_repo.stop_strategy(strategy_id)

        strategy = await strategy_repo.get_by_id(strategy_id)
        if not strategy:
            raise StrategyError("Failed to retrieve strategy")

        return self._to_detail_dto(strategy)

    # ==================== Helper Methods ====================

    def _to_detail_dto(self, strategy) -> StrategyDetailResponseDTO:
        """Strategy Model을 DetailResponseDTO로 변환"""
        config = StrategyConfigDTO(**json.loads(strategy.config_json))

        return StrategyDetailResponseDTO(
            id=strategy.id,
            name=strategy.name,
            description=strategy.description,
            strategy_type=strategy.strategy_type,
            account_no=strategy.account_no,
            symbols=strategy.symbol_list,
            status=strategy.status,
            config=config,
            total_executions=strategy.total_executions,
            successful_executions=strategy.successful_executions,
            failed_executions=strategy.failed_executions,
            success_rate=strategy.success_rate,
            last_executed_at=strategy.last_executed_at,
            started_at=strategy.started_at,
            stopped_at=strategy.stopped_at,
            created_at=strategy.created_at,
            updated_at=strategy.updated_at,
        )
