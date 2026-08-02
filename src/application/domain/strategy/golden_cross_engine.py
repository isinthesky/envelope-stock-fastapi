# -*- coding: utf-8 -*-
"""
Golden Cross Engine - 골든크로스 전략 실행 엔진

장 마감 후 1회 실행 (15:35)
1. 종목 스크리닝
2. OHLCV 데이터 조회 (250일)
3. 지표 계산 (configurable short/long MA, Stochastic)
4. 상태 머신 업데이트 & 시그널 생성
5. SafetyGuard 검증
6. 주문 생성
"""

import json
import logging
from types import SimpleNamespace
from datetime import datetime
from decimal import Decimal

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
from src.adapters.cache.redis_client import get_redis_client
from src.adapters.external.kis_api.client import KISAPIClient, get_kis_client
from src.application.common.indicators import TechnicalIndicators
from src.application.domain.account.service import AccountService
from src.application.domain.risk.safety_guard import SafetyGuard
from src.application.domain.order.dto import OrderCreateRequestDTO
from src.application.domain.order.service import OrderService
from src.application.domain.strategy.dto import (
    GoldenCrossConfigDTO,
    StrategyExecuteResultDTO,
    StrategySignalDTO,
)
from src.application.domain.strategy.ohlcv_data_loader import OHLCVDataLoader
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
        redis_client=None,
    ):
        """
        Args:
            session: DB 세션
            kis_client: KIS API 클라이언트
            redis_client: Redis 클라이언트
        """
        self.session = session
        self.kis_client = kis_client or get_kis_client()
        self.redis_client = redis_client
        self.indicators = TechnicalIndicators()

        # Repositories
        self.strategy_repo = StrategyRepository(session)
        self.symbol_state_repo = StrategySymbolStateRepository(session)
        self.signal_repo = StrategySignalRepository(session)

        # Services (redis_client가 없으면 lazy init)
        self._account_service = None
        self._data_loader: OHLCVDataLoader | None = None

    def _get_data_loader(self) -> OHLCVDataLoader:
        """청크·캐시 지원 OHLCV 로더(스캐너/매도와 동일 경로)."""
        if self._data_loader is None:
            self._data_loader = OHLCVDataLoader(self.session)
        return self._data_loader

    async def _safe_rollback(self) -> None:
        """rollback 자체 실패가 상위로 전파되지 않도록 방어한다.

        주문 접수 후 마킹/커밋 실패의 except 경로에서 rollback이 다시 raise하면
        예외가 _execute_*를 탈출해 FAILED로 오기록될 수 있으므로(이중주문 위험),
        여기서 삼켜 로깅만 한다.
        """
        try:
            await self.session.rollback()
        except Exception as e:
            logger.error(f"[GC Engine] session.rollback() failed (무시): {e}")

    async def _get_account_service(self) -> AccountService:
        if self._account_service is None:
            if self.redis_client is None:
                self.redis_client = await get_redis_client()
            self._account_service = AccountService(self.kis_client, self.redis_client)
        return self._account_service

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

            logger.info(
                f"[GC Engine] Processing {len(all_symbols)} symbols for strategy {strategy_id}"
            )

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

            if not dry_run:
                # 7. 전략 실행 통계 업데이트
                await self.strategy_repo.update_execution_stats(
                    strategy_id, success=len(errors) == 0
                )
                await self.session.commit()

        except Exception as e:
            error_msg = f"Strategy execution failed: {str(e)}"
            logger.exception(f"[GC Engine] {error_msg}")
            errors.append(error_msg)
            await self._safe_rollback()

        return self._create_result(
            strategy_id,
            executed_at,
            dry_run,
            len(all_symbols) if "all_symbols" in locals() else 0,
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
        # 장기 MA(long_period+10) 캔들을 확보하도록 조회 창을 산출(스캐너와 동일 공식).
        # config.lookback_days(달력일)만으로는 거래일 환산 시 부족할 수 있음(예: MA200 → 210 거래일).
        fetch_days = max(
            config.lookback_days, int((config.ma_config.long_period + 20) * 1.6)
        )
        min_candles = config.ma_config.long_period + 10
        df = await self._fetch_ohlcv(symbol, fetch_days, min_candles=min_candles)
        if df is None or len(df) < min_candles:
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
        state = await self.symbol_state_repo.get_by_strategy_and_symbol(strategy.id, symbol)

        if not state:
            # 초기 상태 결정
            initial_state = state_machine.get_initial_state(current_snapshot)
            if dry_run:
                state = SimpleNamespace(
                    state=initial_state.value,
                    gc_date=None,
                    pullback_date=None,
                    entry_price=None,
                    entry_date=None,
                    highest_price=None,
                    trailing_stop_activated=False,
                )
            else:
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
            highest_price=state.highest_price,
            trailing_stop_activated=state.trailing_stop_activated,
        )

        if not dry_run:
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

        # 6-1. 포지션 보유 중이면 highest_price 업데이트
        if not dry_run and state.state == SymbolState.IN_POSITION.value:
            current_highest = state.highest_price or Decimal("0")
            if current_snapshot.close > current_highest:
                await self.symbol_state_repo.update_highest_price(
                    strategy_id=strategy.id,
                    symbol=symbol,
                    highest_price=current_snapshot.close,
                )

            # 트레일링 스탑 활성화 체크
            if state.entry_price and state.entry_price > 0:
                pnl_ratio = float((current_snapshot.close - state.entry_price) / state.entry_price)
                activation_threshold = config.risk_config.trailing_stop_activation
                if pnl_ratio >= activation_threshold and not state.trailing_stop_activated:
                    await self.symbol_state_repo.activate_trailing_stop(
                        strategy_id=strategy.id,
                        symbol=symbol,
                    )

        # 7. 시그널 처리
        if transition.signal == Signal.HOLD:
            # 상태만 업데이트
            if not dry_run and state.state != transition.new_state.value:
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
        signal_type = SignalType.BUY if transition.signal == Signal.BUY else SignalType.SELL

        if dry_run:
            logger.info(
                f"[GC Engine DRY RUN] {symbol} {signal_type.value.upper()} @ {current_snapshot.close}"
            )
            return self._create_dry_run_signal_dto(
                strategy_id=strategy.id,
                symbol=symbol,
                signal_type=signal_type,
                transition=transition,
                current_snapshot=current_snapshot,
                prev_state=state.state,
            )

        # 중복 주문 가드: 직전 실행에서 동일 전이가 이미 EXECUTED로 기록됐다면
        # (symbol_state 동기화 실패로 상태가 stale한 채 재평가된 경우) 새 시그널/주문을
        # 만들지 않고 SKIPPED DTO만 반환해 이중 주문을 방지한다.
        duplicate = await self._find_duplicate_executed_signal(
            strategy_id=strategy.id,
            symbol=symbol,
            signal_type=signal_type,
            prev_state=state.state,
            new_state=transition.new_state.value,
        )
        if duplicate is not None:
            logger.warning(
                f"[GC Engine] Duplicate-submit guard: {symbol} {signal_type.value} "
                f"{state.state}->{transition.new_state.value} already EXECUTED as "
                f"signal_id={duplicate.id}; skipping order (state sync likely failed previously)"
            )
            # stale symbol_state 복구(best-effort): 이미 체결된 전이를 상태에 반영해
            # 다음 실행에서 무한 skip/잘못된 라이프사이클 진행을 방지한다. 여기서 또
            # 실패해도 주문은 나가지 않으므로(가드가 상단에서 차단) 안전하다.
            try:
                await self._update_state_after_signal(
                    strategy.id, symbol, transition, current_snapshot
                )
            except Exception as e:
                logger.error(
                    f"[GC Engine] Duplicate-guard state repair failed for {symbol} "
                    f"(signal_id={duplicate.id}): {e}"
                )
            return self._create_dry_run_signal_dto(
                strategy_id=strategy.id,
                symbol=symbol,
                signal_type=signal_type,
                transition=transition,
                current_snapshot=current_snapshot,
                prev_state=state.state,
                note=f"duplicate-guard: original signal_id={duplicate.id} already EXECUTED",
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
                logger.info(
                    f"[GC Engine] {symbol} state reset to WAITING_FOR_GC after SafetyGuard block"
                )
            return self._model_to_dto(signal_model)

        # 실제 주문 실행 (주문 미체결 시에만 FAILED로 마킹)
        try:
            if signal_type == SignalType.BUY:
                await self._execute_buy(
                    strategy, symbol, current_snapshot.close, config, signal_model
                )
            else:
                await self._execute_sell(
                    strategy, symbol, current_snapshot.close, state, signal_model
                )
        except Exception as e:
            logger.error(f"[GC Engine] Order execution failed: {e}")
            await self.signal_repo.update_execution(
                signal_model.id,
                status=SignalStatus.FAILED,
            )
            updated_signal = await self.signal_repo.get_by_id(signal_model.id)
            return self._model_to_dto(updated_signal)

        # 주문은 이미 체결됨(_execute_*가 EXECUTED로 마킹). 이후 상태 동기화 실패는
        # 시그널 상태를 되돌리지 않고(이중 주문 방지) 별도로 로깅만 한다.
        try:
            await self._update_state_after_signal(strategy.id, symbol, transition, current_snapshot)
        except Exception as e:
            logger.error(
                f"[GC Engine] State sync after executed order failed for {symbol} "
                f"(signal_id={signal_model.id}, 주문 체결됨·시그널 EXECUTED 유지): {e}"
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
        account_service = await self._get_account_service()
        balance = await account_service.get_account_balance(strategy.account_no)

        # 포지션 사이즈 계산
        allocation = float(balance.cash_balance) * config.position.allocation_ratio
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
        order_no = getattr(order_result, "order_no", None)

        # 주문은 이미 브로커에 접수됨(order placed). 이후 durable 마킹이 실패해도
        # 예외를 전파해 FAILED로 오기록하면 안 된다(가드가 EXECUTED만 보면 이중주문).
        # 1단계: order_no를 우선 durable 커밋 — proof-of-placement 확보(상태는 PENDING 유지).
        try:
            await self.signal_repo.update_execution(
                signal_model.id, status=SignalStatus.PENDING, order_no=order_no
            )
            await self.session.commit()
        except Exception as e:
            await self._safe_rollback()
            logger.critical(
                f"[GC Engine] ORDER PLACED BUT order_no NOT DURABLY RECORDED — 수동 대사 필요: "
                f"symbol={symbol} signal_id={signal_model.id} order_no={order_no}: {e}"
            )
            logger.info(f"[GC Engine] BUY {symbol} x {quantity} @ {price}")
            return

        # 2단계: 체결 상세 반영(EXECUTED). 실패해도 order_no가 durable하므로 가드가 재주문 차단.
        try:
            await self.signal_repo.update_execution(
                signal_model.id,
                status=SignalStatus.EXECUTED,
                executed_price=price,
                executed_quantity=quantity,
                order_no=order_no,
            )
            await self.session.commit()
        except Exception as e:
            await self._safe_rollback()
            logger.critical(
                f"[GC Engine] ORDER PLACED (order_no={order_no}) BUT SIGNAL NOT MARKED EXECUTED "
                f"— 수동 대사 필요: symbol={symbol} signal_id={signal_model.id}: {e}"
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
        account_service = await self._get_account_service()
        positions = await account_service.get_position_list(strategy.account_no)
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
        order_no = getattr(order_result, "order_no", None)

        # 주문 접수 후 durable 마킹(2단계). 실패해도 예외를 전파하지 않는다(이중주문 방지).
        # 1단계: order_no 우선 durable 커밋(상태 PENDING 유지).
        try:
            await self.signal_repo.update_execution(
                signal_model.id, status=SignalStatus.PENDING, order_no=order_no
            )
            await self.session.commit()
        except Exception as e:
            await self._safe_rollback()
            logger.critical(
                f"[GC Engine] SELL ORDER PLACED BUT order_no NOT DURABLY RECORDED — 수동 대사 필요: "
                f"symbol={symbol} signal_id={signal_model.id} order_no={order_no}: {e}"
            )
            return

        # 2단계: 체결 상세 반영(EXECUTED + 실현손익).
        try:
            await self.signal_repo.update_execution(
                signal_model.id,
                status=SignalStatus.EXECUTED,
                executed_price=price,
                executed_quantity=target_position.quantity,
                order_no=order_no,
                realized_pnl=realized_pnl,
                realized_pnl_ratio=realized_pnl_ratio,
            )
            await self.session.commit()
        except Exception as e:
            await self._safe_rollback()
            logger.critical(
                f"[GC Engine] SELL ORDER PLACED (order_no={order_no}) BUT SIGNAL NOT MARKED EXECUTED "
                f"— 수동 대사 필요: symbol={symbol} signal_id={signal_model.id}: {e}"
            )

        pnl_text = f"{realized_pnl_ratio:.2%}" if realized_pnl_ratio is not None else "n/a"
        logger.info(
            f"[GC Engine] SELL {symbol} x {target_position.quantity} @ {price} "
            f"(PnL: {pnl_text})"
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

    async def _fetch_ohlcv(
        self, symbol: str, days: int, min_candles: int = 1
    ) -> pd.DataFrame | None:
        """OHLCV 데이터 조회.

        스캐너/매도와 동일한 청크·캐시 지원 로더(OHLCVDataLoader)를 사용한다.
        KIS 일봉 API는 1콜당 최대 100행이므로, 단일 호출 경로로는 장기 MA(예: MA200→210캔들)
        데이터를 확보할 수 없다. 로더는 max_days 청크로 분할 조회한다.
        """
        data_loader = self._get_data_loader()
        try:
            df = await data_loader.load_ohlcv_dataframe(
                symbol=symbol,
                days=days,
                interval="1d",
                min_candles=min_candles,
            )
        except ValueError as e:
            # 데이터 부족 등 예상된 실패만 스킵(None). 그 외 예외(네트워크/스키마 등)는
            # 은폐하지 않고 상위 per-symbol 핸들러로 전파해 실제 오류로 관측되게 한다.
            logger.warning(f"[GC Engine] Insufficient/invalid OHLCV for {symbol}: {e}")
            return None

        if df is None or df.empty:
            return None
        return df.sort_values("timestamp").reset_index(drop=True)

    def _create_snapshot(self, row: pd.Series) -> IndicatorSnapshot:
        """데이터프레임 행을 IndicatorSnapshot으로 변환"""
        return IndicatorSnapshot(
            timestamp=(
                row["timestamp"].to_pydatetime()
                if hasattr(row["timestamp"], "to_pydatetime")
                else row["timestamp"]
            ),
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
            account_service = await self._get_account_service()
            balance = await account_service.get_account_balance(strategy.account_no)
            initial_capital = Decimal(str(balance.cash_balance + balance.stock_balance))
        except Exception:
            initial_capital = Decimal("10_000_000")

        return SafetyGuard(initial_capital=initial_capital)

    def _create_dry_run_signal_dto(
        self,
        strategy_id: int,
        symbol: str,
        signal_type: SignalType,
        transition,
        current_snapshot: IndicatorSnapshot,
        prev_state: str,
        note: str | None = None,
    ) -> StrategySignalDTO:
        """Dry-run/스킵 시그널을 DB 저장 없이 DTO로 생성(note로 사유 지정 가능)"""
        now = datetime.now()
        return StrategySignalDTO(
            id=0,
            strategy_id=strategy_id,
            symbol=symbol,
            signal_type=signal_type.value,
            signal_status=SignalStatus.SKIPPED.value,
            signal_price=current_snapshot.close,
            target_quantity=None,
            executed_price=None,
            executed_quantity=None,
            exit_reason=None,
            realized_pnl=None,
            realized_pnl_ratio=None,
            ma_short=current_snapshot.ma_short,
            ma_long=current_snapshot.ma_long,
            stoch_k=Decimal(str(current_snapshot.stoch_k)),
            stoch_d=Decimal(str(current_snapshot.stoch_d)),
            prev_state=prev_state,
            new_state=transition.new_state.value,
            note=note if note is not None else transition.reason,
            signal_at=now,
            executed_at=None,
            created_at=now,
        )

    async def _find_duplicate_executed_signal(
        self,
        strategy_id: int,
        symbol: str,
        signal_type: SignalType,
        prev_state: str,
        new_state: str,
    ):
        """직전(가장 최근) 시그널이 이번에 도출된 것과 동일 전이
        (signal_type, prev_state, new_state)로 이미 EXECUTED인지 확인한다.

        symbol_state 동기화 실패로 상태가 stale하면 상태머신이 다음 실행에서 동일
        전이를 재도출하므로, 기간 제한 없이 '가장 최근 시그널'만 비교해도 정확히
        중복(재주문)을 잡아낸다. 정상적인 BUY→SELL→BUY 사이클은 signal_type이나
        prev/new_state가 달라지므로 절대 차단되지 않는다.
        """
        recent = await self.signal_repo.get_by_symbol(strategy_id, symbol, limit=1)
        if not recent:
            return None
        latest = recent[0]
        same_transition = (
            latest.signal_type == signal_type.value
            and latest.prev_state == prev_state
            and latest.new_state == new_state
        )
        if not same_transition:
            return None

        # EXECUTED면 명백한 중복.
        if latest.signal_status == SignalStatus.EXECUTED.value:
            return latest

        # status가 EXECUTED로 못 넘어갔어도(2단계 마킹 실패) order_no가 있으면 주문은 이미
        # 브로커에 접수된 것이 durable하게 증명된다 → 재주문 차단. order_no가 없으면(진짜
        # 미주문) 정상 재시도를 허용한다.
        if getattr(latest, "order_no", None):
            logger.critical(
                f"[GC Engine] {symbol} signal_id={latest.id} order_no={latest.order_no} but "
                f"status={latest.signal_status}(≠EXECUTED) — 주문 접수됨·마킹 실패 → 재주문 차단, 수동 대사 필요"
            )
            return latest
        return None

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
