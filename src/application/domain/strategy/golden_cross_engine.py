# -*- coding: utf-8 -*-
"""
Golden Cross Engine - 골든크로스 전략 실행 엔진

장 마감 후 1회 실행 (15:35)
1. 종목 스크리닝
2. OHLCV 데이터 조회 (250일)
3. 지표 계산 (MA60, MA200, Stochastic)
4. 상태 머신 업데이트 & 시그널 생성
5. SafetyGuard 검증
6. 주문 생성
"""

import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Sequence

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.strategy import StrategyModel
from src.adapters.database.models.strategy_signal import SignalStatus, SignalType
from src.adapters.database.models.strategy_symbol_state import SymbolState
from src.adapters.database.repositories.strategy_repository import StrategyRepository
from src.adapters.database.repositories.strategy_signal_repository import (
    StrategySignalRepository,
)
from src.adapters.database.repositories.strategy_symbol_state_repository import (
    StrategySymbolStateRepository,
)
from src.adapters.external.kis_api.client import KISAPIClient
from src.application.common.indicators import TechnicalIndicators
from src.application.domain.account.service import AccountService
from src.application.domain.market_data.service import MarketDataService
from src.application.domain.news_trading.safety_guard import SafetyGuard
from src.application.domain.order.dto import OrderCreateRequestDTO
from src.application.domain.order.service import OrderService
from src.application.domain.strategy.dto import (
    GoldenCrossConfigDTO,
    StrategyExecuteResultDTO,
    StrategySignalDTO,
)
from src.application.domain.strategy.state_machine import (
    GoldenCrossStateMachine,
    IndicatorSnapshot,
    Signal,
)
from src.application.domain.strategy.stock_screener import StockScreener

logger = logging.getLogger(__name__)


