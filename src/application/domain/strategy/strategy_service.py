# -*- coding: utf-8 -*-
"""
Strategy Service - 전략 관리 서비스

전략 CRUD, 상태 관리, 유니버스 관리 등 핵심 기능 제공
매수/매도 분석은 별도 서비스로 위임
"""

import json
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.strategy import StrategyStatus
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
from src.adapters.external.kis_api.client import get_kis_client
from src.application.common.decorators import transaction
from src.application.common.exceptions import StrategyError
from src.application.domain.strategy.dto import (
    AnalysisHistoryCreateDTO,
    AnalysisHistoryDTO,
    AnalysisHistoryListDTO,
    AnalysisHistoryRefreshResultDTO,
    GoldenCrossConfigDTO,
    GoldenCrossScanListDTO,
    SellSignalAnalysisDTO,
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

    # ==================== Stock Universe Methods ====================

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

        kis_client = get_kis_client()
        screener = StockScreener(self.session, kis_client)

        # TODO: KIS API에서 종목 정보 수집
        # 현재는 빈 데이터로 반환
        result = await screener.refresh_universe([])

        return result

    # ==================== Buy/Sell Strategy Delegation ====================

    async def scan_golden_cross_candidates(
        self,
        market: str | None = None,
        stoch_threshold: float = 30.0,
        gc_only: bool = True,
        include_etf: bool = True,
    ) -> GoldenCrossScanListDTO:
        """
        골든크로스 종목 스캔 (BuyStrategyService로 위임)

        Args:
            market: 시장 필터 (KOSPI/KOSDAQ/ETF)
            stoch_threshold: Stochastic 과매도 임계값
            gc_only: 골든크로스 활성 종목만 반환
            include_etf: ETF 종목 포함 여부 (기본 True)
        """
        from src.application.domain.strategy.buy_strategy_service import BuyStrategyService

        buy_service = BuyStrategyService(self.session)
        return await buy_service.scan_golden_cross_candidates(
            market=market,
            stoch_threshold=stoch_threshold,
            gc_only=gc_only,
            include_etf=include_etf,
        )

    async def analyze_sell_signal(
        self,
        symbol: str,
        stoch_overbought: float = 70.0,
        rsi_overbought: float = 70.0,
        entry_price: float | None = None,
        highest_price: float | None = None,
        trailing_stop_activated: bool = False,
    ) -> SellSignalAnalysisDTO:
        """
        매도 시그널 분석 (SellStrategyService로 위임)

        Args:
            symbol: 종목코드
            stoch_overbought: Stochastic 과매수 임계값
            rsi_overbought: RSI 과매수 임계값
            entry_price: 진입가 (수익률 기반 동적 임계값 적용)
            highest_price: 포지션 최고가 (트레일링 스탑용)
            trailing_stop_activated: 트레일링 스탑 활성화 여부
        """
        from src.application.domain.strategy.sell_strategy_service import SellStrategyService

        sell_service = SellStrategyService(self.session)
        return await sell_service.analyze_sell_signal(
            symbol=symbol,
            stoch_overbought=stoch_overbought,
            rsi_overbought=rsi_overbought,
            entry_price=entry_price,
            highest_price=highest_price,
            trailing_stop_activated=trailing_stop_activated,
        )

    # ==================== Analysis History Methods ====================

    @transaction
    async def save_analysis_history(
        self, session: AsyncSession, dto: AnalysisHistoryCreateDTO
    ) -> AnalysisHistoryDTO:
        """분석 이력 저장"""
        from src.adapters.database.repositories import AnalysisHistoryRepository

        history_repo = AnalysisHistoryRepository(session)

        # sell_reasons를 JSON 문자열로 변환
        sell_reasons_json = None
        if dto.sell_reasons:
            sell_reasons_json = json.dumps(dto.sell_reasons, ensure_ascii=False)

        model = await history_repo.create(
            analysis_type=dto.analysis_type,
            symbol=dto.symbol,
            name=dto.name,
            current_price=dto.current_price,
            ma_short=dto.ma_short,
            ma_long=dto.ma_long,
            ma_gap_ratio=dto.ma_gap_ratio,
            stoch_k=dto.stoch_k,
            stoch_d=dto.stoch_d,
            gc_state=dto.gc_state,
            is_gc_active=dto.is_gc_active,
            rsi=dto.rsi,
            is_death_cross=dto.is_death_cross,
            is_stoch_overbought=dto.is_stoch_overbought,
            is_rsi_overbought=dto.is_rsi_overbought,
            sell_signal_strength=dto.sell_signal_strength,
            sell_recommendation=dto.sell_recommendation,
            sell_reasons=sell_reasons_json,
            analyzed_at=datetime.now(),
            is_active=dto.is_active if dto.is_active is not None else True,
        )

        return self._history_to_dto(model)

    async def get_analysis_history(self, history_id: int) -> AnalysisHistoryDTO:
        """분석 이력 상세 조회"""
        from fastapi import HTTPException, status
        from src.adapters.database.repositories import AnalysisHistoryRepository

        if not self.session:
            raise StrategyError("Database session not provided")

        history_repo = AnalysisHistoryRepository(self.session)
        model = await history_repo.get_by_id(history_id)

        if not model:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Analysis history not found: {history_id}",
            )

        return self._history_to_dto(model)

    async def list_analysis_history(
        self,
        analysis_type: str,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AnalysisHistoryListDTO:
        """분석 이력 목록 조회"""
        from src.adapters.database.repositories import AnalysisHistoryRepository

        if not self.session:
            raise StrategyError("Database session not provided")

        history_repo = AnalysisHistoryRepository(self.session)
        histories = await history_repo.get_by_type(
            analysis_type=analysis_type,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )
        total_count = await history_repo.count_by_type(analysis_type, is_active)

        items = [self._history_to_dto(h) for h in histories]

        return AnalysisHistoryListDTO(
            items=items,
            total_count=total_count,
        )

    @transaction
    async def delete_analysis_history(self, session: AsyncSession, history_id: int) -> bool:
        """분석 이력 삭제"""
        from src.adapters.database.repositories import AnalysisHistoryRepository

        history_repo = AnalysisHistoryRepository(session)
        return await history_repo.delete_by_id(history_id)

    @transaction
    async def set_analysis_history_active(
        self, session: AsyncSession, history_id: int, is_active: bool
    ) -> AnalysisHistoryDTO:
        """분석 이력 활성 추적 상태 변경"""
        from fastapi import HTTPException, status
        from src.adapters.database.repositories import AnalysisHistoryRepository

        history_repo = AnalysisHistoryRepository(session)
        updated = await history_repo.set_active(history_id, is_active)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Analysis history not found: {history_id}",
            )
        return self._history_to_dto(updated)

    @transaction
    async def refresh_analysis_history(
        self, session: AsyncSession, analysis_type: str, market_data_service=None
    ) -> AnalysisHistoryRefreshResultDTO:
        """활성 추적 종목 분석 갱신"""
        import logging
        from src.adapters.database.repositories import AnalysisHistoryRepository

        logger = logging.getLogger(__name__)
        errors: list[str] = []
        updated_items: list[AnalysisHistoryDTO] = []

        history_repo = AnalysisHistoryRepository(session)
        active_symbols = await history_repo.get_active_symbols(analysis_type)

        if not active_symbols:
            return AnalysisHistoryRefreshResultDTO(
                updated_count=0,
                items=[],
                errors=["No active tracking items found"],
            )

        logger.info(f"[Refresh] Refreshing {len(active_symbols)} {analysis_type} items")

        # 종목명 조회를 위한 유니버스 레포지토리
        universe_repo = StockUniverseRepository(session)

        for symbol in active_symbols:
            try:
                # 종목명 조회 (DB에 없는 경우)
                stock_name = None
                latest = await history_repo.get_latest_by_symbol(symbol, analysis_type)
                if latest and not latest.name:
                    # DB 유니버스에서 조회
                    universe_stock = await universe_repo.get_by_symbol(symbol)
                    if universe_stock and universe_stock.name:
                        stock_name = universe_stock.name
                    elif market_data_service:
                        # API 폴백 (일반주식 + ETF 지원)
                        try:
                            stock_name = await market_data_service.get_stock_name(symbol)
                        except Exception:
                            pass

                if analysis_type == "sell":
                    sell_result = await self.analyze_sell_signal(symbol)
                    sell_reasons_json = json.dumps(sell_result.sell_reasons, ensure_ascii=False)

                    if latest:
                        update_kwargs = {
                            "current_price": sell_result.current_price,
                            "ma_short": sell_result.ma_short,
                            "ma_long": sell_result.ma_long,
                            "ma_gap_ratio": sell_result.ma_gap_ratio,
                            "stoch_k": sell_result.stoch_k,
                            "stoch_d": sell_result.stoch_d,
                            "rsi": sell_result.rsi,
                            "is_death_cross": sell_result.is_death_cross,
                            "is_stoch_overbought": sell_result.is_stoch_overbought,
                            "is_rsi_overbought": sell_result.is_rsi_overbought,
                            "sell_signal_strength": sell_result.sell_signal_strength,
                            "sell_recommendation": sell_result.sell_recommendation,
                            "sell_reasons": sell_reasons_json,
                            "analyzed_at": datetime.now(),
                        }
                        if stock_name:
                            update_kwargs["name"] = stock_name

                        await history_repo.update_by_id(latest.id, **update_kwargs)
                        updated = await history_repo.get_by_id(latest.id)
                        if updated:
                            updated_items.append(self._history_to_dto(updated))

                elif analysis_type == "buy":
                    from src.application.domain.strategy.buy_strategy_service import BuyStrategyService
                    buy_service = BuyStrategyService(session)
                    scan_result = await buy_service.scan_golden_cross_candidates(gc_only=False)

                    stock_data = next((s for s in scan_result.stocks if s.symbol == symbol), None)
                    if stock_data and latest:
                        update_kwargs = {
                            "current_price": stock_data.current_price,
                            "ma_short": stock_data.ma_short,
                            "ma_long": stock_data.ma_long,
                            "ma_gap_ratio": stock_data.ma_gap_ratio,
                            "stoch_k": stock_data.stoch_k,
                            "stoch_d": stock_data.stoch_d,
                            "gc_state": stock_data.gc_state,
                            "is_gc_active": stock_data.is_gc_active,
                            "analyzed_at": datetime.now(),
                        }
                        if stock_name:
                            update_kwargs["name"] = stock_name

                        await history_repo.update_by_id(latest.id, **update_kwargs)
                        updated = await history_repo.get_by_id(latest.id)
                        if updated:
                            updated_items.append(self._history_to_dto(updated))

            except Exception as e:
                error_msg = f"{symbol}: {str(e)}"
                logger.warning(f"[Refresh] Error: {error_msg}")
                errors.append(error_msg)

        return AnalysisHistoryRefreshResultDTO(
            updated_count=len(updated_items),
            items=updated_items,
            errors=errors,
        )

    def _history_to_dto(self, model) -> AnalysisHistoryDTO:
        """AnalysisHistoryModel을 DTO로 변환"""
        sell_reasons = None
        if model.sell_reasons:
            try:
                sell_reasons = json.loads(model.sell_reasons)
            except (json.JSONDecodeError, TypeError):
                sell_reasons = [model.sell_reasons] if model.sell_reasons else None

        return AnalysisHistoryDTO(
            id=model.id,
            analysis_type=model.analysis_type,
            symbol=model.symbol,
            name=model.name,
            current_price=model.current_price,
            ma_short=model.ma_short,
            ma_long=model.ma_long,
            ma_gap_ratio=model.ma_gap_ratio,
            stoch_k=model.stoch_k,
            stoch_d=model.stoch_d,
            gc_state=model.gc_state,
            is_gc_active=model.is_gc_active,
            rsi=model.rsi,
            is_death_cross=model.is_death_cross,
            is_stoch_overbought=model.is_stoch_overbought,
            is_rsi_overbought=model.is_rsi_overbought,
            sell_signal_strength=model.sell_signal_strength,
            sell_recommendation=model.sell_recommendation,
            sell_reasons=sell_reasons,
            analyzed_at=model.analyzed_at,
            note=model.note,
            is_active=model.is_active,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
