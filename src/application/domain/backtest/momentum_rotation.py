# -*- coding: utf-8 -*-
"""
ETF Momentum Rotation (research, H4) — 월간 리밸런스 추세추종/모멘텀 포트폴리오

라이브 경로와 무관한 **연구 전용** 대안 전략. 파라미터는 사전 고정(a-priori)이며
OOS에서 튜닝하지 않는다.

규칙(사전 등록):
    1. 시그널일: 매월 마지막 거래일 종가 + 활성 첫날(플랫 시작 초기 배분).
    2. 편입 자격(point-in-time): 시그널일까지 자체 바 ≥ max(lookback, trend_ma)+1.
    3. 점수: 12-1 모멘텀 = close[t−skip] / close[t−lookback] − 1 (자체 바 인덱스 기준).
    4. 상위 top_n 선택. 그중 종가 > MA(trend_ma)인 종목만 보유, 아니면 그 슬롯은 현금.
    5. 체결: next_open(기본, t+1 시가) 또는 same_close. 탈락 종목 전량 매도 → 신규 종목을
       총자산/top_n 목표금액(잔여현금 한도)으로 매수. 유지 종목은 재조정하지 않는다
       (회전율 최소화, 사전 고정).
    6. 비용: `BacktestOrderManager`(수수료·슬리피지·ETF 매도세 면제) — 골든크로스와 동일.
    7. 현금: 선택적 이자 스케줄(`CashInterestSchedule`).

순수 계산(DB/FastAPI 의존 없음).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from src.application.domain.backtest.cash_interest import CashInterestSchedule
from src.application.domain.backtest.dto import (
    BacktestConfigDTO,
    BacktestResultDTO,
    DailyStatsDTO,
    TradeDTO,
)
from src.application.domain.backtest.order_manager import BacktestOrderManager
from src.application.domain.backtest.result_builder import build_backtest_result


@dataclass(frozen=True, slots=True)
class MomentumRotationConfig:
    top_n: int = 3
    lookback: int = 252
    skip: int = 21
    trend_ma: int = 200
    fill_timing: str = "next_open"
    cash_interest: CashInterestSchedule | None = None
    liquidate_at_end: bool = False

    def __post_init__(self) -> None:
        if self.top_n < 1:
            raise ValueError("top_n must be >= 1")
        if not 0 <= self.skip < self.lookback:
            raise ValueError("require 0 <= skip < lookback")
        if self.fill_timing not in ("same_close", "next_open"):
            raise ValueError(f"unsupported fill_timing: {self.fill_timing}")

    @property
    def min_history(self) -> int:
        return max(self.lookback, self.trend_ma) + 1

    def describe(self) -> str:
        interest = self.cash_interest.label if self.cash_interest else "0%"
        return (
            f"mom{self.lookback}-{self.skip}_top{self.top_n}_ma{self.trend_ma}"
            f"_{self.fill_timing}_cash{interest}"
        )


@dataclass(frozen=True, slots=True)
class RebalanceRecord:
    signal_date: date
    ranked: tuple[str, ...]  # 상위 top_n(점수순)
    held_after: tuple[str, ...]  # 추세 필터 통과 → 목표 보유
    eligible: int


@dataclass(frozen=True, slots=True)
class MomentumRunResult:
    result: BacktestResultDTO
    rebalances: list[RebalanceRecord] = field(default_factory=list)
    interest_earned: Decimal = Decimal("0")
    open_fallbacks: int = 0


@dataclass(slots=True)
class _Pos:
    quantity: int
    trade: TradeDTO


def _to_date(ts: Any) -> date:
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    return ts.date() if isinstance(ts, datetime) else ts


def _to_dt(ts: Any) -> datetime:
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.replace(tzinfo=None)
    return ts


def month_end_signal_days(calendar: list[date]) -> set[date]:
    """정렬된 거래일 달력에서 각 월의 마지막 거래일."""
    out: set[date] = set()
    for i, d in enumerate(calendar):
        nxt = calendar[i + 1] if i + 1 < len(calendar) else None
        if nxt is None or (nxt.year, nxt.month) != (d.year, d.month):
            out.add(d)
    return out


class MomentumRotationEngine:
    def __init__(self, config: MomentumRotationConfig | None = None) -> None:
        self.config = config or MomentumRotationConfig()

    def run(
        self,
        panels: dict[str, pd.DataFrame],
        backtest_config: BacktestConfigDTO | None = None,
        *,
        active_from: date | None = None,
        calendar: list[date] | None = None,
    ) -> MomentumRunResult:
        """active_from 이전은 워밍업(지표 계산용). calendar 미지정 시 패널 합집합 달력."""
        if not panels:
            raise ValueError("empty panels for momentum backtest")
        cfg = self.config
        backtest_config = backtest_config or BacktestConfigDTO()
        om = BacktestOrderManager(backtest_config)
        next_open = cfg.fill_timing == "next_open"

        # 심볼별 정렬 시계열(자체 바 인덱스)
        closes: dict[str, list[float]] = {}
        opens: dict[str, list[float]] = {}
        dts: dict[str, list[datetime]] = {}
        idx: dict[str, dict[date, int]] = {}
        ma: dict[str, list[float]] = {}
        all_days: set[date] = set()
        for sym, df in panels.items():
            df = df.sort_values("timestamp").reset_index(drop=True)
            c = [float(x) for x in df["close"].tolist()]
            o = (
                [float(x) if x == x else 0.0 for x in df["open"].tolist()]
                if "open" in df.columns
                else c
            )
            ds = [_to_dt(t) for t in df["timestamp"]]
            closes[sym] = c
            opens[sym] = o
            dts[sym] = ds
            idx[sym] = {d.date(): i for i, d in enumerate(ds)}
            ma[sym] = pd.Series(c).rolling(cfg.trend_ma).mean().tolist()
            all_days.update(idx[sym].keys())
        cal = sorted(set(calendar) if calendar is not None else all_days)
        cal = [d for d in cal if d in all_days]
        if not cal:
            raise ValueError("empty calendar")
        active_days = [d for d in cal if active_from is None or d >= active_from]
        if not active_days:
            raise ValueError("no active days")
        signal_days = month_end_signal_days(cal) | {active_days[0]}
        last_day = active_days[-1]
        dt_of: dict[date, datetime] = {}
        for sym in panels:
            for d, i in idx[sym].items():
                dt_of.setdefault(d, dts[sym][i])

        cash = backtest_config.initial_capital
        positions: dict[str, _Pos] = {}
        last_px: dict[str, Decimal] = {}
        trades: list[TradeDTO] = []
        completed: list[dict] = []
        equity_curve: list[Decimal] = []
        daily_stats: list[DailyStatsDTO] = []
        rebalances: list[RebalanceRecord] = []
        pending_target: tuple[str, ...] | None = None
        interest = Decimal("0")
        open_fallbacks = 0
        prev_day: date | None = None

        def px_close(sym: str, d: date) -> Decimal | None:
            i = idx[sym].get(d)
            if i is None:
                return last_px.get(sym)
            return Decimal(str(closes[sym][i]))

        def sell(sym: str, price: Decimal, when: datetime) -> None:
            nonlocal cash
            pos = positions.pop(sym)
            done, net = om.execute_sell_order(pos.trade, price, when, exit_reason="signal")
            cash += net
            completed.append(
                {
                    "profit_rate": done.profit_rate,
                    "holding_days": done.holding_days,
                    "profit": done.profit,
                }
            )
            for k, t in enumerate(trades):
                if t.trade_id == done.trade_id:
                    trades[k] = done
                    break

        def rebalance(target: tuple[str, ...], d: date, use_open: bool) -> None:
            nonlocal cash, open_fallbacks

            def fill_px(sym: str) -> Decimal | None:
                i = idx[sym].get(d)
                if i is None:
                    return None
                if use_open:
                    o = opens[sym][i]
                    if o > 0:
                        return Decimal(str(o))
                    open_fallbacks += 1
                return Decimal(str(closes[sym][i]))

            # 1) 탈락 종목 매도(당일 바 없는 종목은 보유 유지 — 다음 리밸런스에서 재평가)
            for sym in [s for s in positions if s not in target]:
                p = fill_px(sym)
                if p is not None and p > 0:
                    sell(sym, p, dt_of[d])
            # 2) 목표금액 = 총자산 / top_n (유지 종목은 재조정 없음)
            mark = {s: (fill_px(s) or last_px.get(s) or Decimal("0")) for s in positions}
            equity = cash + sum(mark[s] * positions[s].quantity for s in positions)
            slot = equity / Decimal(cfg.top_n)
            for sym in target:
                if sym in positions:
                    continue
                p = fill_px(sym)
                if p is None or p <= 0:
                    continue
                qty = om.calculate_position_size(min(cash, slot), 1.0, p)
                if qty < 1 or not om.can_afford(cash, p, qty):
                    continue
                trade, cost = om.execute_buy_order(sym, p, qty, dt_of[d])
                if cost > cash:
                    continue
                cash -= cost
                positions[sym] = _Pos(qty, trade)
                trades.append(trade)

        for d in cal:
            in_active = active_from is None or d >= active_from
            if not in_active:
                for sym in panels:
                    i = idx[sym].get(d)
                    if i is not None:
                        last_px[sym] = Decimal(str(closes[sym][i]))
                continue
            # 이자
            if cfg.cash_interest is not None and prev_day is not None and cash > 0:
                acc = cash * cfg.cash_interest.accrual_factor(prev_day, d)
                cash += acc
                interest += acc
            prev_day = d
            # next_open: 전일 시그널 체결
            if next_open and pending_target is not None:
                rebalance(pending_target, d, use_open=True)
                pending_target = None
            for sym in panels:
                i = idx[sym].get(d)
                if i is not None:
                    last_px[sym] = Decimal(str(closes[sym][i]))
            # 시그널(종가 기준)
            if d in signal_days and d != last_day:
                scored: list[tuple[float, str]] = []
                for sym in panels:
                    i = idx[sym].get(d)
                    if i is None or i + 1 < cfg.min_history:
                        continue
                    base = closes[sym][i - cfg.lookback]
                    recent = closes[sym][i - cfg.skip]
                    if base <= 0:
                        continue
                    scored.append((recent / base - 1.0, sym))
                scored.sort(key=lambda x: (-x[0], x[1]))
                ranked = tuple(s for _, s in scored[: cfg.top_n])
                held = tuple(
                    s
                    for s in ranked
                    if ma[s][idx[s][d]] == ma[s][idx[s][d]]  # not NaN
                    and closes[s][idx[s][d]] > ma[s][idx[s][d]]
                )
                rebalances.append(RebalanceRecord(d, ranked, held, len(scored)))
                if next_open:
                    pending_target = held
                else:
                    rebalance(held, d, use_open=False)
            # MTM
            pos_val = Decimal("0")
            for sym, pos in positions.items():
                p = px_close(sym, d)
                if p is not None:
                    pos_val += p * pos.quantity
            if cfg.liquidate_at_end and d == last_day and positions:
                liq = Decimal("0")
                for sym, pos in positions.items():
                    p = px_close(sym, d)
                    if p is not None:
                        liq += om.liquidation_value(sym, p, pos.quantity, dt_of[d])
                pos_val = liq
            equity = cash + pos_val
            equity_curve.append(equity)
            dr = 0.0
            if len(equity_curve) > 1 and equity_curve[-2] > 0:
                dr = float((equity - equity_curve[-2]) / equity_curve[-2] * 100)
            c0 = backtest_config.initial_capital
            peak = max(equity_curve)
            daily_stats.append(
                DailyStatsDTO(
                    date=dt_of[d],
                    equity=equity,
                    cash=cash,
                    position_value=pos_val,
                    daily_return=dr,
                    cumulative_return=float((equity - c0) / c0 * 100),
                    drawdown=float((equity - peak) / peak * 100) if peak > 0 else 0.0,
                )
            )

        result = build_backtest_result(
            symbol="MOMENTUM",
            start_date=daily_stats[0].date,
            end_date=daily_stats[-1].date,
            initial_capital=backtest_config.initial_capital,
            execution_timing="next_open" if next_open else "same_close",
            equity_curve=equity_curve,
            daily_stats=daily_stats,
            trades=trades,
            completed_trades=completed,
        )
        return MomentumRunResult(result, rebalances, interest, open_fallbacks)