class GoldenCrossEngine:
    """
    골든크로스 전략 실행 엔진

    장 마감 후 종목별 상태 머신을 업데이트하고 시그널을 생성합니다.
    """

    def __init__(
        self,
        session: AsyncSession,
        kis_client: KISAPIClient | None = None,
    ):
        """
        Args:
            session: DB 세션
            kis_client: KIS API 클라이언트
        """
        self.session = session
        self.kis_client = kis_client or KISAPIClient()
        self.indicators = TechnicalIndicators()

        # Repositories
        self.strategy_repo = StrategyRepository(session)
        self.symbol_state_repo = StrategySymbolStateRepository(session)
        self.signal_repo = StrategySignalRepository(session)

        # Services
        self.market_data_service = MarketDataService(self.kis_client)
        self.account_service = AccountService(self.kis_client)

    async def execute(
        self,
        strategy_id: int,
        dry_run: bool = True,
    ) -> StrategyExecuteResultDTO:
        """
        전략 실행

        Args:
            strategy_id: 전략 ID
            dry_run: Dry Run 모드 (주문 생성 안함)

        Returns:
            StrategyExecuteResultDTO: 실행 결과
        """
        executed_at = datetime.now()
        signals: list[StrategySignalDTO] = []
        errors: list[str] = []
        buy_count = 0
        sell_count = 0
        orders_created = 0

        try:
            # 1. 전략 조회
            strategy = await self.strategy_repo.get_by_id(strategy_id)
            if not strategy:
                errors.append(f"Strategy {strategy_id} not found")
                return self._create_result(
                    strategy_id, executed_at, dry_run, 0, 0, 0, 0, signals, errors
                )

            # 2. 전략 설정 파싱
            config = self._parse_config(strategy)

            # 3. 상태 머신 초기화
            state_machine = GoldenCrossStateMachine(config)

            # 4. SafetyGuard 초기화
            safety_guard = await self._init_safety_guard(strategy)

            # 5. 종목 스크리닝
            screener = StockScreener(self.session, self.kis_client, config.screener_config)
            candidates = await screener.get_screening_candidates()

            # 기존 전략 종목도 포함
            existing_symbols = set(strategy.symbol_list)
            all_symbols = list(set(candidates) | existing_symbols)

            logger.info(f"[GC Engine] Processing {len(all_symbols)} symbols for strategy {strategy_id}")

            # 6. 종목별 처리
            for symbol in all_symbols:
                try:
                    result = await self._process_symbol(
                        strategy=strategy,
                        symbol=symbol,
                        config=config,
                        state_machine=state_machine,
                        safety_guard=safety_guard,
                        dry_run=dry_run,
                    )

                    if result:
                        signals.append(result)
                        if result.signal_type == SignalType.BUY.value:
                            buy_count += 1
                            if not dry_run and result.signal_status == SignalStatus.EXECUTED.value:
                                orders_created += 1
                        elif result.signal_type == SignalType.SELL.value:
                            sell_count += 1
                            if not dry_run and result.signal_status == SignalStatus.EXECUTED.value:
                                orders_created += 1

                except Exception as e:
                    error_msg = f"Error processing {symbol}: {str(e)}"
                    logger.error(f"[GC Engine] {error_msg}")
                    errors.append(error_msg)

            # 7. 전략 실행 통계 업데이트
            await self.strategy_repo.update_execution_stats(
                strategy_id, success=len(errors) == 0
            )

            await self.session.commit()

        except Exception as e:
            error_msg = f"Strategy execution failed: {str(e)}"
            logger.exception(f"[GC Engine] {error_msg}")
            errors.append(error_msg)
            await self.session.rollback()

        return self._create_result(
            strategy_id,
            executed_at,
            dry_run,
            len(all_symbols) if 'all_symbols' in locals() else 0,
            buy_count,
            sell_count,
            orders_created,
            signals,
            errors,
        )

    async def _process_symbol(
        self,
        strategy: StrategyModel,
        symbol: str,
        config: GoldenCrossConfigDTO,
        state_machine: GoldenCrossStateMachine,
        safety_guard: SafetyGuard,
        dry_run: bool,
    ) -> StrategySignalDTO | None:
        """
        개별 종목 처리

        Args:
            strategy: 전략 모델
            symbol: 종목코드
            config: 전략 설정
            state_machine: 상태 머신
            safety_guard: SafetyGuard
            dry_run: Dry Run 모드

        Returns:
            StrategySignalDTO | None: 시그널 (발생 시)
        """
        # 1. OHLCV 데이터 조회
        df = await self._fetch_ohlcv(symbol, config.lookback_days)
        if df is None or len(df) < config.ma_config.long_period + 10:
            logger.warning(f"[GC Engine] Insufficient data for {symbol}")
            return None

        # 2. 지표 계산
        df = TechnicalIndicators.prepare_golden_cross_indicators(
            df,
            short_ma_period=config.ma_config.short_period,
            long_ma_period=config.ma_config.long_period,
            stoch_k_period=config.stochastic_config.k_period,
            stoch_d_period=config.stochastic_config.d_period,
        )

        # 3. 현재/이전 지표 스냅샷
        if len(df) < 2:
            return None

        current_row = df.iloc[-1]
        prev_row = df.iloc[-2]

        current_snapshot = self._create_snapshot(current_row)
        prev_snapshot = self._create_snapshot(prev_row)

        # 4. 현재 상태 조회 (없으면 생성)
        state = await self.symbol_state_repo.get_by_strategy_and_symbol(
            strategy.id, symbol
        )

        if not state:
            # 초기 상태 결정
            initial_state = state_machine.get_initial_state(current_snapshot)
            state = await self.symbol_state_repo.upsert(
                strategy_id=strategy.id,
                symbol=symbol,
                state=initial_state.value,
            )

        # 5. 상태 머신 처리
        transition = state_machine.process(
            current=current_snapshot,
            prev=prev_snapshot,
            current_state=SymbolState(state.state),
            gc_date=state.gc_date,
            pullback_date=state.pullback_date,
            entry_price=state.entry_price,
            entry_date=state.entry_date,
        )

        # 6. 지표 스냅샷 업데이트
        await self.symbol_state_repo.update_indicators(
            strategy_id=strategy.id,
            symbol=symbol,
            ma_short=Decimal(str(current_snapshot.ma_short)),
            ma_long=Decimal(str(current_snapshot.ma_long)),
            stoch_k=Decimal(str(current_snapshot.stoch_k)),
            stoch_d=Decimal(str(current_snapshot.stoch_d)),
            close=current_snapshot.close,
        )

        # 7. 시그널 처리
        if transition.signal == Signal.HOLD:
            # 상태만 업데이트
            if state.state != transition.new_state.value:
                await self.symbol_state_repo.update_state(
                    strategy_id=strategy.id,
                    symbol=symbol,
                    new_state=transition.new_state,
                    gc_date=transition.gc_date,
                    pullback_date=transition.pullback_date,
                )
            return None

        # 8. 매수/매도 시그널 처리
        return await self._handle_signal(
            strategy=strategy,
            symbol=symbol,
            transition=transition,
            current_snapshot=current_snapshot,
            state=state,
            config=config,
            safety_guard=safety_guard,
            dry_run=dry_run,
        )

    async def _handle_signal(
        self,
        strategy: StrategyModel,
        symbol: str,
        transition,
        current_snapshot: IndicatorSnapshot,
        state,
        config: GoldenCrossConfigDTO,
        safety_guard: SafetyGuard,
        dry_run: bool,
    ) -> StrategySignalDTO | None:
        """
        시그널 처리 (매수/매도)
        """
        signal_type = (
            SignalType.BUY if transition.signal == Signal.BUY else SignalType.SELL
        )

        # 시그널 저장
        signal_model = await self.signal_repo.create_signal(
            strategy_id=strategy.id,
            symbol=symbol,
            signal_type=signal_type,
            signal_price=current_snapshot.close,
            prev_state=state.state,
            new_state=transition.new_state.value,
            ma_short=Decimal(str(current_snapshot.ma_short)),
            ma_long=Decimal(str(current_snapshot.ma_long)),
            stoch_k=Decimal(str(current_snapshot.stoch_k)),
            stoch_d=Decimal(str(current_snapshot.stoch_d)),
            note=transition.reason,
        )

        if dry_run:
            # Dry Run: 상태만 업데이트
            logger.info(
                f"[GC Engine DRY RUN] {symbol} {signal_type.value.upper()} @ {current_snapshot.close}"
            )
            await self._update_state_after_signal(
                strategy.id, symbol, transition, current_snapshot
            )
            await self.signal_repo.update_execution(
                signal_model.id,
                status=SignalStatus.SKIPPED,
            )
            return self._model_to_dto(signal_model)

        # SafetyGuard 체크
        can_trade, block_reason, block_message = safety_guard.can_trade()
        if not can_trade:
            logger.warning(f"[GC Engine] SafetyGuard blocked: {block_message}")
            await self.signal_repo.update_execution(
                signal_model.id,
                status=SignalStatus.SKIPPED,
            )
            # SafetyGuard 차단 시에도 상태 업데이트 (반복 시그널 방지)
            # 매수 차단: 상태를 WAITING_FOR_GC로 리셋
            # 매도 차단: 상태는 IN_POSITION 유지 (다음 기회에 재시도)
            if signal_type == SignalType.BUY:
                await self.symbol_state_repo.reset_to_waiting(strategy.id, symbol)
                logger.info(f"[GC Engine] {symbol} state reset to WAITING_FOR_GC after SafetyGuard block")
            return self._model_to_dto(signal_model)

        # 실제 주문 실행
        try:
            if signal_type == SignalType.BUY:
                await self._execute_buy(
                    strategy, symbol, current_snapshot.close, config, signal_model
                )
            else:
                await self._execute_sell(
                    strategy, symbol, current_snapshot.close, state, signal_model
                )

            await self._update_state_after_signal(
                strategy.id, symbol, transition, current_snapshot
            )

        except Exception as e:
            logger.error(f"[GC Engine] Order execution failed: {e}")
            await self.signal_repo.update_execution(
                signal_model.id,
                status=SignalStatus.FAILED,
            )

        # 갱신된 시그널 다시 조회
        updated_signal = await self.signal_repo.get_by_id(signal_model.id)
        return self._model_to_dto(updated_signal)

    async def _execute_buy(
        self,
        strategy: StrategyModel,
        symbol: str,
        price: Decimal,
        config: GoldenCrossConfigDTO,
        signal_model,
    ):
        """매수 주문 실행"""
        # 계좌 잔고 조회
        balance = await self.account_service.get_balance(strategy.account_no)

        # 포지션 사이즈 계산
        allocation = float(balance.total_cash) * config.position.allocation_ratio
        quantity = int(allocation / float(price))

        if quantity <= 0:
            raise ValueError("Insufficient cash for buy order")

        # 주문 생성
        order_service = OrderService(self.kis_client, self.session)
        order_request = OrderCreateRequestDTO(
            symbol=symbol,
            order_type="buy",
            price_type="limit",
            price=price,
            quantity=quantity,
            account_no=strategy.account_no,
        )

        order_result = await order_service.create_order(self.session, order_request)

        # 시그널 업데이트
        await self.signal_repo.update_execution(
            signal_model.id,
            status=SignalStatus.EXECUTED,
            executed_price=price,
            executed_quantity=quantity,
            order_no=getattr(order_result, "order_no", None),
        )

        logger.info(f"[GC Engine] BUY {symbol} x {quantity} @ {price}")

    async def _execute_sell(
        self,
        strategy: StrategyModel,
        symbol: str,
        price: Decimal,
        state,
        signal_model,
    ):
        """매도 주문 실행"""
        # 보유 수량 조회
        positions = await self.account_service.get_positions(strategy.account_no)
        target_position = None
        for pos in positions.positions:
            if pos.symbol == symbol:
                target_position = pos
                break

        if not target_position or target_position.quantity <= 0:
            raise ValueError("No position to sell")

        # 수익률 계산
        realized_pnl = None
        realized_pnl_ratio = None
        if state.entry_price:
            realized_pnl = (price - state.entry_price) * target_position.quantity
            realized_pnl_ratio = (price - state.entry_price) / state.entry_price

        # 주문 생성
        order_service = OrderService(self.kis_client, self.session)
        order_request = OrderCreateRequestDTO(
            symbol=symbol,
            order_type="sell",
            price_type="limit",
            price=price,
            quantity=target_position.quantity,
            account_no=strategy.account_no,
        )

        order_result = await order_service.create_order(self.session, order_request)

        # 시그널 업데이트
        await self.signal_repo.update_execution(
            signal_model.id,
            status=SignalStatus.EXECUTED,
            executed_price=price,
            executed_quantity=target_position.quantity,
            order_no=getattr(order_result, "order_no", None),
            realized_pnl=realized_pnl,
            realized_pnl_ratio=realized_pnl_ratio,
        )

        logger.info(
            f"[GC Engine] SELL {symbol} x {target_position.quantity} @ {price} "
            f"(PnL: {realized_pnl_ratio:.2%})"
        )

    async def _update_state_after_signal(
        self,
        strategy_id: int,
        symbol: str,
        transition,
        current_snapshot: IndicatorSnapshot,
    ):
        """시그널 후 상태 업데이트"""
        if transition.signal == Signal.BUY:
            await self.symbol_state_repo.update_state(
                strategy_id=strategy_id,
                symbol=symbol,
                new_state=transition.new_state,
                entry_date=current_snapshot.timestamp,
                entry_price=current_snapshot.close,
            )
        elif transition.signal == Signal.SELL:
            await self.symbol_state_repo.reset_to_waiting(strategy_id, symbol)

    async def _fetch_ohlcv(self, symbol: str, days: int) -> pd.DataFrame | None:
        """OHLCV 데이터 조회"""
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days + 50)).strftime("%Y%m%d")

            chart_data = await self.market_data_service.get_chart_data(
                symbol=symbol,
                period="D",
                start_date=start_date,
                end_date=end_date,
            )

            if not chart_data.candles:
                return None

            # DataFrame 변환
            records = []
            for candle in chart_data.candles:
                records.append({
                    "timestamp": candle.timestamp,
                    "open": float(candle.open),
                    "high": float(candle.high),
                    "low": float(candle.low),
                    "close": float(candle.close),
                    "volume": candle.volume,
                })

            df = pd.DataFrame(records)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.sort_values("timestamp").reset_index(drop=True)

            return df

        except Exception as e:
            logger.error(f"[GC Engine] Failed to fetch OHLCV for {symbol}: {e}")
            return None

    def _create_snapshot(self, row: pd.Series) -> IndicatorSnapshot:
        """데이터프레임 행을 IndicatorSnapshot으로 변환"""
        return IndicatorSnapshot(
            timestamp=row["timestamp"].to_pydatetime() if hasattr(row["timestamp"], "to_pydatetime") else row["timestamp"],
            close=Decimal(str(row["close"])),
            ma_short=Decimal(str(row["ma_short"])) if pd.notna(row["ma_short"]) else Decimal("0"),
            ma_long=Decimal(str(row["ma_long"])) if pd.notna(row["ma_long"]) else Decimal("0"),
            stoch_k=float(row["stoch_k"]) if pd.notna(row["stoch_k"]) else 50.0,
            stoch_d=float(row["stoch_d"]) if pd.notna(row["stoch_d"]) else 50.0,
        )

    def _parse_config(self, strategy: StrategyModel) -> GoldenCrossConfigDTO:
        """전략 설정 파싱"""
        try:
            config_dict = json.loads(strategy.config_json)
            return GoldenCrossConfigDTO(**config_dict)
        except Exception:
            return GoldenCrossConfigDTO()

    async def _init_safety_guard(self, strategy: StrategyModel) -> SafetyGuard:
        """SafetyGuard 초기화"""
        try:
            balance = await self.account_service.get_balance(strategy.account_no)
            initial_capital = Decimal(str(balance.total_cash + balance.total_stock_value))
        except Exception:
            initial_capital = Decimal("10_000_000")

        return SafetyGuard(initial_capital=initial_capital)

    def _model_to_dto(self, model) -> StrategySignalDTO:
        """모델을 DTO로 변환"""
        return StrategySignalDTO(
            id=model.id,
            strategy_id=model.strategy_id,
            symbol=model.symbol,
            signal_type=model.signal_type,
            signal_status=model.signal_status,
            signal_price=model.signal_price,
            target_quantity=model.target_quantity,
            executed_price=model.executed_price,
            executed_quantity=model.executed_quantity,
            exit_reason=model.exit_reason,
            realized_pnl=model.realized_pnl,
            realized_pnl_ratio=model.realized_pnl_ratio,
            ma_short=model.ma_short,
            ma_long=model.ma_long,
            stoch_k=model.stoch_k,
            stoch_d=model.stoch_d,
            prev_state=model.prev_state,
            new_state=model.new_state,
            note=model.note,
            signal_at=model.signal_at,
            executed_at=model.executed_at,
            created_at=model.created_at,
        )

    def _create_result(
        self,
        strategy_id: int,
        executed_at: datetime,
        dry_run: bool,
        symbols_checked: int,
        buy_signals: int,
        sell_signals: int,
        orders_created: int,
        signals: list[StrategySignalDTO],
        errors: list[str],
    ) -> StrategyExecuteResultDTO:
        """실행 결과 DTO 생성"""
        return StrategyExecuteResultDTO(
            strategy_id=strategy_id,
            executed_at=executed_at,
            dry_run=dry_run,
            symbols_checked=symbols_checked,
            buy_signals=buy_signals,
            sell_signals=sell_signals,
            orders_created=orders_created,
            signals=signals,
            errors=errors,
        )
