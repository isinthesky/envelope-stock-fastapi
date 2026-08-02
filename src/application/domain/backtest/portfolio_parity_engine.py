# -*- coding: utf-8 -*-
"""
Portfolio Parity Engine - 공유 현금북 포트폴리오 백테스트 (P2)

P0의 `GoldenCrossParityReplay`(라이브 FSM 시그널)를 유니버스로 확장한다.
기존 `backtest.service.simulate_universe_portfolio`의 한계를 정면으로 해소한다:

    기존 sim의 문제              →  이 엔진의 처방
    ─────────────────────────────────────────────────────────
    비용/세금 미적용             →  BacktestOrderManager 전 체결 경로 적용
    equal-slot 사이징            →  라이브와 동일 allocation_ratio(현금 비율)
    집중도 캡 없음(카운트만)     →  max_positions + **섹터 노출 캡** 강제
    사후 거래-스티칭             →  **일별 시가평가** 공유 현금북 시뮬
    후행편향 랭킹(full-return)   →  시그널-시점 정보(회복 강도)로만 우선순위
    divergent 생성기 시그널      →  parity(라이브 FSM) 시그널

무음 누락 금지: 캡/현금 제한으로 진입 거부된 후보는 사유와 함께 기록한다.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import pandas as pd

from src.adapters.database.models.strategy_symbol_state import SymbolState
from src.application.domain.backtest.dto import (
    BacktestConfigDTO,
    BacktestResultDTO,
    DailyStatsDTO,
    TradeDTO,
)
from src.application.domain.backtest.golden_cross_parity import GoldenCrossParityReplay
from src.application.domain.backtest.order_manager import BacktestOrderManager
from src.application.domain.backtest.result_builder import build_backtest_result
from src.application.domain.strategy.dto import GoldenCrossConfigDTO
from src.application.domain.strategy.state_machine import (
    GoldenCrossStateMachine,
    IndicatorSnapshot,
    Signal,
    StateTransition,
)

_EXIT_REASON_MAP = {
    "dead_cross": "signal",
    "stop_loss": "stop_loss",
    "take_profit": "take_profit",
    "trailing_stop": "trailing_stop",
    "max_hold": "max_hold",
}

# 진입 우선순위: 강한 회복을 약한 회복보다 먼저(시그널-시점 정보, 후행편향 없음).
_BUY_REASON_PRIORITY = {"stoch_strong_recovery": 0, "stoch_recovery_crossover": 1}


@dataclass(frozen=True, slots=True)
class PortfolioConstraints:
    """포트폴리오 리스크 제약."""

    max_positions: int = 5
    max_sector_weight: float = 1.0  # 1.0 = 섹터 캡 비활성
    # 신규 포지션당 현금 비율. None이면 config.position.allocation_ratio(라이브 값) 사용.
    # 값을 주면 포트폴리오 레벨에서 명시적으로 오버라이드한다.
    allocation_ratio: float | None = None
    # symbol -> sector. 미지정 종목은 자기 자신을 섹터로 간주(사실상 종목 캡).
    sector_map: dict[str, str] = field(default_factory=dict)

    def sector_of(self, symbol: str) -> str:
        return self.sector_map.get(symbol, symbol)


@dataclass(slots=True)
class _SymbolFSM:
    """포트폴리오 실행 중 각 심볼의 라이브 상태머신 상태(체결 결과 반영)."""

    state: str
    gc_date: datetime | None = None
    pullback_date: datetime | None = None
    entry_price: Decimal | None = None
    entry_date: datetime | None = None
    highest_price: Decimal | None = None
    trailing: bool = False

    def reset_to_waiting(self) -> None:
        self.state = SymbolState.WAITING_FOR_GC.value
        self.gc_date = self.pullback_date = None
        self.entry_price = self.entry_date = self.highest_price = None
        self.trailing = False


@dataclass(frozen=True, slots=True)
class RejectedEntry:
    date: date
    symbol: str
    reason: str


@dataclass(slots=True)
class _OpenPosition:
    symbol: str
    sector: str
    quantity: int
    trade: TradeDTO


@dataclass(frozen=True, slots=True)
class PortfolioRunResult:
    result: BacktestResultDTO  # symbol="PORTFOLIO" 성과 집계
    entered_positions: int
    rejected: list[RejectedEntry]
    max_sector_exposure: float  # 시뮬 전체에서 관측된 최대 단일 섹터 비중
    max_concurrent_positions: int


class PortfolioParityEngine:
    """parity 시그널 기반 일별 시가평가 공유 현금북 포트폴리오 엔진."""

    def __init__(
        self,
        config: GoldenCrossConfigDTO | None = None,
        constraints: PortfolioConstraints | None = None,
    ) -> None:
        self.config = config or GoldenCrossConfigDTO()
        self.constraints = constraints or PortfolioConstraints()
        self.replay = GoldenCrossParityReplay(self.config)

    def run(
        self,
        panels: dict[str, pd.DataFrame],
        backtest_config: BacktestConfigDTO | None = None,
        active_from: date | None = None,
    ) -> PortfolioRunResult:
        """포트폴리오 백테스트 실행.

        Args:
            active_from: 지정 시 이 날짜 이전은 지표/FSM 워밍업에만 사용하고,
                포지션 진입·성과 집계는 이 날짜부터 시작한다(walk-forward fold의
                독립 OOS 측정용). 시그널 스케줄은 전체 슬라이스로 계산되므로
                active_from 시점 FSM 상태가 올바르게 반영된다.
        """
        backtest_config = backtest_config or BacktestConfigDTO()
        if not panels:
            raise ValueError("empty panels for portfolio backtest")

        sm = GoldenCrossStateMachine(self.config)
        risk = self.config.risk_config

        # 1) 심볼별 지표/스냅샷/종가 사전계산(실주문과 동일 지표)
        rows: dict[str, list[IndicatorSnapshot]] = {}
        didx: dict[str, dict[date, int]] = {}
        close_map: dict[str, dict[date, Decimal]] = {}
        dt_map: dict[date, datetime] = {}
        all_dates: set[date] = set()
        for symbol, df in panels.items():
            prepared = self.replay._prepare(df)
            srows = [self.replay._snapshot(prepared.iloc[i]) for i in range(len(prepared))]
            rows[symbol] = srows
            dmap: dict[date, int] = {}
            cmap: dict[date, Decimal] = {}
            for i, snap in enumerate(srows):
                d = snap.timestamp.date()
                dmap[d] = i
                cmap[d] = snap.close
                dt_map.setdefault(d, snap.timestamp)
                all_dates.add(d)
            didx[symbol] = dmap
            close_map[symbol] = cmap

        calendar = sorted(all_dates)

        order_manager = BacktestOrderManager(backtest_config)
        # allocation_ratio: 제약에 명시값 있으면 오버라이드, 없으면 config(라이브) 값
        alloc = (
            self.constraints.allocation_ratio
            if self.constraints.allocation_ratio is not None
            else self.config.position.allocation_ratio
        )
        max_pos = self.constraints.max_positions
        max_sector = self.constraints.max_sector_weight

        initial_capital: Decimal = backtest_config.initial_capital
        cash: Decimal = initial_capital

        positions: dict[str, _OpenPosition] = {}
        fsm: dict[str, _SymbolFSM] = {}
        last_close: dict[str, Decimal] = {}
        trades: list[TradeDTO] = []
        completed_trades: list[dict] = []
        rejected: list[RejectedEntry] = []
        equity_curve: list[Decimal] = []
        daily_stats: list[DailyStatsDTO] = []
        entered_positions = 0
        max_sector_exposure = 0.0
        max_concurrent = 0

        for d in calendar:
            exec_dt = dt_map[d]
            for symbol, cmap in close_map.items():
                if d in cmap:
                    last_close[symbol] = cmap[d]

            # 워밍업 구간(active_from 이전): FSM은 active_from에서 get_initial_state로
            # 플랫 초기화(지표는 lookback으로 유효). 이전 구간은 진입/집계 없이 건너뜀.
            if active_from is not None and d < active_from:
                continue

            # ── Phase A: 당일 바가 있는 심볼의 FSM을 라이브와 동일하게 1스텝 진행
            transitions: dict[str, tuple[StateTransition, IndicatorSnapshot]] = {}
            for symbol in panels:
                bar_i = didx[symbol].get(d)
                if bar_i is None or bar_i == 0:  # 당일 바 없음 또는 prev 없음
                    continue
                current = rows[symbol][bar_i]
                prev = rows[symbol][bar_i - 1]
                st = fsm.get(symbol)
                if st is None:
                    st = _SymbolFSM(state=sm.get_initial_state(current).value)
                    fsm[symbol] = st
                transition = sm.process(
                    current=current,
                    prev=prev,
                    current_state=SymbolState(st.state),
                    gc_date=st.gc_date,
                    pullback_date=st.pullback_date,
                    entry_price=st.entry_price,
                    entry_date=st.entry_date,
                    highest_price=st.highest_price,
                    trailing_stop_activated=st.trailing,
                )
                # 엔진 6-1 미러: 진입 전 상태가 IN_POSITION이면 최고가/트레일링 갱신
                if st.state == SymbolState.IN_POSITION.value:
                    if st.highest_price is None or current.close > st.highest_price:
                        st.highest_price = current.close
                    if st.entry_price and st.entry_price > 0:
                        pnl = float((current.close - st.entry_price) / st.entry_price)
                        if pnl >= risk.trailing_stop_activation and not st.trailing:
                            st.trailing = True
                transitions[symbol] = (transition, current)

            # ── Phase B: 청산(SELL) 먼저 — 보유 종목의 매도로 현금 확보
            for symbol in list(positions.keys()):
                tr_pair = transitions.get(symbol)
                if tr_pair is None:
                    continue  # 당일 바 없음 → 보유 유지
                transition, current = tr_pair
                st = fsm[symbol]
                if transition.signal == Signal.SELL:
                    pos = positions[symbol]
                    exit_reason = _EXIT_REASON_MAP.get(transition.reason or "", "signal")
                    completed, net = order_manager.execute_sell_order(
                        trade=pos.trade, price=current.close, date=exec_dt, exit_reason=exit_reason
                    )
                    cash += net
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
                    del positions[symbol]
                    st.reset_to_waiting()
                else:  # IN_POSITION HOLD: 상태만 유지
                    st.state = transition.new_state.value

            # ── Phase C: 미보유 종목의 상태 전이(HOLD 진행) + 매수 후보 수집
            candidates: list[tuple[str, StateTransition, IndicatorSnapshot]] = []
            for symbol in panels:
                if symbol in positions:
                    continue
                tr_pair = transitions.get(symbol)
                if tr_pair is None:
                    continue
                transition, current = tr_pair
                st = fsm[symbol]
                if transition.signal == Signal.BUY:
                    candidates.append((symbol, transition, current))
                else:  # HOLD: WAITING/PULLBACK/READY 진행
                    st.state = transition.new_state.value
                    st.gc_date = transition.gc_date
                    st.pullback_date = transition.pullback_date

            # 회복 강도 우선(강한 회복 먼저), 그다음 심볼코드
            candidates.sort(key=lambda c: (_BUY_REASON_PRIORITY.get(c[1].reason or "", 9), c[0]))

            # ── Phase D: 진입 — 체결 결과를 FSM에 피드백(거부 시 라이브처럼 reset_to_waiting)
            for symbol, transition, current in candidates:
                st = fsm[symbol]
                price = current.close
                qty = 0
                reject_reason: str | None = None
                if len(positions) >= max_pos:
                    reject_reason = "max_positions"
                elif price <= 0:  # current.close는 Decimal — 불량 데이터(<=0)만 방어
                    reject_reason = "invalid_price"
                else:
                    qty = order_manager.calculate_position_size(cash, alloc, price)
                    if qty < 1 or not order_manager.can_afford(cash, price, qty):
                        reject_reason = "insufficient_cash"
                    else:
                        sector = self.constraints.sector_of(symbol)
                        if max_sector < 1.0:
                            # 시장가치 노출 기준 캡: (섹터 시가 + 신규 시가) / 총자산.
                            # 체결 수수료/세금 드래그(<0.1%)는 다음 MTM에서 자동 반영되며
                            # 캡(예: 30%)의 해상도 대비 무시 가능하므로 시가로 평가한다.
                            total_equity = cash + _positions_value(
                                positions, close_map, last_close, d
                            )
                            sector_value = _sector_value(
                                positions, close_map, last_close, d, sector, self.constraints
                            )
                            if total_equity > 0:
                                prospective = float((sector_value + price * qty) / total_equity)
                                if prospective > max_sector:
                                    reject_reason = "sector_cap"

                if reject_reason is not None:
                    rejected.append(RejectedEntry(d, symbol, reject_reason))
                    # 라이브: 매수 차단 시 reset_to_waiting → 새 골든크로스까지 재진입 대기
                    st.reset_to_waiting()
                    continue

                trade, total_cost = order_manager.execute_buy_order(
                    symbol=symbol, price=price, quantity=qty, date=exec_dt
                )
                if cash < total_cost:
                    rejected.append(RejectedEntry(d, symbol, "insufficient_cash"))
                    st.reset_to_waiting()
                    continue
                cash -= total_cost
                positions[symbol] = _OpenPosition(
                    symbol, self.constraints.sector_of(symbol), qty, trade
                )
                trades.append(trade)
                entered_positions += 1
                # 체결 성공 → IN_POSITION 확정(라이브 _update_state_after_signal)
                st.state = SymbolState.IN_POSITION.value
                st.entry_price = current.close
                st.entry_date = current.timestamp
                st.highest_price = None
                st.trailing = False
                st.gc_date = None
                st.pullback_date = None

            # ── Phase E: 일별 시가평가
            pos_value = _positions_value(positions, close_map, last_close, d)
            equity = cash + pos_value
            equity_curve.append(equity)
            max_concurrent = max(max_concurrent, len(positions))
            if equity > 0 and positions:
                sector_exp = _max_sector_exposure(
                    positions, close_map, last_close, d, equity, self.constraints
                )
                max_sector_exposure = max(max_sector_exposure, sector_exp)

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
                    date=exec_dt,
                    equity=equity,
                    cash=cash,
                    position_value=pos_value,
                    daily_return=daily_return,
                    cumulative_return=cumulative_return,
                    drawdown=drawdown,
                )
            )

        # active_from 사용 시 성과 창은 실제 집계된 첫/마지막 날 기준
        start_date = daily_stats[0].date if daily_stats else dt_map[calendar[0]]
        end_date = daily_stats[-1].date if daily_stats else dt_map[calendar[-1]]
        result = build_backtest_result(
            symbol="PORTFOLIO",
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            execution_timing="same_close",
            equity_curve=equity_curve,
            daily_stats=daily_stats,
            trades=trades,
            completed_trades=completed_trades,
        )
        return PortfolioRunResult(
            result=result,
            entered_positions=entered_positions,
            rejected=rejected,
            max_sector_exposure=round(max_sector_exposure, 4),
            max_concurrent_positions=max_concurrent,
        )


# ==================== 헬퍼 ====================


def _price_at(
    symbol: str,
    close_map: dict[str, dict[date, Decimal]],
    last_close: dict[str, Decimal],
    d: date,
) -> Decimal | None:
    return close_map.get(symbol, {}).get(d, last_close.get(symbol))


def _positions_value(
    positions: dict[str, _OpenPosition],
    close_map: dict[str, dict[date, Decimal]],
    last_close: dict[str, Decimal],
    d: date,
) -> Decimal:
    total = Decimal("0")
    for symbol, pos in positions.items():
        price = _price_at(symbol, close_map, last_close, d)
        if price is not None:
            total += price * pos.quantity
    return total


def _sector_value(
    positions: dict[str, _OpenPosition],
    close_map: dict[str, dict[date, Decimal]],
    last_close: dict[str, Decimal],
    d: date,
    sector: str,
    constraints: PortfolioConstraints,
) -> Decimal:
    total = Decimal("0")
    for symbol, pos in positions.items():
        if pos.sector != sector:
            continue
        price = _price_at(symbol, close_map, last_close, d)
        if price is not None:
            total += price * pos.quantity
    return total


def _max_sector_exposure(
    positions: dict[str, _OpenPosition],
    close_map: dict[str, dict[date, Decimal]],
    last_close: dict[str, Decimal],
    d: date,
    equity: Decimal,
    constraints: PortfolioConstraints,
) -> float:
    by_sector: dict[str, Decimal] = {}
    for symbol, pos in positions.items():
        price = _price_at(symbol, close_map, last_close, d)
        if price is None:
            continue
        by_sector[pos.sector] = by_sector.get(pos.sector, Decimal("0")) + price * pos.quantity
    if not by_sector or equity <= 0:
        return 0.0
    return float(max(by_sector.values()) / equity)
