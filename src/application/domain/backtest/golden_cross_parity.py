# -*- coding: utf-8 -*-
"""
Golden Cross Live-Parity Backtest - 라이브 패리티 골든크로스 백테스트

목적(P0 시그널 단일화):
    검증 하네스가 **실제로 매매되는 로직**을 백테스트하도록 보장한다.
    기존 `GoldenCrossSignalGenerator`는 실주문 경로(state_machine)와 다른
    파라미터/판정으로 독자 재구현되어 있어 "매매되지 않는 것"을 검증했다.

    이 모듈은 실주문 엔진(`golden_cross_engine._process_symbol`)이 사용하는
    **동일한 `GoldenCrossStateMachine` + 동일한 지표 계산
    (`prepare_golden_cross_indicators`)** 을 바-리플레이하여, 진입/청산 시그널이
    라이브와 구조적으로 동일하도록 만든다.

    - 시그널: 실주문 FSM을 그대로 구동 (crossover→pullback→recovery 진입, dead-cross
      / -7% 손절 / +20% 익절 / 트레일링 / 최대보유 청산)
    - 체결/비용: 검증된 `BacktestOrderManager` (거래세/수수료/슬리피지)
    - 성과: `result_builder.build_backtest_result` (엔진과 동일 계산 경로)

라이브 대비 의도적 차이(문서화):
    - 포지션 사이징은 비용 인지형 백테스트 사이징(단일 lot). 라이브는 현금의
      `allocation_ratio`를 `int(allocation/price)`로 나눈 단일 주문이며, parity도
      단일 주문·`allocation_ratio` 기준으로 동일한 "1 심볼 1 포지션" 규칙을 따른다.
      (엔진의 3-lot 분할 매수는 사용하지 않는다.)
    - 체결 시점은 시그널 발생 바의 종가(same_close). 라이브는 15:35 종가 지정가.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

import pandas as pd

from src.adapters.database.models.strategy_symbol_state import SymbolState
from src.application.common.indicators import TechnicalIndicators
from src.application.domain.backtest.dto import (
    BacktestConfigDTO,
    BacktestResultDTO,
    DailyStatsDTO,
    TradeDTO,
)
from src.application.domain.backtest.order_manager import BacktestOrderManager
from src.application.domain.backtest.result_builder import build_backtest_result
from src.application.domain.strategy.dto import GoldenCrossConfigDTO
from src.application.domain.strategy.state_machine import (
    GoldenCrossStateMachine,
    IndicatorSnapshot,
    Signal,
)

# FSM 청산 사유 → TradeDTO.exit_reason 허용 패턴 매핑.
# state_machine의 dead_cross는 TradeDTO 패턴에 없으므로 reverse-signal 청산인
# "signal"로 매핑한다. 나머지는 그대로 통과.
_EXIT_REASON_MAP = {
    "dead_cross": "signal",
    "stop_loss": "stop_loss",
    "take_profit": "take_profit",
    "trailing_stop": "trailing_stop",
    "max_hold": "max_hold",
}


def _to_datetime(ts: Any) -> datetime:
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.replace(tzinfo=None)
    return cast(datetime, ts)


@dataclass(frozen=True, slots=True)
class ParitySignal:
    """리플레이가 생성한 단일 진입/청산 시그널."""

    index: int
    timestamp: datetime
    signal: str  # "buy" | "sell"
    reason: str | None
    close: Decimal


class GoldenCrossParityReplay:
    """실주문 상태머신을 바-리플레이하는 라이브 패리티 백테스트."""

    def __init__(self, config: GoldenCrossConfigDTO | None = None) -> None:
        self.config = config or GoldenCrossConfigDTO()
        self.state_machine = GoldenCrossStateMachine(self.config)

    # ==================== 지표/스냅샷 ====================

    def _prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """실주문 엔진과 동일한 지표를 계산한다."""
        return TechnicalIndicators.prepare_golden_cross_indicators(
            df,
            short_ma_period=self.config.ma_config.short_period,
            long_ma_period=self.config.ma_config.long_period,
            stoch_k_period=self.config.stochastic_config.k_period,
            stoch_d_period=self.config.stochastic_config.d_period,
        )

    @staticmethod
    def _snapshot(row: pd.Series) -> IndicatorSnapshot:
        """엔진 `_create_snapshot`과 동일한 변환(NaN→0/50 규칙 포함)."""
        return IndicatorSnapshot(
            timestamp=_to_datetime(row["timestamp"]),
            close=Decimal(str(row["close"])),
            ma_short=Decimal(str(row["ma_short"])) if pd.notna(row["ma_short"]) else Decimal("0"),
            ma_long=Decimal(str(row["ma_long"])) if pd.notna(row["ma_long"]) else Decimal("0"),
            stoch_k=float(row["stoch_k"]) if pd.notna(row["stoch_k"]) else 50.0,
            stoch_d=float(row["stoch_d"]) if pd.notna(row["stoch_d"]) else 50.0,
        )

    # ==================== 시그널 스케줄(SSOT) ====================

    def build_signal_schedule(self, df: pd.DataFrame) -> list[ParitySignal]:
        """OHLCV로부터 라이브 FSM을 리플레이하여 진입/청산 시그널을 생성한다."""
        return self._build_schedule(self._prepare(df))

    def _build_schedule(self, prepared: pd.DataFrame) -> list[ParitySignal]:
        long_period = self.config.ma_config.long_period
        # 라이브 가드 `len(df) >= long_period + 10` 를 그대로 반영.
        warmup = long_period + 10
        n = len(prepared)
        schedule: list[ParitySignal] = []
        if n < warmup:
            return schedule

        sm = self.state_machine
        risk = self.config.risk_config
        rows = [self._snapshot(prepared.iloc[i]) for i in range(n)]

        state_str: str | None = None
        gc_date: datetime | None = None
        pullback_date: datetime | None = None
        entry_price: Decimal | None = None
        entry_date: datetime | None = None
        highest_price: Decimal | None = None
        trailing = False

        start_idx = warmup - 1  # 0-based 첫 평가 바
        for i in range(start_idx, n):
            current = rows[i]
            prev = rows[i - 1]

            if state_str is None:
                state_str = sm.get_initial_state(current).value
                gc_date = pullback_date = None
                entry_price = entry_date = highest_price = None
                trailing = False

            transition = sm.process(
                current=current,
                prev=prev,
                current_state=SymbolState(state_str),
                gc_date=gc_date,
                pullback_date=pullback_date,
                entry_price=entry_price,
                entry_date=entry_date,
                highest_price=highest_price,
                trailing_stop_activated=trailing,
            )

            # 엔진 6-1 미러: 현재 IN_POSITION이면 최고가/트레일링 활성화 갱신
            if state_str == SymbolState.IN_POSITION.value:
                if highest_price is None or current.close > highest_price:
                    highest_price = current.close
                if entry_price and entry_price > 0:
                    pnl = float((current.close - entry_price) / entry_price)
                    if pnl >= risk.trailing_stop_activation and not trailing:
                        trailing = True

            signal = transition.signal
            if signal == Signal.BUY:
                schedule.append(
                    ParitySignal(i, current.timestamp, "buy", transition.reason, current.close)
                )
                # _update_state_after_signal(BUY): 신규 포지션
                state_str = transition.new_state.value
                entry_price = current.close
                entry_date = current.timestamp
                highest_price = None
                trailing = False
                gc_date = pullback_date = None
            elif signal == Signal.SELL:
                schedule.append(
                    ParitySignal(i, current.timestamp, "sell", transition.reason, current.close)
                )
                # reset_to_waiting
                state_str = SymbolState.WAITING_FOR_GC.value
                entry_price = entry_date = highest_price = None
                gc_date = pullback_date = None
                trailing = False
            else:
                state_str = transition.new_state.value
                gc_date = transition.gc_date
                pullback_date = transition.pullback_date

        return schedule

    # ==================== 실행(체결/비용/성과) ====================

    def run(
        self,
        symbol: str,
        df: pd.DataFrame,
        backtest_config: BacktestConfigDTO | None = None,
    ) -> BacktestResultDTO:
        """스케줄을 단일 심볼·단일 포지션으로 체결하고 성과를 집계한다."""
        backtest_config = backtest_config or BacktestConfigDTO()
        prepared = self._prepare(df)
        if len(prepared) == 0:
            raise ValueError("empty OHLCV for parity backtest")

        schedule = self._build_schedule(prepared)
        schedule_by_index = {s.index: s for s in schedule}

        order_manager = BacktestOrderManager(backtest_config)
        alloc = self.config.position.allocation_ratio
        initial_capital: Decimal = backtest_config.initial_capital
        cash: Decimal = initial_capital

        trades: list[TradeDTO] = []
        completed_trades: list[dict] = []
        equity_curve: list[Decimal] = []
        daily_stats: list[DailyStatsDTO] = []

        open_trade: TradeDTO | None = None
        open_qty = 0

        for i in range(len(prepared)):
            row = prepared.iloc[i]
            date = _to_datetime(row["timestamp"])
            close = Decimal(str(row["close"]))

            sig = schedule_by_index.get(i)
            if sig is not None:
                if sig.signal == "buy" and open_trade is None:
                    qty = order_manager.calculate_position_size(cash, alloc, close)
                    if qty > 0 and order_manager.can_afford(cash, close, qty):
                        trade, total_cost = order_manager.execute_buy_order(
                            symbol=symbol, price=close, quantity=qty, date=date
                        )
                        if cash >= total_cost:
                            cash -= total_cost
                            open_trade = trade
                            open_qty = qty
                            trades.append(trade)
                elif sig.signal == "sell" and open_trade is not None:
                    exit_reason = _EXIT_REASON_MAP.get(sig.reason or "", "signal")
                    completed, net_proceeds = order_manager.execute_sell_order(
                        trade=open_trade, price=close, date=date, exit_reason=exit_reason
                    )
                    cash += net_proceeds
                    completed_trades.append(
                        {
                            "profit_rate": completed.profit_rate,
                            "holding_days": completed.holding_days,
                        }
                    )
                    for idx, t in enumerate(trades):
                        if t.trade_id == completed.trade_id:
                            trades[idx] = completed
                            break
                    open_trade = None
                    open_qty = 0

            position_value = close * open_qty if open_trade is not None else Decimal("0")
            equity = cash + position_value
            equity_curve.append(equity)

            daily_return = 0.0
            if len(equity_curve) > 1 and equity_curve[-2] > 0:
                daily_return = float((equity - equity_curve[-2]) / equity_curve[-2] * 100)
            cumulative_return = float((equity - initial_capital) / initial_capital * 100)
            cummax = max(float(e) for e in equity_curve)
            drawdown = (
                float((equity - Decimal(str(cummax))) / Decimal(str(cummax)) * 100)
                if cummax > 0
                else 0.0
            )
            daily_stats.append(
                DailyStatsDTO(
                    date=date,
                    equity=equity,
                    cash=cash,
                    position_value=position_value,
                    daily_return=daily_return,
                    cumulative_return=cumulative_return,
                    drawdown=drawdown,
                )
            )

        start_date = _to_datetime(prepared.iloc[0]["timestamp"])
        end_date = _to_datetime(prepared.iloc[-1]["timestamp"])
        return build_backtest_result(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            execution_timing="same_close",
            equity_curve=equity_curve,
            daily_stats=daily_stats,
            trades=trades,
            completed_trades=completed_trades,
        )
