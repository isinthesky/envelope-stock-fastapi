"""examples/backtest/golden_cross_backtest.py 비용·회계 회귀 테스트(2026-11-08).

- 국내 ETF 매도세 면제(도메인 BacktestOrderManager.is_tax_exempt와 동일)
- 거래 손익에 매수 비용 포함, 수익률은 비용 반영
"""

from datetime import datetime
from decimal import Decimal

from examples.backtest.golden_cross_backtest import (
    BacktestConfig,
    GoldenCrossBacktester,
    GoldenCrossConfig,
    Trade,
)


def _tester(exempt: list[str]) -> GoldenCrossBacktester:
    return GoldenCrossBacktester(
        GoldenCrossConfig(),
        BacktestConfig(
            tax_rate=0.002, commission_rate=0.0, slippage_rate=0.0, tax_exempt_symbols=exempt
        ),
    )


def _sell(tester: GoldenCrossBacktester, symbol: str) -> tuple[Decimal, Trade]:
    trade = Trade(
        trade_id=1, entry_date=datetime(2026, 1, 2), entry_price=Decimal("100"), quantity=10
    )
    return tester._execute_sell(
        Decimal("0"),
        Decimal("110"),
        10,
        Decimal("100"),
        datetime(2026, 1, 2),
        datetime(2026, 2, 2),
        trade,
        "take_profit",
        entry_cost=Decimal("1001"),  # 체결 1000 + 매수 수수료·슬리피지 1
        symbol=symbol,
    )


def test_etf_sell_is_tax_exempt_and_stock_is_taxed() -> None:
    tester = _tester(exempt=["069500"])
    cash_etf, _ = _sell(tester, "069500")
    cash_stock, _ = _sell(tester, "005930")
    assert cash_etf == Decimal("1100")  # 면세
    assert cash_stock == Decimal("1100") - Decimal("1100") * Decimal("0.002")


def test_trade_pnl_includes_buy_costs() -> None:
    _, trade = _sell(_tester(exempt=["069500"]), "069500")
    assert trade.profit_loss == Decimal("99")  # 1100 − 1001
    assert abs(trade.profit_rate - 99 / 1001 * 100) < 1e-9


def test_final_capital_equals_initial_plus_trade_pnl_after_end_liquidation() -> None:
    import asyncio

    from tests.test_walk_forward import _walk_panel

    df = _walk_panel(seed=3, n=520)
    tester = GoldenCrossBacktester(
        GoldenCrossConfig(short_ma_period=5, long_ma_period=20, stoch_oversold=60.0),
        BacktestConfig(tax_exempt_symbols=[]),
    )
    result = asyncio.run(
        tester.run(
            "005930",
            "test",
            df,
            df["timestamp"].iloc[0].to_pydatetime(),
            df["timestamp"].iloc[-1].to_pydatetime(),
        )
    )
    assert result.total_trades > 0
    pnl = sum((t.profit_loss for t in result.trades), Decimal("0"))
    # 회계 정합: 기간말 청산까지 반영한 최종 자본 − 초기 자본 == 완료 거래 순손익 합
    assert abs((result.final_capital - result.initial_capital) - pnl) < Decimal("0.01")


def test_example_allows_small_capital() -> None:
    GoldenCrossBacktester(GoldenCrossConfig(), BacktestConfig(initial_capital=Decimal("10000")))
