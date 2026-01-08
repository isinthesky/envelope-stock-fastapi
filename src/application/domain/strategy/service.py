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
from src.adapters.external.kis_api.client import get_kis_client
from src.application.common.decorators import transaction
from src.application.common.exceptions import StrategyError
from src.application.domain.strategy.dto import (
    GoldenCrossConfigDTO,
    GoldenCrossScanItemDTO,
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

    async def scan_golden_cross_candidates(
        self,
        market: str | None = None,
        stoch_threshold: float = 30.0,
        gc_only: bool = True,
    ) -> GoldenCrossScanListDTO:
        """
        골든크로스 종목 스캔

        기본 스크리닝 통과 종목에 대해 기술적 지표를 계산하여
        골든크로스 전략 조건에 부합하는 종목을 필터링합니다.

        - 2번의 API 호출로 약 160~170개 캔들 수집
        - DB 캐싱을 통해 반복 호출 최소화
        - MA40/MA160 지표 사용

        Args:
            market: 시장 필터 (KOSPI/KOSDAQ)
            stoch_threshold: Stochastic 과매도 임계값 (기본 30)
            gc_only: 골든크로스 활성 종목만 반환 (기본 True)

        Returns:
            GoldenCrossScanListDTO: 스캔 결과
        """
        if not self.session:
            raise StrategyError("Database session not provided")

        import asyncio
        import logging
        from datetime import timedelta

        import pandas as pd

        from src.application.common.indicators import TechnicalIndicators
        from src.adapters.database.repositories.ohlcv_repository import OHLCVRepository
        from src.application.domain.market_data.service import MarketDataService

        logger = logging.getLogger(__name__)
        scan_time = datetime.now()
        errors: list[str] = []
        results: list[GoldenCrossScanItemDTO] = []

        # 1. 유니버스에서 스크리닝 통과 종목 조회
        universe_repo = StockUniverseRepository(self.session)
        market_type = MarketType(market) if market else None
        stocks = await universe_repo.get_eligible_stocks(market=market_type)

        if not stocks:
            return GoldenCrossScanListDTO(
                stocks=[],
                total_scanned=0,
                gc_active_count=0,
                pullback_waiting_count=0,
                ready_to_buy_count=0,
                scan_time=scan_time,
                errors=["No eligible stocks found in universe"],
            )

        logger.info(f"[GC Scan] Scanning {len(stocks)} eligible stocks with MA40/MA160")

        # 2. MarketDataService 초기화
        from src.adapters.cache.redis_client import get_redis_client

        kis_client = KISAPIClient()
        redis_client = await get_redis_client()
        market_data_service = MarketDataService(kis_client, redis_client)

        # 3. 날짜 범위 설정 (MA160을 위해 약 240일 필요)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=240)
        ohlcv_repo = OHLCVRepository(self.session) if self.session else None

        # 4. 종목별 기술적 지표 계산
        for stock in stocks:
            try:
                df = None

                if ohlcv_repo:
                    availability = await ohlcv_repo.check_data_availability(
                        symbol=stock.symbol,
                        start_date=start_date,
                        end_date=end_date,
                        interval="1d",
                    )
                    latest = availability.get("latest")
                    can_use_cached = availability["is_complete"]
                    if latest and availability.get("count", 0) >= 160:
                        if (end_date - latest) <= timedelta(days=3):
                            can_use_cached = True

                    if can_use_cached:
                        cached_df = await ohlcv_repo.get_candles_to_dataframe(
                            symbol=stock.symbol,
                            start_date=start_date,
                            end_date=end_date,
                            interval="1d",
                        )
                        if not cached_df.empty:
                            df = cached_df

                if df is None:
                    # 2번의 API 호출로 약 240일 데이터 수집 (MA160용)
                    all_candles: list = []

                    # 첫 번째 호출: 최근 120일 (약 80 캔들)
                    chart_data1 = await market_data_service.get_chart_data(
                        symbol=stock.symbol,
                        interval="1d",
                        start_date=end_date - timedelta(days=120),
                        end_date=end_date,
                    )
                    if chart_data1.candles:
                        all_candles.extend(chart_data1.candles)

                    # 두 번째 호출: 이전 120일
                    if all_candles:
                        earliest = min(c.timestamp for c in all_candles)
                        chart_data2 = await market_data_service.get_chart_data(
                            symbol=stock.symbol,
                            interval="1d",
                            start_date=earliest - timedelta(days=120),
                            end_date=earliest - timedelta(days=1),
                        )
                        if chart_data2.candles:
                            all_candles.extend(chart_data2.candles)

                    if not all_candles:
                        logger.debug(f"[GC Scan] {stock.symbol}: No candle data")
                        continue

                    candles_by_date = {c.timestamp: c for c in all_candles}
                    all_candles = sorted(candles_by_date.values(), key=lambda c: c.timestamp)

                    if ohlcv_repo:
                        try:
                            await ohlcv_repo.save_candles_bulk(
                                symbol=stock.symbol,
                                candles=all_candles,
                                interval="1d",
                                source="kis",
                            )
                            await self.session.commit()
                        except Exception as cache_error:
                            await self.session.rollback()
                            logger.warning(
                                "[GC Scan] Failed to cache %s candles: %s",
                                stock.symbol,
                                cache_error,
                            )

                    df = pd.DataFrame(
                        [
                            {
                                "timestamp": c.timestamp,
                                "open": float(c.open),
                                "high": float(c.high),
                                "low": float(c.low),
                                "close": float(c.close),
                                "volume": int(c.volume),
                            }
                            for c in all_candles
                        ]
                    )

                df = (
                    df.drop_duplicates(subset=["timestamp"])
                    .sort_values("timestamp")
                    .reset_index(drop=True)
                )

                candle_count = len(df)
                # MA160 계산을 위해 최소 160개 필요
                if candle_count < 160:
                    logger.debug(f"[GC Scan] {stock.symbol}: Insufficient data, need 160, got {candle_count}")
                    continue

                # 지표 계산 (MA40/MA160)
                df = TechnicalIndicators.prepare_golden_cross_indicators(
                    df,
                    short_ma_period=40,
                    long_ma_period=160,
                    stoch_k_period=14,
                    stoch_d_period=3,
                )

                # 최신 행 추출
                latest = df.iloc[-1]
                ma_short = float(latest["ma_short"]) if pd.notna(latest["ma_short"]) else 0
                ma_long = float(latest["ma_long"]) if pd.notna(latest["ma_long"]) else 0
                stoch_k = float(latest["stoch_k"]) if pd.notna(latest["stoch_k"]) else 50
                stoch_d = float(latest["stoch_d"]) if pd.notna(latest["stoch_d"]) else 50
                close = float(latest["close"])

                # 골든크로스 상태 판정
                is_gc_active = ma_short > ma_long

                # gc_only 필터
                if gc_only and not is_gc_active:
                    continue

                # 상태 결정
                gc_state = self._determine_gc_state(
                    is_gc_active=is_gc_active,
                    stoch_k=stoch_k,
                    stoch_threshold=stoch_threshold,
                )

                # MA 갭 비율 계산
                ma_gap_ratio = ((ma_short - ma_long) / ma_long) if ma_long > 0 else 0

                # 결과 추가
                results.append(
                    GoldenCrossScanItemDTO(
                        symbol=stock.symbol,
                        name=stock.name,
                        market=stock.market,
                        current_price=Decimal(str(close)),
                        ma_short=Decimal(str(round(ma_short, 2))),
                        ma_long=Decimal(str(round(ma_long, 2))),
                        ma_gap_ratio=round(ma_gap_ratio * 100, 2),  # 백분율
                        stoch_k=round(stoch_k, 2),
                        stoch_d=round(stoch_d, 2),
                        is_gc_active=is_gc_active,
                        gc_state=gc_state,
                        market_cap=stock.market_cap,
                        screening_score=stock.screening_score,
                    )
                )

                # Rate limit 대응
                await asyncio.sleep(0.05)

            except Exception as e:
                error_msg = f"{stock.symbol}: {str(e)}"
                logger.warning(f"[GC Scan] Error processing {error_msg}")
                errors.append(error_msg)

        # 5. 결과 정렬 (READY_TO_BUY > WAITING_FOR_PULLBACK > 기타)
        state_order = {"READY_TO_BUY": 0, "WAITING_FOR_PULLBACK": 1, "GC_ACTIVE": 2, "NOT_GC": 3}
        results.sort(key=lambda x: (state_order.get(x.gc_state, 99), -float(x.screening_score or 0)))

        # 6. 통계 계산
        gc_active_count = sum(1 for r in results if r.is_gc_active)
        pullback_waiting_count = sum(1 for r in results if r.gc_state == "WAITING_FOR_PULLBACK")
        ready_to_buy_count = sum(1 for r in results if r.gc_state == "READY_TO_BUY")

        logger.info(
            f"[GC Scan] Complete: {len(results)} results, "
            f"GC Active: {gc_active_count}, Pullback: {pullback_waiting_count}, "
            f"Ready: {ready_to_buy_count}, Errors: {len(errors)}"
        )

        return GoldenCrossScanListDTO(
            stocks=results,
            total_scanned=len(stocks),
            gc_active_count=gc_active_count,
            pullback_waiting_count=pullback_waiting_count,
            ready_to_buy_count=ready_to_buy_count,
            scan_time=scan_time,
            errors=errors,
        )

    def _determine_gc_state(
        self,
        is_gc_active: bool,
        stoch_k: float,
        stoch_threshold: float,
    ) -> str:
        """
        골든크로스 상태 결정

        Args:
            is_gc_active: 골든크로스 활성 여부
            stoch_k: 현재 Stochastic K 값
            stoch_threshold: 과매도 임계값

        Returns:
            str: 상태 문자열
        """
        if not is_gc_active:
            return "NOT_GC"

        # 골든크로스 활성 상태에서 Stochastic 확인
        if stoch_k < stoch_threshold:
            # Stochastic이 과매도 구간에 있으면 매수 준비
            return "READY_TO_BUY"
        elif stoch_k < 50:
            # 중간 구간이면 눌림목 대기
            return "WAITING_FOR_PULLBACK"
        else:
            # Stochastic이 높으면 일반 골든크로스 활성
            return "GC_ACTIVE"

    # ==================== 매도 시그널 분석 ====================

    async def analyze_sell_signal(
        self,
        symbol: str,
        stoch_overbought: float = 70.0,
        rsi_overbought: float = 70.0,
    ) -> SellSignalAnalysisDTO:
        """
        매도 시그널 분석

        종목의 기술적 지표를 분석하여 매도 시그널을 판단합니다.
        - MA40/MA160 데드크로스 확인
        - Stochastic 과매수 확인
        - RSI 과매수 확인

        Args:
            symbol: 종목코드
            stoch_overbought: Stochastic 과매수 임계값 (기본 70)
            rsi_overbought: RSI 과매수 임계값 (기본 70)

        Returns:
            SellSignalAnalysisDTO: 매도 시그널 분석 결과
        """
        import logging
        from datetime import timedelta

        import pandas as pd

        from src.adapters.cache.redis_client import get_redis_client
        from src.adapters.database.repositories.ohlcv_repository import OHLCVRepository
        from src.application.common.indicators import TechnicalIndicators
        from src.application.domain.market_data.service import MarketDataService

        logger = logging.getLogger(__name__)
        analyzed_at = datetime.now()

        # 1. MarketDataService 초기화
        kis_client = KISAPIClient()
        redis_client = await get_redis_client()
        market_data_service = MarketDataService(kis_client, redis_client)

        # 2. 날짜 범위 설정 (MA160 + RSI14 여유분 = 약 240일)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=240)

        ohlcv_repo = OHLCVRepository(self.session) if self.session else None

        # 3. OHLCV 데이터 조회 (캐시 우선)
        df = None

        if ohlcv_repo:
            try:
                availability = await ohlcv_repo.check_data_availability(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    interval="1d",
                )
                if availability.get("count", 0) >= 160:
                    latest = availability.get("latest")
                    if latest and (end_date - latest) <= timedelta(days=3):
                        cached_df = await ohlcv_repo.get_candles_to_dataframe(
                            symbol=symbol,
                            start_date=start_date,
                            end_date=end_date,
                            interval="1d",
                        )
                        if not cached_df.empty:
                            df = cached_df
                            logger.info(f"[Sell Signal] {symbol}: Using cached data ({len(df)} candles)")
            except Exception as cache_err:
                logger.warning(f"[Sell Signal] Cache check failed for {symbol}: {cache_err}")

        if df is None:
            # API 2회 호출로 약 240일 데이터 수집
            all_candles: list = []

            # 첫 번째 호출: 최근 120일
            chart_data1 = await market_data_service.get_chart_data(
                symbol=symbol,
                interval="1d",
                start_date=end_date - timedelta(days=120),
                end_date=end_date,
            )
            if chart_data1.candles:
                all_candles.extend(chart_data1.candles)

            # 두 번째 호출: 이전 120일
            if all_candles:
                earliest = min(c.timestamp for c in all_candles)
                chart_data2 = await market_data_service.get_chart_data(
                    symbol=symbol,
                    interval="1d",
                    start_date=earliest - timedelta(days=120),
                    end_date=earliest - timedelta(days=1),
                )
                if chart_data2.candles:
                    all_candles.extend(chart_data2.candles)

            if not all_candles:
                raise StrategyError(f"No candle data available for {symbol}")

            # 중복 제거 및 정렬
            candles_by_date = {c.timestamp: c for c in all_candles}
            all_candles = sorted(candles_by_date.values(), key=lambda c: c.timestamp)

            # DB 캐싱
            if ohlcv_repo:
                try:
                    await ohlcv_repo.save_candles_bulk(
                        symbol=symbol,
                        candles=all_candles,
                        interval="1d",
                        source="kis",
                    )
                    await self.session.commit()
                except Exception as cache_err:
                    await self.session.rollback()
                    logger.warning(f"[Sell Signal] Failed to cache {symbol}: {cache_err}")

            df = pd.DataFrame([
                {
                    "timestamp": c.timestamp,
                    "open": float(c.open),
                    "high": float(c.high),
                    "low": float(c.low),
                    "close": float(c.close),
                    "volume": int(c.volume),
                }
                for c in all_candles
            ])

        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        candle_count = len(df)

        if candle_count < 160:
            raise StrategyError(f"Insufficient data for {symbol}: need 160 candles, got {candle_count}")

        # 4. 기술적 지표 계산 (MA40/MA160 + Stochastic + RSI)
        df = TechnicalIndicators.prepare_golden_cross_indicators(
            df,
            short_ma_period=40,
            long_ma_period=160,
            stoch_k_period=14,
            stoch_d_period=3,
        )

        # RSI 계산 추가
        close_prices = df["close"].tolist()
        rsi_value = TechnicalIndicators.calculate_rsi(close_prices, period=14)
        df["rsi"] = rsi_value if rsi_value is not None else 50.0

        # 5. 최신 값 추출
        latest = df.iloc[-1]
        close = float(latest["close"])
        ma_short = float(latest["ma_short"]) if pd.notna(latest["ma_short"]) else 0
        ma_long = float(latest["ma_long"]) if pd.notna(latest["ma_long"]) else 0
        stoch_k = float(latest["stoch_k"]) if pd.notna(latest["stoch_k"]) else 50
        stoch_d = float(latest["stoch_d"]) if pd.notna(latest["stoch_d"]) else 50
        rsi = float(latest["rsi"]) if pd.notna(latest["rsi"]) else 50

        # 6. 매도 시그널 판단
        is_death_cross = ma_short < ma_long
        is_stoch_overbought = stoch_k > stoch_overbought
        is_rsi_overbought = rsi > rsi_overbought
        ma_gap_ratio = ((ma_short - ma_long) / ma_long * 100) if ma_long > 0 else 0

        # 매도 근거 수집
        sell_reasons: list[str] = []
        sell_score = 0

        # 데드크로스 (강력 매도 시그널)
        if is_death_cross:
            sell_reasons.append(f"데드크로스 발생 (MA40 {ma_short:,.0f} < MA160 {ma_long:,.0f})")
            sell_score += 2

        # Stochastic 과매수
        if is_stoch_overbought:
            sell_reasons.append(f"Stochastic 과매수 (K={stoch_k:.1f} > {stoch_overbought})")
            sell_score += 1
            if stoch_k > 80:
                sell_reasons.append("Stochastic 극단적 과매수 (K > 80)")
                sell_score += 1

        # RSI 과매수
        if is_rsi_overbought:
            sell_reasons.append(f"RSI 과매수 (RSI={rsi:.1f} > {rsi_overbought})")
            sell_score += 1
            if rsi > 80:
                sell_reasons.append("RSI 극단적 과매수 (RSI > 80)")
                sell_score += 1

        # Stochastic + RSI 동시 과매수 (추가 점수)
        if is_stoch_overbought and is_rsi_overbought:
            sell_reasons.append("Stochastic & RSI 동시 과매수 - 고점 가능성 높음")

        # MA 갭이 너무 벌어진 경우 (과열)
        if ma_gap_ratio > 20:
            sell_reasons.append(f"MA 갭 과대 ({ma_gap_ratio:.1f}%) - 평균 회귀 예상")
            sell_score += 1

        # 점수를 0-5 범위로 제한
        sell_signal_strength = min(5, sell_score)

        # 추천 등급 결정
        recommendation_map = {
            0: "HOLD",
            1: "WATCH",
            2: "WEAK_SELL",
            3: "CONSIDER_SELL",
            4: "SELL",
            5: "STRONG_SELL",
        }
        sell_recommendation = recommendation_map.get(sell_signal_strength, "HOLD")

        if not sell_reasons:
            sell_reasons.append("현재 매도 시그널 없음 - 보유 유지")

        logger.info(
            f"[Sell Signal] {symbol}: strength={sell_signal_strength}, "
            f"recommendation={sell_recommendation}, reasons={len(sell_reasons)}"
        )

        return SellSignalAnalysisDTO(
            symbol=symbol,
            name=None,  # 종목명은 별도 조회 필요
            current_price=Decimal(str(close)),
            analyzed_at=analyzed_at,
            ma_short=Decimal(str(round(ma_short, 2))),
            ma_long=Decimal(str(round(ma_long, 2))),
            ma_gap_ratio=round(ma_gap_ratio, 2),
            is_death_cross=is_death_cross,
            stoch_k=round(stoch_k, 2),
            stoch_d=round(stoch_d, 2),
            is_stoch_overbought=is_stoch_overbought,
            rsi=round(rsi, 2),
            is_rsi_overbought=is_rsi_overbought,
            sell_signal_strength=sell_signal_strength,
            sell_recommendation=sell_recommendation,
            sell_reasons=sell_reasons,
            candle_count=candle_count,
        )
