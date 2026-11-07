# -*- coding: utf-8 -*-
"""백테스트/성과지표 버그 수정 회귀 테스트 (2026-11).

1 부분익절 lot 단위 플래그 → 포지션 단위 tranche
2 리스크 청산 후 재진입 재무장(라이브 FSM WAITING_FOR_GC 정합)
3 Sortino 하방편차(전체 관측치)
4 Sharpe 일별 초과수익 정의 / DSR(rf0) 기준 일치
5 Profit Factor 금액 기준 / 실제 회복기간
7 DSR n_trials 명시 입력
8 포트폴리오 시뮬레이션 look-ahead 랭킹 제거 · 일별 MTM MDD · 청산비용
"""

import math
from datetime import datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from src.application.common.performance_metrics import PerformanceMetrics
from src.application.domain.backtest.dto import (
    BacktestConfigDTO,
    BacktestResultDTO,
    MultiSymbolBacktestResultDTO,
    TradeDTO,
)
from src.application.domain.backtest.engine import BacktestEngine
from src.application.domain.backtest.generators.golden_cross import GoldenCrossSignalGenerator
from src.application.domain.backtest.service import BacktestService
from src.application.domain.backtest.statistics import sharpe_stats
from src.application.domain.backtest.walk_forward_runner import (
    WalkForwardCandidate,
    WalkForwardRunner,
)
from src.application.domain.strategy.dto import GoldenCrossConfigDTO, StrategyConfigDTO

NO_COST = BacktestConfigDTO(use_commission=False, use_tax=False, use_slippage=False)
D0 = datetime(2025, 3, 3)


def _engine(trailing: bool = False) -> BacktestEngine:
    config = StrategyConfigDTO()
    if trailing:
        config.risk_management.use_trailing_stop = True
        config.risk_management.trailing_stop_ratio = 0.07
    return BacktestEngine(
        symbol="005930",
        strategy_config=config,
        backtest_config=NO_COST,
        strategy_params={"short_period": 2, "long_period": 3},
    )


# ==================== 1. 부분익절 ====================


@pytest.mark.asyncio
async def test_partial_take_profit_exits_only_first_tranche() -> None:
    engine = _engine()
    await engine._execute_buy(D0, Decimal("100"))
    lots_before = engine.position_manager.get_positions("005930")
    assert len(lots_before) == 3

    await engine._check_risk_management(D0 + timedelta(days=1), Decimal("110"))

    remaining = engine.position_manager.get_positions("005930")
    # 이전 버그: lot 단위 플래그라 3개 lot이 모두 +10%에 같은 날 청산되었다.
    assert len(remaining) == 2
    exits = [t for t in engine.trades if t.exit_reason is not None]
    assert [t.exit_reason for t in exits] == ["partial_take_profit_1"]
    assert exits[0].trade_id == lots_before[0].trade_id

    # 같은 수익률 재평가 시 추가 청산 없음
    await engine._check_risk_management(D0 + timedelta(days=2), Decimal("111"))
    assert len(engine.position_manager.get_positions("005930")) == 2


@pytest.mark.asyncio
async def test_second_tranche_then_runner_follows_trailing_stop() -> None:
    engine = _engine(trailing=True)
    await engine._execute_buy(D0, Decimal("100"))
    await engine._check_risk_management(D0 + timedelta(days=1), Decimal("110"))
    await engine._check_risk_management(D0 + timedelta(days=2), Decimal("117"))
    remaining = engine.position_manager.get_positions("005930")
    assert len(remaining) == 1  # 러너는 부분익절로 청산되지 않는다

    # 고점 갱신(+25%) 후 고점 대비 -7% 이상 하락 → 트레일링 청산
    engine.position_manager.update_positions({"005930": Decimal("125")})
    await engine._check_risk_management(D0 + timedelta(days=3), Decimal("125"))
    assert engine.position_manager.has_position("005930")
    await engine._check_risk_management(D0 + timedelta(days=4), Decimal("116"))
    assert not engine.position_manager.has_position("005930")
    reasons = [t.exit_reason for t in engine.trades]
    assert reasons == ["partial_take_profit_1", "partial_take_profit_2", "trailing_stop"]


@pytest.mark.asyncio
async def test_gap_through_both_thresholds_takes_both_tranches_once() -> None:
    engine = _engine()
    await engine._execute_buy(D0, Decimal("100"))
    await engine._check_risk_management(D0 + timedelta(days=1), Decimal("120"))
    assert len(engine.position_manager.get_positions("005930")) == 1


# ==================== 2. 재진입 재무장 ====================


