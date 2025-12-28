# -*- coding: utf-8 -*-
"""
Strategy Service - 전략 관리 서비스
"""

import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.strategy import StrategyStatus, StrategyType
from src.adapters.database.models.stock_universe import MarketType
from src.adapters.database.repositories.stock_universe_repository import (
    StockUniverseRepository,
)
from src.adapters.database.repositories.strategy_repository import StrategyRepository
from src.adapters.database.repositories.strategy_signal_repository import (
    StrategySignalRepository,
)
from src.adapters.database.repositories.strategy_symbol_state_repository import (
    StrategySymbolStateRepository,
)
from src.adapters.external.kis_api.client import KISAPIClient
from src.application.common.decorators import transaction
from src.application.common.exceptions import StrategyError
from src.application.domain.strategy.dto import (
    GoldenCrossConfigDTO,
    SignalListDTO,
    SignalStatisticsDTO,
    StockUniverseItemDTO,
    StockUniverseListDTO,
    StrategyConfigDTO,
    StrategyCreateRequestDTO,
    StrategyDetailResponseDTO,
    StrategyExecuteResultDTO,
    StrategyListResponseDTO,
    StrategySignalDTO,
    StrategyUpdateRequestDTO,
    SymbolStateDTO,
    SymbolStateListDTO,
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

        # 설정 JSON 변환 (전략 유형에 따라 적절한 config 사용)
        if request.strategy_type == "golden_cross" and request.golden_cross_config:
            config_json = request.golden_cross_config.model_dump_json()
        elif request.config:
            config_json = request.config.model_dump_json()
        elif request.strategy_type == "golden_cross":
            # golden_cross인데 config가 없으면 기본값 사용
            config_json = GoldenCrossConfigDTO().model_dump_json()
        else:
            config_json = StrategyConfigDTO().model_dump_json()

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
        # 전략 유형에 따라 적절한 config 사용
        if request.golden_cross_config:
            update_data["config_json"] = request.golden_cross_config.model_dump_json()
        elif request.config:
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
        config_dict = json.loads(strategy.config_json)

        # 전략 유형에 따라 적절한 config 파싱
        config = None
        golden_cross_config = None

        if strategy.strategy_type == "golden_cross":
            try:
                golden_cross_config = GoldenCrossConfigDTO(**config_dict)
            except Exception:
                # 파싱 실패 시 기본값 사용
                golden_cross_config = GoldenCrossConfigDTO()
        else:
            try:
                config = StrategyConfigDTO(**config_dict)
            except Exception:
                config = StrategyConfigDTO()

        return StrategyDetailResponseDTO(
            id=strategy.id,
            name=strategy.name,
            description=strategy.description,
            strategy_type=strategy.strategy_type,
            account_no=strategy.account_no,
            symbols=strategy.symbol_list,
            status=strategy.status,
            config=config,
            golden_cross_config=golden_cross_config,
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

    # ==================== Golden Cross Strategy Methods ====================

    async def get_golden_cross_config(self, strategy_id: int) -> GoldenCrossConfigDTO:
        """골든크로스 전략 설정 조회"""
        if not self.session:
            raise StrategyError("Database session not provided")

        strategy_repo = StrategyRepository(self.session)
        strategy = await strategy_repo.get_by_id(strategy_id)

        if not strategy:
            raise StrategyError(f"Strategy not found: {strategy_id}")

        try:
            config_dict = json.loads(strategy.config_json)
            return GoldenCrossConfigDTO(**config_dict)
        except Exception:
            return GoldenCrossConfigDTO()

    @transaction
    async def update_golden_cross_config(
        self,
        session: AsyncSession,
        strategy_id: int,
        config: GoldenCrossConfigDTO,
    ) -> GoldenCrossConfigDTO:
        """골든크로스 전략 설정 수정"""
        strategy_repo = StrategyRepository(session)
        strategy = await strategy_repo.get_by_id(strategy_id)

        if not strategy:
            raise StrategyError(f"Strategy not found: {strategy_id}")

        config_json = config.model_dump_json()
        await strategy_repo.update(strategy_id, config_json=config_json)

        return config

    async def get_symbol_states(self, strategy_id: int) -> SymbolStateListDTO:
        """종목별 상태 조회"""
        if not self.session:
            raise StrategyError("Database session not provided")

        state_repo = StrategySymbolStateRepository(self.session)
        states = await state_repo.get_all_by_strategy(strategy_id)
        state_counts = await state_repo.count_by_state(strategy_id)

        state_dtos = [
            SymbolStateDTO(
                strategy_id=s.strategy_id,
                symbol=s.symbol,
                state=s.state,
                gc_date=s.gc_date,
                pullback_date=s.pullback_date,
                entry_date=s.entry_date,
                entry_price=s.entry_price,
                quantity=s.quantity,
                last_ma_short=s.last_ma_short,
                last_ma_long=s.last_ma_long,
                last_stoch_k=s.last_stoch_k,
                last_stoch_d=s.last_stoch_d,
                last_close=s.last_close,
                unrealized_pnl_ratio=s.unrealized_pnl_ratio,
                days_since_entry=s.days_since_entry,
                last_checked_at=s.last_checked_at,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in states
        ]

        return SymbolStateListDTO(
            states=state_dtos,
            total_count=len(state_dtos),
            state_counts=state_counts,
        )

    async def get_signals(
        self, strategy_id: int, limit: int = 50, offset: int = 0
    ) -> SignalListDTO:
        """시그널 이력 조회"""
        if not self.session:
            raise StrategyError("Database session not provided")

        signal_repo = StrategySignalRepository(self.session)
        signals = await signal_repo.get_by_strategy(strategy_id, limit, offset)

        signal_dtos = [
            StrategySignalDTO(
                id=s.id,
                strategy_id=s.strategy_id,
                symbol=s.symbol,
                signal_type=s.signal_type,
                signal_status=s.signal_status,
                signal_price=s.signal_price,
                target_quantity=s.target_quantity,
                executed_price=s.executed_price,
                executed_quantity=s.executed_quantity,
                exit_reason=s.exit_reason,
                realized_pnl=s.realized_pnl,
                realized_pnl_ratio=s.realized_pnl_ratio,
                ma_short=s.ma_short,
                ma_long=s.ma_long,
                stoch_k=s.stoch_k,
                stoch_d=s.stoch_d,
                prev_state=s.prev_state,
                new_state=s.new_state,
                note=s.note,
                signal_at=s.signal_at,
                executed_at=s.executed_at,
                created_at=s.created_at,
            )
            for s in signals
        ]

        return SignalListDTO(
            signals=signal_dtos,
            total_count=len(signal_dtos),
        )

    async def get_signal_statistics(
        self, strategy_id: int, days: int = 30
    ) -> SignalStatisticsDTO:
        """시그널 통계 조회"""
        if not self.session:
            raise StrategyError("Database session not provided")

        signal_repo = StrategySignalRepository(self.session)
        stats = await signal_repo.get_statistics(strategy_id, days)

        return SignalStatisticsDTO(**stats)

    async def execute_golden_cross(
        self, strategy_id: int, dry_run: bool = True, force: bool = False
    ) -> StrategyExecuteResultDTO:
        """골든크로스 전략 수동 실행"""
        if not self.session:
            raise StrategyError("Database session not provided")

        from src.application.domain.strategy.scheduler import get_strategy_scheduler

        scheduler = get_strategy_scheduler()
        execution = await scheduler.execute_now(strategy_id, dry_run=dry_run, force=force)

        if not execution.get("success"):
            raise StrategyError(execution.get("error", "Execution failed"))

        return StrategyExecuteResultDTO(**execution["result"])

    async def get_stock_universe(
        self, market: str | None = None, eligible_only: bool = True
    ) -> StockUniverseListDTO:
        """종목 유니버스 조회"""
        if not self.session:
            raise StrategyError("Database session not provided")

        universe_repo = StockUniverseRepository(self.session)

        market_type = MarketType(market) if market else None

        if eligible_only:
            stocks = await universe_repo.get_eligible_stocks(market=market_type)
        else:
            if market_type:
                stocks = await universe_repo.get_many(market=market_type.value)
            else:
                stocks = await universe_repo.get_all()

        stock_dtos = [
            StockUniverseItemDTO(
                symbol=s.symbol,
                name=s.name,
                market=s.market,
                sector=s.sector,
                market_cap=s.market_cap,
                avg_volume_20d=s.avg_volume_20d,
                current_price=s.current_price,
                is_eligible=s.is_eligible,
                screening_score=s.screening_score,
            )
            for s in stocks
        ]

        eligible_count = sum(1 for s in stocks if s.is_eligible)

        return StockUniverseListDTO(
            stocks=stock_dtos,
            total_count=len(stock_dtos),
            eligible_count=eligible_count,
        )

    async def refresh_universe(self) -> dict:
        """유니버스 갱신"""
        if not self.session:
            raise StrategyError("Database session not provided")

        from src.application.domain.strategy.stock_screener import StockScreener

        kis_client = KISAPIClient()
        screener = StockScreener(self.session, kis_client)

        # TODO: KIS API에서 종목 정보 수집
        # 현재는 빈 데이터로 반환
        result = await screener.refresh_universe([])

        return result
