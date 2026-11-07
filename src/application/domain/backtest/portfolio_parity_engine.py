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
from src.application.domain.backtest.cash_interest import CashInterestSchedule
from src.application.domain.backtest.dto import (
    BacktestConfigDTO,
    BacktestResultDTO,
    DailyStatsDTO,
    TradeDTO,
)
from src.application.domain.backtest.entry_guard import EntryGuardConfig, EntryGuardDay, check_entry
from src.application.domain.backtest.exit_overlay import OVERLAY_TRADE_EXIT_REASON, ExitOverlay
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
class PortfolioExecutionOptions:
    """연구용 체결/사이징/현금 모델 옵션(opt-in). 기본값 = 기존 엔진 동작과 동일.

    - fill_timing: "same_close"(기본, 시그널 바 종가 체결) | "next_open"(종가 t 시그널 →
      t+1 시가 체결, 갭 리스크 포함). next_open에서 시가가 결측/0이면 그날 종가로 대체하고
      `open_fallbacks`로 집계한다.
    - sizing_mode: "cash_ratio"(기본, 잔여현금 × allocation_ratio — 라이브 정합) |
      "equal_weight_equity"(총자산 / max_positions, 잔여현금 한도).
    - cash_interest: 미투자 현금 이자 스케줄(None=0%, 기본).
    - liquidate_at_end: 마지막 바 보유분을 순청산가(슬리피지·수수료·세금 차감)로 평가.
    - exit_overlay: 가격 기반 추가 청산 규칙(H5). None=미적용(기본).
    """

    fill_timing: str = "same_close"
    sizing_mode: str = "cash_ratio"
    cash_interest: CashInterestSchedule | None = None
    liquidate_at_end: bool = False
    exit_overlay: ExitOverlay | None = None
    # SafetyGuard 재현(신규 진입만 차단). same_close 전용. None=미적용(기본, 라이브 현행=무효 가드와 동일)
    entry_guard: EntryGuardConfig | None = None

    def __post_init__(self) -> None:
        if self.fill_timing not in ("same_close", "next_open"):
            raise ValueError(f"unsupported fill_timing: {self.fill_timing}")
        if self.sizing_mode not in ("cash_ratio", "equal_weight_equity"):
            raise ValueError(f"unsupported sizing_mode: {self.sizing_mode}")
        if self.entry_guard is not None and self.fill_timing != "same_close":
            raise ValueError("entry_guard supports fill_timing='same_close' only")

    @property
    def is_default(self) -> bool:
        return self == PortfolioExecutionOptions()

    def describe(self) -> str:
        parts = [self.fill_timing, self.sizing_mode]
        if self.cash_interest is not None:
            parts.append(f"interest={self.cash_interest.label}")
        if self.liquidate_at_end:
            parts.append("liquidate_at_end")
        if self.exit_overlay is not None:
            parts.append(f"overlay={self.exit_overlay.describe()}")
        if self.entry_guard is not None:
            parts.append(self.entry_guard.describe())
        return ",".join(parts)


@dataclass(frozen=True, slots=True)
class PortfolioRunResult:
    result: BacktestResultDTO  # symbol="PORTFOLIO" 성과 집계
    entered_positions: int
    rejected: list[RejectedEntry]
    max_sector_exposure: float  # 시뮬 전체에서 관측된 최대 단일 섹터 비중
    max_concurrent_positions: int
    # ── 연구 옵션 진단(기본 실행에서는 0/빈 값) ──
    overlay_exits: dict[str, int] = field(default_factory=dict)
    open_fallbacks: int = 0
    interest_earned: Decimal = Decimal("0")
    end_liquidation_cost: Decimal = Decimal("0")
    guard_blocks: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class _PendingBuy:
    symbol: str
    reason: str | None
    signal_date: date