def test_generator_blocks_reentry_until_fresh_cross_after_risk_exit() -> None:
    gen = GoldenCrossSignalGenerator(
        short_period=2, long_period=3, min_reentry_cooldown_bars=0, min_pullback_bars=0
    )
    gen.notify_exit()
    gen._oversold_seen = True
    gen._pullback_bars = 5
    # GC 활성(단기>장기) 상태가 이어지는 동안은 재진입 금지
    assert gen._should_buy(True, 60.0, 50.0) is False

    # 단기MA<=장기MA 관측 → 재무장
    gen.generate_signal(price_history=[10.0, 9.0, 8.0], current_price=Decimal("8"))
    assert gen._awaiting_fresh_cross is False


def test_generator_opt_out_keeps_legacy_reentry() -> None:
    gen = GoldenCrossSignalGenerator(
        min_reentry_cooldown_bars=0, min_pullback_bars=0, require_fresh_cross_after_exit=False
    )
    gen.notify_exit()
    gen._oversold_seen = True
    gen._pullback_bars = 5
    assert gen._should_buy(True, 60.0, 50.0) is True


@pytest.mark.asyncio
async def test_engine_risk_exit_notifies_generator() -> None:
    engine = _engine(trailing=True)
    await engine._execute_buy(D0, Decimal("100"))
    engine.position_manager.update_positions({"005930": Decimal("100")})
    # 고점 대비 -15% 손절(운영 고정 기준) → 전량 청산 + 재무장 대기
    engine.strategy_config.risk_management.use_stop_loss = True
    engine.strategy_config.risk_management.stop_loss_ratio = -0.15
    await engine._check_risk_management(D0 + timedelta(days=1), Decimal("84"))
    assert not engine.position_manager.has_position("005930")
    assert engine.signal_generator._awaiting_fresh_cross is True


# ==================== 3/4. Sortino · Sharpe ====================


def _equity_from_returns(returns: list[float]) -> pd.DataFrame:
    eq = [100.0]
    for r in returns:
        eq.append(eq[-1] * (1.0 + r))
    return pd.DataFrame({"timestamp": range(len(eq)), "equity": eq})


def test_sortino_uses_downside_deviation_over_all_observations() -> None:
    returns = [0.01, -0.02, 0.03, -0.01]
    df = _equity_from_returns(returns)
    r = np.asarray(returns)
    expected = r.mean() / math.sqrt(np.mean(np.minimum(r, 0.0) ** 2)) * math.sqrt(252)
    got = PerformanceMetrics.calculate_sortino_ratio(df, risk_free_rate=0.0)
    assert got == pytest.approx(expected, rel=1e-9)
    # 이전 구현(음수 수익만의 std)과 다르다
    legacy = (r.mean() * 252 * 100) / (np.std(r[r < 0], ddof=1) * math.sqrt(252) * 100)
    assert got != pytest.approx(legacy, rel=1e-3)


def test_daily_sharpe_rf0_matches_dsr_per_period_sharpe() -> None:
    rng = np.random.default_rng(7)
    returns = list(rng.normal(0.0005, 0.01, 300))
    df = _equity_from_returns(returns)
    sr_rf0 = PerformanceMetrics.calculate_daily_sharpe_ratio(df, risk_free_rate=0.0)
    assert sr_rf0 == pytest.approx(sharpe_stats(returns).sharpe * math.sqrt(252), rel=1e-6)


def test_daily_sharpe_subtracts_daily_compounded_risk_free() -> None:
    returns = [0.001, -0.0005, 0.0012, 0.0002, -0.0003]
    df = _equity_from_returns(returns)
    rf_d = 1.03 ** (1 / 252) - 1
    r = np.asarray(returns)
    expected = (r - rf_d).mean() / r.std(ddof=1) * math.sqrt(252)
    assert PerformanceMetrics.calculate_daily_sharpe_ratio(df, 3.0) == pytest.approx(expected)


# ==================== 5. Profit Factor · 회복기간 ====================


def test_profit_factor_is_money_based_when_profit_available() -> None:
    trades = [
        {"profit_rate": 10.0, "profit": Decimal("1000")},
        {"profit_rate": -5.0, "profit": Decimal("-2000")},
    ]
    assert PerformanceMetrics.calculate_profit_factor(trades) == pytest.approx(0.5)
    legacy = [{"profit_rate": 10.0}, {"profit_rate": -5.0}]
    assert PerformanceMetrics.calculate_profit_factor(legacy) == pytest.approx(2.0)


