# -*- coding: utf-8 -*-
"""
Golden Cross Engine - 골든크로스 전략 실행 엔진

장 마감 후 1회 실행 (15:35)
0. 직전 주문 체결 대사(reconcile)
1. 종목 스크리닝
2. OHLCV 데이터 조회 (250일)
3. 지표 계산 (configurable short/long MA, Stochastic)
4. 상태 머신 업데이트 & 시그널 생성
5. 시장 국면 게이트(신규 매수만, fail-closed) + SafetyGuard 검증
6. 주문 접수 — 기본 장후 시간외 종가(ORD_DVSN 06). 시그널은 PENDING(order_no)으로 남고
   체결 확인은 16:10 reconcile job(`reconcile_open_orders`)이 실제 체결가/수량으로 확정한다.
"""

import json
import logging
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.cache.redis_client import get_redis_client
from src.adapters.database.models.strategy import StrategyModel
from src.adapters.database.models.stock_universe import MarketType
from src.adapters.database.models.strategy_signal import SignalStatus, SignalType
from src.adapters.database.models.strategy_symbol_state import SymbolState
from src.adapters.database.repositories.strategy_repository import StrategyRepository
from src.adapters.database.repositories.strategy_signal_repository import (
    StrategySignalRepository,
)
from src.adapters.database.repositories.strategy_symbol_state_repository import (
    StrategySymbolStateRepository,
)
from src.adapters.external.kis_api.client import KISAPIClient, get_kis_client
from src.application.common.indicators import TechnicalIndicators
from src.application.domain.account.service import AccountService
from src.application.domain.order.dto import OrderCreateRequestDTO
from src.application.domain.order.service import OrderService
from src.application.domain.risk.safety_guard import SafetyGuard
from src.application.domain.strategy.dto import (
    GoldenCrossConfigDTO,
    StrategyExecuteResultDTO,
    StrategySignalDTO,
)
from src.application.domain.backtest.cost_schedule import get_latest_backtest_cost_schedule
from src.application.domain.order.order_id import split_order_id
from src.application.domain.strategy.market_regime import market_regime_ok
from src.application.domain.strategy.ohlcv_data_loader import (
    OHLCVDataLoader,
    get_regime_benchmark_ohlc,
)
from src.application.domain.strategy.state_machine import (
    GoldenCrossStateMachine,
    IndicatorSnapshot,
    Signal,
)
from src.application.domain.strategy.stock_screener import StockScreener
from src.settings.config import settings

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

        if not dry_run and not settings.strategy_live_trading_enabled:
            errors.append("Live trading is disabled by STRATEGY_LIVE_TRADING_ENABLED kill-switch")
            logger.warning("[GC Engine] Live trading blocked by master kill-switch")
            return self._create_result(
                strategy_id, executed_at, dry_run, 0, 0, 0, 0, signals, errors
            )

        try:
            # 1. 전략 조회
            strategy = await self.strategy_repo.get_by_id(strategy_id)
            if not strategy:
                errors.append(f"Strategy {strategy_id} not found")
                return self._create_result(
                    strategy_id, executed_at, dry_run, 0, 0, 0, 0, signals, errors
                )

            # 0. 직전 실행 주문 체결 대사 (실주문 모드만)
            if not dry_run:
                await self.reconcile_open_orders(strategy_id)

            # 2. 전략 설정 파싱
            config = self._parse_config(strategy)
            _warn_if_ma_drift(strategy_id, config)

            # 2-1. 벤치 당일 봉 확보(로더가 API로 받아 캐시) → 급락 가드 입력 + 레짐 판정에 당일 봉 반영
            market_change = await self._benchmark_change_today()

            # 2-2. 시장 국면 게이트(신규 매수 전용, 실행당 1회). 실주문은 fail-closed.
            entry_regime_allowed = await self._evaluate_entry_regime(fail_open=dry_run)

            # 3. 상태 머신 초기화
            state_machine = GoldenCrossStateMachine(config)

            # 4. SafetyGuard 초기화 + 당일 시장 변화(급락 가드) + 보유 종목 수(최대 포지션)
            safety_guard = await self._init_safety_guard(strategy)
            safety_guard.update_market_change(market_change)
            held = await self.symbol_state_repo.get_in_position(strategy.id)
            self._run_state = {
                "held": len(held),
                "max_positions": config.position.max_position_count,
            }

            # 5. 종목 스크리닝
            screener = StockScreener(self.session, self.kis_client, config.screener_config)
            # ETF 모드: 개별주 스크리닝(시총·거래량)은 ETF에 시총이 없어 221종 중 2종만 통과시켰다.
            # 백테스트·walk-forward 유니버스(활성 ETF 전체)와 맞춰 ETF 조건(활성·거래가능·비제외)만 쓴다.
            candidates = await screener.get_screening_candidates(
                market=MarketType.ETF if settings.etf_universe_enabled else None
            )

            # 기존 전략 종목도 포함. 처리 순서는 백테스트(Phase B 청산 → Phase D 진입)와 맞춘다:
            # 보유 종목 먼저, 나머지는 종목코드 순(일 진입 상한·최대 포지션이 순서에 의존).
            existing_symbols = set(strategy.symbol_list)
            held_symbols = {h.symbol for h in held}
            all_symbols = sorted(
                set(candidates) | existing_symbols | held_symbols,
                key=lambda sym: (sym not in held_symbols, sym),
            )

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
                        entry_regime_allowed=entry_regime_allowed,
                    )

                    if result:
                        signals.append(result)
                        # 주문 접수 = order_no가 있는 PENDING(체결 대기) 또는 EXECUTED
                        placed = (
                            not dry_run
                            and bool(result.order_no)
                            and (
                                result.signal_status
                                in (SignalStatus.PENDING.value, SignalStatus.EXECUTED.value)
                            )
                        )
                        if result.signal_type == SignalType.BUY.value:
                            buy_count += 1
                        elif result.signal_type == SignalType.SELL.value:
                            sell_count += 1
                        if placed:
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
        entry_regime_allowed: bool = True,
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
        # 1. 현재 상태를 먼저 조회한다. 보유 상태는 지표 데이터가 부족해도
        # 가격 기반 하드스톱을 평가해야 한다.
        state = await self.symbol_state_repo.get_by_strategy_and_symbol(strategy.id, symbol)

        # 2. OHLCV 데이터 조회
        # 장기 MA(long_period+10) 캔들을 확보하도록 조회 창을 산출(스캐너와 동일 공식).
        # config.lookback_days(달력일)만으로는 거래일 환산 시 부족할 수 있음(예: MA200 → 210 거래일).
        fetch_days = max(config.lookback_days, int((config.ma_config.long_period + 20) * 1.6))
        min_candles = config.ma_config.long_period + 10
        df = await self._fetch_ohlcv(symbol, fetch_days, min_candles=min_candles)
        if df is None or len(df) < min_candles:
            logger.warning(f"[GC Engine] Insufficient data for {symbol}")
            if state and state.state == SymbolState.IN_POSITION.value:
                return await self._process_price_only_position(
                    strategy=strategy,
                    symbol=symbol,
                    state=state,
                    config=config,
                    state_machine=state_machine,
                    safety_guard=safety_guard,
                    dry_run=dry_run,
                )
            return None

        # 3. 지표 계산
        df = TechnicalIndicators.prepare_golden_cross_indicators(
            df,
            short_ma_period=config.ma_config.short_period,
            long_ma_period=config.ma_config.long_period,
            stoch_k_period=config.stochastic_config.k_period,
            stoch_d_period=config.stochastic_config.d_period,
        )

        # 4. 현재/이전 지표 스냅샷
        if len(df) < 2:
            return None

        current_row = df.iloc[-1]
        prev_row = df.iloc[-2]

        current_snapshot = self._create_snapshot(current_row)
        prev_snapshot = self._create_snapshot(prev_row)

        # 5. 상태가 없으면 생성
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

        # 6. 상태 머신 처리
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
            entry_regime_allowed=entry_regime_allowed,
        )

    async def _process_price_only_position(
        self,
        *,
        strategy: StrategyModel,
        symbol: str,
        state,
        config: GoldenCrossConfigDTO,
        state_machine: GoldenCrossStateMachine,
        safety_guard: SafetyGuard,
        dry_run: bool,
    ) -> StrategySignalDTO | None:
        """지표 부족 시 보유 포지션의 가격 손절만 안전하게 평가한다."""
        price_df = await self._fetch_ohlcv(symbol, days=10, min_candles=1)
        if price_df is None or price_df.empty:
            logger.error(
                f"[GC Engine] No current price for in-position symbol {symbol}; "
                "price stop cannot be evaluated"
            )
            return None

        row = price_df.iloc[-1]
        timestamp = (
            row["timestamp"].to_pydatetime()
            if hasattr(row["timestamp"], "to_pydatetime")
            else row["timestamp"]
        )
        current_price = Decimal(str(row["close"]))
        transition = state_machine.process_price_stop(
            current_price=current_price,
            entry_price=state.entry_price,
            highest_price=state.highest_price,
        )

        if transition is None:
            current_highest = max(
                value
                for value in (state.entry_price, state.highest_price, current_price)
                if value is not None
            )
            if not dry_run and current_highest != state.highest_price:
                await self.symbol_state_repo.update_highest_price(
                    strategy_id=strategy.id,
                    symbol=symbol,
                    highest_price=current_highest,
                )
            return None

        price_snapshot = IndicatorSnapshot(
            timestamp=timestamp,
            close=current_price,
            ma_short=Decimal("0"),
            ma_long=Decimal("0"),
            stoch_k=0.0,
            stoch_d=0.0,
        )
        logger.warning(f"[GC Engine] Price-only stop triggered for {symbol} @ {current_price}")
        return await self._handle_signal(
            strategy=strategy,
            symbol=symbol,
            transition=transition,
            current_snapshot=price_snapshot,
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
        entry_regime_allowed: bool = True,
    ) -> StrategySignalDTO | None:
        """
        시그널 처리 (매수/매도)
        """
        signal_type = SignalType.BUY if transition.signal == Signal.BUY else SignalType.SELL
        regime_blocked = signal_type == SignalType.BUY and not entry_regime_allowed

        if dry_run:
            logger.info(
                f"[GC Engine DRY RUN] {symbol} {signal_type.value.upper()} @ {current_snapshot.close}"
                + (" (regime_block)" if regime_blocked else "")
            )
            return self._create_dry_run_signal_dto(
                strategy_id=strategy.id,
                symbol=symbol,
                signal_type=signal_type,
                transition=transition,
                current_snapshot=current_snapshot,
                prev_state=state.state,
                note="regime_block: 시장 국면 게이트로 신규 매수 차단" if regime_blocked else None,
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

        # 시장 국면 게이트: 신규 매수만 차단(백테스트 regime_block과 동일하게 WAITING으로 리셋)
        if regime_blocked:
            logger.info(f"[GC Engine] {symbol} BUY blocked by market regime gate")
            await self.signal_repo.update_execution(
                signal_model.id,
                status=SignalStatus.SKIPPED,
                exit_reason="regime_block",
            )
            await self.symbol_state_repo.reset_to_waiting(strategy.id, symbol)
            return self._model_to_dto(signal_model)

        # 최대 보유 종목 수(전략 config, 백테스트 max_positions와 동일 — 이전엔 라이브 미적용)
        run_state = getattr(self, "_run_state", None)
        if (
            signal_type == SignalType.BUY
            and run_state is not None
            and run_state["held"] >= run_state["max_positions"]
        ):
            logger.info(
                f"[GC Engine] {symbol} BUY blocked: max positions "
                f"{run_state['held']}/{run_state['max_positions']}"
            )
            await self.signal_repo.update_execution(
                signal_model.id, status=SignalStatus.SKIPPED, exit_reason="max_positions"
            )
            await self.symbol_state_repo.reset_to_waiting(strategy.id, symbol)
            return self._model_to_dto(signal_model)

        # SafetyGuard 체크
        can_trade, _, block_message = safety_guard.can_trade(
            is_risk_reducing=signal_type == SignalType.SELL
        )
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
                safety_guard.record_entry(symbol)
                if run_state is not None:
                    run_state["held"] += 1
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

        # 주문은 브로커에 접수됨(_execute_*가 order_no와 함께 PENDING으로 durable 마킹).
        # 상태는 체결을 가정해 전이하고(시간외 종가 = 신호봉 종가), 미체결이면 reconcile이 되돌린다.
        # 이후 상태 동기화 실패는 시그널 상태를 되돌리지 않고(이중 주문 방지) 별도로 로깅만 한다.
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
        """매수 주문 접수 (체결 확정은 reconcile_open_orders)"""
        account_service = await self._get_account_service()
        balance = await account_service.get_account_balance(strategy.account_no, use_cache=False)

        # 포지션 사이즈: 주문가능현금 × allocation_ratio (백테스트 order_manager와 같은 모델)
        allocation = float(balance.available_amount) * config.position.allocation_ratio
        quantity = int(allocation / float(price))

        if quantity <= 0:
            raise ValueError("Insufficient cash for buy order")

        await self._place_order(strategy, symbol, "buy", price, quantity, signal_model, metadata={})
        logger.info(f"[GC Engine] BUY {symbol} x {quantity} submitted (signal close {price})")

    async def _execute_sell(
        self,
        strategy: StrategyModel,
        symbol: str,
        price: Decimal,
        state,
        signal_model,
    ):
        """매도 주문 접수 (체결 확정·실현손익은 reconcile_open_orders)"""
        account_service = await self._get_account_service()
        positions = await account_service.get_position_list(strategy.account_no)
        target_position = next(
            (pos for pos in positions.positions if pos.symbol == symbol and pos.quantity > 0),
            None,
        )
        if target_position is None:
            raise ValueError("No position to sell")

        quantity = target_position.available_quantity or target_position.quantity
        # 상태는 접수 직후 WAITING으로 리셋되므로 실현손익 계산용 진입가를 시그널에 보존한다.
        entry_price = state.entry_price or target_position.avg_purchase_price
        await self._place_order(
            strategy,
            symbol,
            "sell",
            price,
            quantity,
            signal_model,
            metadata={"entry_price": str(entry_price)},
        )
        logger.info(f"[GC Engine] SELL {symbol} x {quantity} submitted (signal close {price})")

    async def _place_order(
        self,
        strategy: StrategyModel,
        symbol: str,
        side: str,
        price: Decimal,
        quantity: int,
        signal_model,
        metadata: dict,
    ) -> None:
        """주문 접수 후 order_no를 durable 커밋한다(시그널은 PENDING = 체결 대기).

        이전 구현은 접수 직후 신호가로 EXECUTED를 기록했다(체결 확인 없음). 이제 EXECUTED와
        실제 체결가/수량/실현손익은 reconcile_open_orders가 KIS 체결조회로 확정한다.
        """
        price_type = settings.strategy_order_price_type
        order_service = OrderService(self.kis_client, self.session)
        order_request = OrderCreateRequestDTO(
            symbol=symbol,
            order_type=side,
            price_type=price_type,
            price=price if price_type == "limit" else Decimal("0"),
            quantity=quantity,
            account_no=strategy.account_no,
        )

        order_result = await order_service.create_order(self.session, order_request)
        order_no = getattr(order_result, "order_no", None)

        # 주문은 이미 브로커에 접수됨. 이후 durable 마킹이 실패해도 예외를 전파해 FAILED로
        # 오기록하면 안 된다(가드가 order_no를 못 보면 이중주문).
        try:
            await self.signal_repo.update_execution(
                signal_model.id,
                status=SignalStatus.PENDING,
                order_no=order_no,
                target_quantity=quantity,
                metadata={**metadata, "broker_order_id": getattr(order_result, "order_id", None)},
            )
            await self.session.commit()
        except Exception as e:
            await self._safe_rollback()
            logger.critical(
                f"[GC Engine] {side.upper()} ORDER PLACED BUT order_no NOT DURABLY RECORDED — "
                f"수동 대사 필요: symbol={symbol} signal_id={signal_model.id} order_no={order_no}: {e}"
            )

    # ==================== 체결 대사 ====================

    async def reconcile_open_orders(self, strategy_id: int) -> dict[str, int]:
        """체결 대기(PENDING + order_no) 시그널을 KIS 체결조회로 확정한다.

        - 체결 수량 > 0: EXECUTED + 실제 평균체결가/수량. 매수는 진입가를 체결가로 보정,
          매도는 수수료·매도세를 뺀 실현손익을 기록한다. 매도 일부 체결이면 잔량을 위해
          IN_POSITION을 복원한다.
        - 체결 0 + 주문 세션 종료(주문일 다음 날 이후, 또는 당일 16:00 KST 이후): CANCELLED.
          매수는 WAITING으로, 매도는 브로커 잔고 기준 IN_POSITION으로 되돌린다.
        - 그 외(세션 진행 중): 그대로 둔다.
        """
        summary = {"executed": 0, "cancelled": 0, "open": 0, "errors": 0}
        pending = await self.signal_repo.get_pending_signals(strategy_id)
        order_service = OrderService(self.kis_client, self.session)
        now_kst = datetime.now(KST)

        for signal in pending:
            if not signal.order_no:
                continue
            try:
                order_id = _signal_meta(signal).get("broker_order_id") or (
                    await self._find_broker_order_id(signal)
                )
                if not order_id:
                    logger.critical(
                        f"[GC Reconcile] signal_id={signal.id} order_no={signal.order_no}: "
                        "주문 레코드를 찾을 수 없음 — 수동 대사 필요"
                    )
                    summary["errors"] += 1
                    continue
                status = await order_service.update_order_status(self.session, order_id)
                filled_qty = int(status.filled_quantity or 0)
                if filled_qty > 0:
                    await self._confirm_fill(
                        strategy_id, signal, Decimal(str(status.filled_avg_price)), filled_qty
                    )
                    summary["executed"] += 1
                elif _order_session_closed(signal.signal_at, now_kst):
                    await self._cancel_unfilled(strategy_id, signal)
                    summary["cancelled"] += 1
                else:
                    summary["open"] += 1
                await self.session.commit()
            except Exception as e:  # noqa: BLE001 - 한 건 실패가 나머지 대사를 막지 않게
                await self._safe_rollback()
                summary["errors"] += 1
                logger.error(f"[GC Reconcile] signal_id={signal.id} reconcile failed: {e}")

        if any(summary.values()):
            logger.info(f"[GC Reconcile] strategy={strategy_id} {summary}")
        return summary

    async def _find_broker_order_id(self, signal) -> str | None:
        """레거시 시그널(broker_order_id 미기록)용: 주문 테이블에서 ODNO로 주문 ID를 찾는다."""
        from src.adapters.database.repositories.order_repository import OrderRepository

        orders = await OrderRepository(self.session).get_by_symbol(signal.symbol)
        for order in orders:
            if split_order_id(order.order_id)[1] == signal.order_no:
                return order.order_id
        return None

    async def _confirm_fill(
        self, strategy_id: int, signal, avg_price: Decimal, filled_qty: int
    ) -> None:
        realized_pnl = None
        realized_pnl_ratio = None
        state = await self.symbol_state_repo.get_by_strategy_and_symbol(strategy_id, signal.symbol)

        if signal.signal_type == SignalType.BUY.value:
            # 상태는 접수 시 신호봉 종가로 IN_POSITION 전이됨 → 실제 체결가로 보정
            if state and state.state == SymbolState.IN_POSITION.value:
                await self.symbol_state_repo.update_state(
                    strategy_id=strategy_id,
                    symbol=signal.symbol,
                    new_state=SymbolState.IN_POSITION,
                    entry_price=avg_price,
                )
        else:
            entry_price = _signal_entry_price(signal)
            if entry_price and entry_price > 0:
                realized_pnl, realized_pnl_ratio = estimate_realized_pnl(
                    entry_price, avg_price, filled_qty, signal.symbol
                )
            target = int(signal.target_quantity or filled_qty)
            if filled_qty < target:
                logger.critical(
                    f"[GC Reconcile] {signal.symbol} SELL partially filled {filled_qty}/{target} "
                    "— 잔량 재매도를 위해 IN_POSITION 복원"
                )
                await self._restore_position_from_broker(strategy_id, signal)

        await self.signal_repo.update_execution(
            signal.id,
            status=SignalStatus.EXECUTED,
            executed_price=avg_price,
            executed_quantity=filled_qty,
            realized_pnl=realized_pnl,
            realized_pnl_ratio=realized_pnl_ratio,
        )

    async def _cancel_unfilled(self, strategy_id: int, signal) -> None:
        logger.warning(
            f"[GC Reconcile] {signal.symbol} {signal.signal_type} order_no={signal.order_no} "
            "unfilled after session close → CANCELLED, state reverted"
        )
        if signal.signal_type == SignalType.BUY.value:
            await self.symbol_state_repo.reset_to_waiting(strategy_id, signal.symbol)
        else:
            await self._restore_position_from_broker(strategy_id, signal)
        await self.signal_repo.update_execution(
            signal.id, status=SignalStatus.CANCELLED, exit_reason="unfilled"
        )

    async def _restore_position_from_broker(self, strategy_id: int, signal) -> None:
        """매도 미체결/일부체결 시 브로커 잔고(평균매입가)를 진실로 IN_POSITION을 복원한다."""
        account_service = await self._get_account_service()
        positions = await account_service.get_position_list()
        held = next(
            (p for p in positions.positions if p.symbol == signal.symbol and p.quantity > 0),
            None,
        )
        if held is None:
            await self.symbol_state_repo.reset_to_waiting(strategy_id, signal.symbol)
            return
        entry_price = _signal_entry_price(signal) or held.avg_purchase_price
        await self.symbol_state_repo.update_state(
            strategy_id=strategy_id,
            symbol=signal.symbol,
            new_state=SymbolState.IN_POSITION,
            entry_price=entry_price,
        )

    async def _benchmark_change_today(self) -> float:
        """벤치(gc_regime_benchmark) 당일 종가 수익률. 당일 봉이 없거나 오류면 0.0(급락 가드 미발동).

        데이터 부재 시 신규 매수 차단은 레짐 게이트(fail-closed)가 담당한다.
        """
        try:
            bench = await self._fetch_ohlcv(settings.gc_regime_benchmark, days=10, min_candles=2)
            if bench is None or len(bench) < 2:
                return 0.0
            last = pd.Timestamp(bench["timestamp"].iloc[-1])
            last_day = (last.tz_convert(KST) if last.tzinfo else last).date()
            if last_day != datetime.now(KST).date():
                return 0.0
            closes = bench["close"].astype(float)
            change = float(closes.iloc[-1] / closes.iloc[-2] - 1.0)
            logger.info(f"[GC Engine] benchmark change today {change:.2%}")
            return change
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[GC Engine] benchmark change unavailable: {e}")
            return 0.0

    async def _evaluate_entry_regime(self, *, fail_open: bool) -> bool:
        """신규 매수 시장 국면 게이트(실행당 1회). 비활성이면 항상 허용."""
        if not settings.gc_regime_filter_enabled:
            return True
        try:
            bench = await get_regime_benchmark_ohlc(
                self.session, settings.gc_regime_benchmark, days=500
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[GC Engine] regime benchmark load failed: {e}")
            return fail_open
        allowed = market_regime_ok(bench, fail_open=fail_open)
        logger.info(f"[GC Engine] entry regime allowed={allowed} (fail_open={fail_open})")
        return allowed

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
            # cache_freshness_days=0: 15:35 실행에서 "어제 봉까지 있으면 신선"으로 보고 당일 종가를
            # 받지 않던 문제(신호가 백테스트 same_close보다 하루 늦음) 수정. 당일 봉이 이미 캐시돼 있으면
            # API를 다시 부르지 않는다(15:31 이후 봉만 저장되므로 캐시된 당일 봉은 확정값).
            df = await data_loader.load_ohlcv_dataframe(
                symbol=symbol,
                days=days,
                interval="1d",
                min_candles=min_candles,
                cache_freshness_days=0,
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
            atr=(Decimal(str(row["atr"])) if "atr" in row.index and pd.notna(row["atr"]) else None),
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
            balance = await account_service.get_account_balance(
                strategy.account_no, use_cache=False
            )
            initial_capital = Decimal(str(balance.total_balance))
            if initial_capital <= 0:
                raise ValueError("account total balance is zero")
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

        # EXECUTED면 명백한 중복. 단 매도 일부 체결(잔량 재매도 대상)은 중복이 아니다.
        if latest.signal_status == SignalStatus.EXECUTED.value:
            target = getattr(latest, "target_quantity", None)
            executed = getattr(latest, "executed_quantity", None)
            partial_sell = (
                latest.signal_type == SignalType.SELL.value
                and target is not None
                and executed is not None
                and executed < target
            )
            return None if partial_sell else latest

        # EXECUTED가 아니어도 order_no가 있으면 주문은 이미 브로커에 접수된 것이 durable하게
        # 증명된다 → 재주문 차단(체결 대기 PENDING, 마킹 실패 FAILED 포함). 예외는 reconcile이
        # KIS 체결조회로 "미체결 확정"한 CANCELLED뿐이다 — 이때만 정상 재시도를 허용한다.
        if latest.signal_status != SignalStatus.CANCELLED.value and getattr(
            latest, "order_no", None
        ):
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


KST = timezone(timedelta(hours=9), "KST")
# 장후 시간외 종가 세션 종료(16:00) + 여유. 이 시각 이후 체결 0이면 미체결 확정.
ORDER_SESSION_CLOSE_KST = time(16, 5)


def _order_session_closed(signal_at: datetime, now_kst: datetime) -> bool:
    """주문이 나간 거래일(KST)의 주문 세션이 끝났는지.

    signal_at은 DB(timestamptz)에서 aware로 오며, naive면 프로세스 로컬 시각으로 해석한다
    (create_signal이 datetime.now()로 기록).
    """
    placed_day = signal_at.astimezone(KST).date()
    if now_kst.date() > placed_day:
        return True
    return now_kst.time() >= ORDER_SESSION_CLOSE_KST


def _signal_meta(signal) -> dict:
    raw = getattr(signal, "metadata_json", None)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _signal_entry_price(signal) -> Decimal | None:
    value = _signal_meta(signal).get("entry_price")
    try:
        return Decimal(str(value)) if value not in (None, "", "None") else None
    except (ArithmeticError, ValueError):
        return None


def estimate_realized_pnl(
    entry_price: Decimal, exit_price: Decimal, quantity: int, symbol: str
) -> tuple[Decimal, Decimal]:
    """수수료(양방향)·매도세를 반영한 실현손익과 비용기준 수익률.

    매도세율은 백테스트 비용 스케줄의 최신 값을 쓴다(국내 ETF 면제 등은 스케줄이 결정).
    """
    schedule = get_latest_backtest_cost_schedule()
    commission = Decimal(str(settings.live_commission_rate))
    tax_rate = _sell_tax_rate_for(schedule, symbol)
    buy_amount = entry_price * quantity
    sell_amount = exit_price * quantity
    costs = buy_amount * commission + sell_amount * (commission + tax_rate)
    pnl = sell_amount - buy_amount - costs
    basis = buy_amount * (1 + commission)
    ratio = pnl / basis if basis > 0 else Decimal("0")
    return pnl.quantize(Decimal("1")), ratio.quantize(Decimal("0.000001"))


def _sell_tax_rate_for(schedule, symbol: str) -> Decimal:
    """국내 상장 ETF는 증권거래세 면제(백테스트 OrderManager.is_tax_exempt와 같은 목록)."""
    exempt = {s.strip() for s in settings.etf_universe_symbols if s and s.strip()}
    if symbol in exempt:
        return Decimal("0")
    return Decimal(str(schedule.sell_tax_rate))


def _warn_if_ma_drift(strategy_id: int, config: GoldenCrossConfigDTO) -> None:
    """스캔/매도분석(settings.gc_*_ma_period)과 실주문 전략 config의 MA가 다르면 경고한다.

    2026-11-06 이전에 스캔은 .env 50/200, 실주문은 DB config 55/165로 서로 다른 신호를 냈다.
    """
    live = (config.ma_config.short_period, config.ma_config.long_period)
    scan = (settings.gc_short_ma_period, settings.gc_long_ma_period)
    if live != scan:
        logger.error(
            f"[GC Engine] MA drift: strategy {strategy_id} config MA{live[0]}/{live[1]} "
            f"!= scan/sell settings MA{scan[0]}/{scan[1]} — 알림·매도분석과 실주문 신호가 달라진다"
        )