class PortfolioParityEngine:
    """parity 시그널 기반 일별 시가평가 공유 현금북 포트폴리오 엔진."""

    def __init__(
        self,
        config: GoldenCrossConfigDTO | None = None,
        constraints: PortfolioConstraints | None = None,
        execution: PortfolioExecutionOptions | None = None,
    ) -> None:
        self.config = config or GoldenCrossConfigDTO()
        self.constraints = constraints or PortfolioConstraints()
        self.execution = execution or PortfolioExecutionOptions()
        self.replay = GoldenCrossParityReplay(self.config)

    def run(
        self,
        panels: dict[str, pd.DataFrame],
        backtest_config: BacktestConfigDTO | None = None,
        active_from: date | None = None,
        entry_allowed_dates: set[date] | None = None,
    ) -> PortfolioRunResult:
        """포트폴리오 백테스트 실행.

        Args:
            active_from: 지정 시 이 날짜 이전은 지표/FSM 워밍업에만 사용하고,
                포지션 진입·성과 집계는 이 날짜부터 시작한다(walk-forward fold의
                독립 OOS 측정용). 시그널 스케줄은 전체 슬라이스로 계산되므로
                active_from 시점 FSM 상태가 올바르게 반영된다.
            entry_allowed_dates: 지정 시 이 집합에 없는 거래일에는 **신규 진입을
                차단**한다(시장 국면 필터, regime_block). 청산은 막지 않는다.
                None이면 게이트 미적용(전량 허용, 기존 동작).
        """
        backtest_config = backtest_config or BacktestConfigDTO()
        if not panels:
            raise ValueError("empty panels for portfolio backtest")

        ex = self.execution
        next_open = ex.fill_timing == "next_open"
        sm = GoldenCrossStateMachine(self.config)
        risk = self.config.risk_config

        # 1) 심볼별 지표/스냅샷/종가 사전계산(실주문과 동일 지표)
        rows: dict[str, list[IndicatorSnapshot]] = {}
        didx: dict[str, dict[date, int]] = {}
        close_map: dict[str, dict[date, Decimal]] = {}
        open_map: dict[str, dict[date, Decimal]] = {}
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
            if next_open and "open" in prepared.columns:
                omap: dict[date, Decimal] = {}
                for i, o in enumerate(prepared["open"].tolist()):
                    if o == o and o is not None and float(o) > 0:  # NaN/0 제외
                        omap[srows[i].timestamp.date()] = Decimal(str(o))
                open_map[symbol] = omap

        calendar = sorted(all_dates)
        last_day = calendar[-1]

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
        # 연구 옵션 상태
        pending_sells: dict[str, str] = {}  # symbol -> exit_reason
        pending_buys: list[_PendingBuy] = []
        overlay_exits: dict[str, int] = {}
        open_fallbacks = 0
        interest_earned = Decimal("0")
        end_liquidation_cost = Decimal("0")
        prev_active_day: date | None = None

        guard_blocks: dict[str, int] = {}
        day_losses = {"streak": 0}

        def _close_position(symbol: str, price: Decimal, exec_dt: datetime, reason: str) -> None:
            nonlocal cash
            pos = positions[symbol]
            completed, net = order_manager.execute_sell_order(
                trade=pos.trade, price=price, date=exec_dt, exit_reason=reason
            )
            cash += net
            # 당일 연속 손실 청산 수(SafetyGuard TradingDayStats와 같은 일 단위)
            day_losses["streak"] = day_losses["streak"] + 1 if completed.profit < 0 else 0
            completed_trades.append(
                {
                    "profit_rate": completed.profit_rate,
                    "holding_days": completed.holding_days,
                    "profit": completed.profit,
                }
            )
            for idx, t in enumerate(trades):
                if t.trade_id == completed.trade_id:
                    trades[idx] = completed
                    break
            del positions[symbol]

        def _size(price: Decimal, mark: dict[str, Decimal], d: date) -> int:
            if ex.sizing_mode == "equal_weight_equity":
                total_equity = cash + _positions_value(positions, close_map, mark, d)
                target = min(cash, total_equity / Decimal(max_pos))
                if target <= 0:
                    return 0
                return order_manager.calculate_position_size(target, 1.0, price)
            return order_manager.calculate_position_size(cash, alloc, price)

        def _sector_reject(
            symbol: str, price: Decimal, qty: int, mark: dict[str, Decimal], d: date
        ) -> bool:
            if max_sector >= 1.0:
                return False
            sector = self.constraints.sector_of(symbol)
            # 시장가치 노출 기준 캡: (섹터 시가 + 신규 시가) / 총자산.
            # 체결 수수료/세금 드래그(<0.1%)는 다음 MTM에서 자동 반영되며
            # 캡(예: 30%)의 해상도 대비 무시 가능하므로 시가로 평가한다.
            total_equity = cash + _positions_value(positions, close_map, mark, d)
            sector_value = _sector_value(positions, close_map, mark, d, sector, self.constraints)
            if total_equity > 0:
                prospective = float((sector_value + price * qty) / total_equity)
                if prospective > max_sector:
                    return True
            return False

        for d in calendar:
            exec_dt = dt_map[d]
            day_losses["streak"] = 0
            in_active = active_from is None or d >= active_from

            # ── Phase 0 (next_open 전용): 전일 종가 시그널을 당일 시가로 체결.
            # last_close 갱신 전이므로 사이징/섹터 평가는 전일 종가 기준(미래 참조 없음).
            if next_open and in_active and (pending_sells or pending_buys):
                for symbol in list(pending_sells.keys()):
                    if symbol not in positions:
                        del pending_sells[symbol]
                        continue
                    bar_i = didx[symbol].get(d)
                    if bar_i is None:
                        continue  # 당일 바 없음 → 다음 바까지 대기
                    price = open_map.get(symbol, {}).get(d)
                    if price is None:
                        price = rows[symbol][bar_i].close
                        open_fallbacks += 1
                    _close_position(symbol, price, rows[symbol][bar_i].timestamp, pending_sells[symbol])
                    del pending_sells[symbol]
                still_pending: list[_PendingBuy] = []
                for pb in pending_buys:
                    symbol = pb.symbol
                    bar_i = didx[symbol].get(d)
                    if bar_i is None:
                        still_pending.append(pb)
                        continue
                    st = fsm[symbol]
                    price = open_map.get(symbol, {}).get(d)
                    if price is None:
                        price = rows[symbol][bar_i].close
                        open_fallbacks += 1
                    reject_reason: str | None = None
                    qty = 0
                    if len(positions) >= max_pos:
                        reject_reason = "max_positions"
                    elif price <= 0:
                        reject_reason = "invalid_price"
                    else:
                        # date.min: close_map 조회를 비켜 전일 종가(last_close)로만 평가
                        qty = _size(price, last_close, date.min)
                        if qty < 1 or not order_manager.can_afford(cash, price, qty):
                            reject_reason = "insufficient_cash"
                        elif _sector_reject(symbol, price, qty, last_close, date.min):
                            reject_reason = "sector_cap"
                    if reject_reason is None:
                        fill_dt = rows[symbol][bar_i].timestamp
                        trade, total_cost = order_manager.execute_buy_order(
                            symbol=symbol, price=price, quantity=qty, date=fill_dt
                        )
                        if cash < total_cost:
                            reject_reason = "insufficient_cash"
                    if reject_reason is not None:
                        rejected.append(RejectedEntry(d, symbol, reject_reason))
                        st.reset_to_waiting()
                        continue
                    cash -= total_cost
                    positions[symbol] = _OpenPosition(
                        symbol, self.constraints.sector_of(symbol), qty, trade
                    )
                    trades.append(trade)
                    entered_positions += 1
                    st.state = SymbolState.IN_POSITION.value
                    st.entry_price = price  # 체결 기준 시가(슬리피지 전) — same_close의 종가와 대칭
                    st.entry_date = fill_dt
                    st.highest_price = None
                    st.trailing = False
                    st.gc_date = None
                    st.pullback_date = None
                pending_buys = still_pending

            for symbol, cmap in close_map.items():
                if d in cmap:
                    last_close[symbol] = cmap[d]

            # 워밍업 구간(active_from 이전): FSM은 active_from에서 get_initial_state로
            # 플랫 초기화(지표는 lookback으로 유효). 이전 구간은 진입/집계 없이 건너뜀.
            if not in_active:
                continue

            # ── 현금 이자(opt-in): 직전 활성일 이후 달력일 복리
            if ex.cash_interest is not None and prev_active_day is not None and cash > 0:
                accrued = cash * ex.cash_interest.accrual_factor(prev_active_day, d)
                cash += accrued
                interest_earned += accrued
            prev_active_day = d

            # ── Phase A: 당일 바가 있는 심볼의 FSM을 라이브와 동일하게 1스텝 진행
            transitions: dict[str, tuple[StateTransition, IndicatorSnapshot]] = {}
            pending_buy_symbols = {pb.symbol for pb in pending_buys}
            for symbol in panels:
                bar_i = didx[symbol].get(d)
                if bar_i is None or bar_i == 0:  # 당일 바 없음 또는 prev 없음
                    continue
                if symbol in pending_buy_symbols:
                    continue  # next_open 체결 대기 중(이론상 바가 있으면 이미 체결됨)
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
                if symbol in pending_sells:
                    continue  # next_open 매도 대기(FSM은 이미 리셋됨)
                transition, current = tr_pair
                st = fsm[symbol]
                exit_reason: str | None = None
                if transition.signal == Signal.SELL:
                    exit_reason = _EXIT_REASON_MAP.get(transition.reason or "", "signal")
                elif ex.exit_overlay is not None:
                    bar_i = didx[symbol][d]
                    lb = ex.exit_overlay.breakdown_lookback
                    recent = [r.close for r in rows[symbol][max(0, bar_i - lb + 1) : bar_i + 1]]
                    overlay_reason = ex.exit_overlay.check(
                        close=current.close,
                        entry_price=st.entry_price,
                        highest_price=st.highest_price,
                        ma_long=current.ma_long if current.ma_long > 0 else None,
                        recent_closes=recent,
                    )
                    if overlay_reason is not None:
                        overlay_exits[overlay_reason] = overlay_exits.get(overlay_reason, 0) + 1
                        exit_reason = OVERLAY_TRADE_EXIT_REASON[overlay_reason]
                if exit_reason is not None:
                    if next_open:
                        pending_sells[symbol] = exit_reason
                    else:
                        _close_position(symbol, current.close, exec_dt, exit_reason)
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
            entries_today = 0
            for symbol, transition, current in candidates:
                st = fsm[symbol]
                price = current.close
                qty = 0
                reject_reason = None
                guard_reason = None
                if ex.entry_guard is not None:
                    equity_now = float(cash + _positions_value(positions, close_map, last_close, d))
                    guard_reason = check_entry(
                        ex.entry_guard,
                        EntryGuardDay(
                            day=d,
                            equity_now=equity_now,
                            equity_history=[float(e) for e in equity_curve[-21:]],
                            entries_today=entries_today,
                            consecutive_losses_today=day_losses["streak"],
                        ),
                    )
                if entry_allowed_dates is not None and d not in entry_allowed_dates:
                    # 시장 국면 필터: 하락/횡보장 신규 진입 차단(라이브 regime 게이트 정합)
                    reject_reason = "regime_block"
                elif guard_reason is not None:
                    reject_reason = guard_reason
                    guard_blocks[guard_reason] = guard_blocks.get(guard_reason, 0) + 1
                elif next_open:
                    # 시그널 시점 슬롯 예약: (보유 − 매도대기 + 매수대기) < max
                    committed = len(positions) - len(pending_sells) + len(pending_buys)
                    if committed >= max_pos:
                        reject_reason = "max_positions"
                    else:
                        pending_buys.append(_PendingBuy(symbol, transition.reason, d))
                        continue  # 체결/사이징은 다음 바 시가에서
                elif len(positions) >= max_pos:
                    reject_reason = "max_positions"
                elif price <= 0:  # current.close는 Decimal — 불량 데이터(<=0)만 방어
                    reject_reason = "invalid_price"
                else:
                    qty = _size(price, last_close, d)
                    if qty < 1 or not order_manager.can_afford(cash, price, qty):
                        reject_reason = "insufficient_cash"
                    elif _sector_reject(symbol, price, qty, last_close, d):
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
                entries_today += 1
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
            if ex.liquidate_at_end and d == last_day and positions:
                # 마지막 바: 보유분을 순청산가(슬리피지·수수료·세금 차감)로 평가
                liq_value = Decimal("0")
                for symbol, pos in positions.items():
                    px = _price_at(symbol, close_map, last_close, d)
                    if px is not None:
                        liq_value += order_manager.liquidation_value(
                            symbol, px, pos.quantity, exec_dt
                        )
                end_liquidation_cost = pos_value - liq_value
                pos_value = liq_value
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
            execution_timing="next_open" if next_open else "same_close",
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
            overlay_exits=overlay_exits,
            open_fallbacks=open_fallbacks,
            interest_earned=interest_earned,
            end_liquidation_cost=end_liquidation_cost,
            guard_blocks=guard_blocks,
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