def test_recovery_days_is_trough_to_prior_peak_duration() -> None:
    curve = [Decimal(x) for x in (100, 120, 90, 100, 125, 110)]
    info = PerformanceMetrics.calculate_mdd(curve)
    assert info["valley_index"] == 2
    assert info["recovery_days"] == 2  # idx2(90) → idx4(125>=120)


def test_recovery_days_none_when_unrecovered() -> None:
    curve = [Decimal(x) for x in (100, 120, 90, 100, 110)]
    assert PerformanceMetrics.calculate_mdd(curve)["recovery_days"] is None


# ==================== 7. DSR n_trials ====================


def _runner(n_trials: int | None) -> WalkForwardRunner:
    cands = [
        WalkForwardCandidate("a", GoldenCrossConfigDTO()),
        WalkForwardCandidate("b", GoldenCrossConfigDTO()),
    ]
    return WalkForwardRunner(cands, n_trials=n_trials)


def test_dsr_uses_researcher_supplied_cumulative_trials() -> None:
    rng = np.random.default_rng(1)
    oos = list(rng.normal(0.0004, 0.01, 300))
    trial_sharpes = list(rng.normal(0.02, 0.02, 6))
    supplied = _runner(250)._overfitting_stats(oos, trial_sharpes, [[0.1, 0.2]] * 3, 6)
    default = _runner(None)._overfitting_stats(oos, trial_sharpes, [[0.1, 0.2]] * 3, 6)

    assert supplied["n_trials"] == 250
    assert supplied["n_trials_source"] == "researcher_supplied"
    assert default["n_trials"] == 6
    assert default["n_trials_source"] == "default_in_run_only"
    assert supplied["deflated_sharpe"] <= default["deflated_sharpe"]
    assert WalkForwardRunner._n_trials_warning(default)
    assert not WalkForwardRunner._n_trials_warning(supplied)


def test_supplied_trials_never_below_in_run_trials() -> None:
    stats = _runner(3)._overfitting_stats([0.01, -0.01, 0.02], [0.1, 0.2], [], 18)
    assert stats["n_trials"] == 18


# ==================== 8. 포트폴리오 시뮬레이션 ====================


def _trade(
    symbol: str,
    entry: datetime,
    exit_: datetime | None,
    entry_price: str,
    exit_price: str | None,
    trade_id: int = 1,
    quantity: int = 1,
) -> TradeDTO:
    return TradeDTO(
        trade_id=trade_id,
        symbol=symbol,
        trade_type="buy",
        entry_date=entry,
        entry_price=Decimal(entry_price),
        exit_date=exit_,
        exit_price=Decimal(exit_price) if exit_price else None,
        quantity=quantity,
    )


def _result(symbol: str, total_return: float, trades: list[TradeDTO]) -> BacktestResultDTO:
    return BacktestResultDTO(
        symbol=symbol,
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 1, 31),
        initial_capital=Decimal("1000000"),
        final_capital=Decimal("1000000"),
        execution_timing="same_close",
        total_return=total_return,
        annualized_return=0.0,
        cagr=0.0,
        mdd=0.0,
        volatility=0.0,
        sharpe_ratio=0.0,
        sortino_ratio=0.0,
        calmar_ratio=0.0,
        var_95=0.0,
        total_trades=len(trades),
        winning_trades=0,
        losing_trades=0,
        win_rate=0.0,
        profit_factor=0.0,
        avg_win=0.0,
        avg_loss=0.0,
        avg_win_loss_ratio=0.0,
        avg_holding_days=0.0,
        max_consecutive_wins=0,
        max_consecutive_losses=0,
        trades=trades,
    )


def _multi(*results: BacktestResultDTO) -> MultiSymbolBacktestResultDTO:
    return MultiSymbolBacktestResultDTO(
        results={r.symbol: r for r in results},
        total_count=len(results),
        success_count=len(results),
        failed_count=0,
    )


E, X = datetime(2024, 1, 2), datetime(2024, 1, 10)


def test_portfolio_ranking_does_not_use_full_period_return() -> None:
    service = BacktestService(market_data_service=None, db_session=None)
    multi = _multi(
        _result("AAA001", 5.0, [_trade("AAA001", E, X, "100", "105")]),
        _result("BBB002", 50.0, [_trade("BBB002", E, X, "100", "150")]),
    )
    portfolio = service.simulate_universe_portfolio(multi, Decimal("1000000"), 1)
    # 이전: 전체기간 수익률 내림차순(미래 정보) → BBB002 선택
    assert portfolio.trades[0].symbol == "AAA001"
    assert "total_return" not in portfolio.ranking_method


def test_portfolio_mdd_marks_to_market_daily() -> None:
    service = BacktestService(market_data_service=None, db_session=None)
    multi = _multi(_result("AAA001", 0.0, [_trade("AAA001", E, X, "100", "100")]))
    days = [E.date() + timedelta(days=i) for i in range(9)]
    closes = ["100", "90", "70", "80", "95", "100", "100", "100", "100"]
    prices = {"AAA001": {d: Decimal(c) for d, c in zip(days, closes)}}

    legacy = service.simulate_universe_portfolio(multi, Decimal("1000000"), 1, price_series={})
    mtm = service.simulate_universe_portfolio(multi, Decimal("1000000"), 1, price_series=prices)
    assert legacy.mdd == 0.0  # 원가 평가 → 장중 낙폭 미반영(과소추정)
    assert legacy.equity_valuation.startswith("event_cost_basis")
    assert mtm.equity_valuation == "daily_mark_to_market"
    assert mtm.mdd == pytest.approx(-30.0, abs=0.01)


def test_portfolio_applies_commission_and_tax_when_config_given() -> None:
    service = BacktestService(market_data_service=None, db_session=None)
    multi = _multi(_result("005930", 10.0, [_trade("005930", E, X, "100", "110")]))
    gross = service.simulate_universe_portfolio(multi, Decimal("1000000"), 1)
    net = service.simulate_universe_portfolio(
        multi,
        Decimal("1000000"),
        1,
        backtest_config=BacktestConfigDTO(cost_schedule_date=E.date(), tax_exempt_symbols=[]),
    )
    assert gross.total_return == pytest.approx(10.0)
    assert net.total_return < gross.total_return
    assert net.trades[0].profit < gross.trades[0].profit


def test_portfolio_liquidates_open_trade_at_final_bar() -> None:
    service = BacktestService(market_data_service=None, db_session=None)
    multi = _multi(_result("AAA001", 0.0, [_trade("AAA001", E, None, "100", None)]))
    days = [E.date() + timedelta(days=i) for i in range(5)]
    prices = {"AAA001": {d: Decimal("80") for d in days}}
    without_prices = service.simulate_universe_portfolio(
        multi, Decimal("1000000"), 1, price_series={}
    )
    with_prices = service.simulate_universe_portfolio(
        multi, Decimal("1000000"), 1, price_series=prices
    )
    assert without_prices.total_trades == 0  # 레거시: 미청산 손실 포지션 누락
    assert with_prices.total_trades == 1
    assert with_prices.total_return == pytest.approx(-20.0)


def test_portfolio_splits_position_across_engine_lots() -> None:
    service = BacktestService(market_data_service=None, db_session=None)
    lots = [
        _trade("AAA001", E, X, "100", "110", trade_id=1, quantity=5),
        _trade("AAA001", E, X + timedelta(days=5), "100", "90", trade_id=2, quantity=5),
    ]
    portfolio = service.simulate_universe_portfolio(
        _multi(_result("AAA001", 0.0, lots)), Decimal("1000000"), 1
    )
    assert portfolio.total_trades == 1
    assert portfolio.total_return == pytest.approx(0.0)  # +10% 절반, -10% 절반


# ==================== 8. 엔진 최종 바 청산비용 ====================


def _ohlcv(closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2025-01-02", periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1000] * len(closes),
        }
    )


@pytest.mark.asyncio
async def test_engine_final_equity_net_of_liquidation_costs() -> None:
    engine = BacktestEngine(
        symbol="005930",
        strategy_config=StrategyConfigDTO(),
        backtest_config=BacktestConfigDTO(execution_timing="same_close", tax_exempt_symbols=[]),
        strategy_params={"short_period": 2, "long_period": 3},
    )
    data = _ohlcv([100.0] * 5)
    engine._reset()
    await engine._execute_buy(datetime(2025, 1, 2), Decimal("100"))
    for _, row in data.iterrows():
        engine.last_bar_date = row["timestamp"].to_pydatetime()
        engine.last_bar_price = Decimal(str(row["close"]))
        value = engine.position_manager.update_positions({"005930": engine.last_bar_price})
        engine._update_daily_stats(engine.last_bar_date, value)
    gross_final = engine.equity_curve[-1]
    engine._apply_final_liquidation_mark()
    net_final = engine.equity_curve[-1]
    assert net_final < gross_final
    qty = engine.position_manager.get_total_quantity("005930")
    expected = engine.cash + engine.order_manager.liquidation_value(
        "005930", Decimal("100"), qty, engine.last_bar_date
    )
    assert net_final == expected
    assert engine.daily_stats[-1].equity == net_final
