import asyncio
from datetime import datetime
from decimal import Decimal

from scripts.common.data_generator import MarketScenario, SyntheticMarket
from src.application.domain.backtest.engine import BacktestEngine
from src.application.domain.backtest.dto import BacktestConfigDTO
from src.application.domain.strategy.dto import (
    StrategyConfigDTO,
    BollingerBandConfig,
    EnvelopeConfig,
    PositionConfig,
    RiskManagementConfig,
)


# 1. Stock Selection Logic
class StockSelector:
    """
    합성 시장(SyntheticMarket)의 종목 메타데이터를 기준으로 스크리닝하고,
    각 판정 사유를 콘솔에 출력한다.
    """

    def __init__(self, market: SyntheticMarket):
        self.market = market

    def filter_stocks(self, criteria: dict) -> list[str]:
        """
        criteria: dict
          - min_volume
          - min_volatility
          - max_debt_ratio
          - max_per
        """
        selected = []

        print("\n🔍 Screening Stocks based on Criteria:")
        print(f"   - Min Volume: {criteria.get('min_volume', 0):,}")
        print(f"   - Min Volatility (Daily): {criteria.get('min_volatility', 0)*100:.2f}%")
        print(f"   - Max Debt Ratio: {criteria.get('max_debt_ratio', 999)}%")
        print(f"   - Max PER: {criteria.get('max_per', 999)}")
        print("-" * 60)

        for symbol, meta in self.market.stocks.items():
            # 1. Volume Check
            if meta.avg_volume < criteria.get("min_volume", 0):
                print(f"   ❌ {symbol} ({meta.name}): Volume too low ({meta.avg_volume:,})")
                continue

            # 2. Financial Check
            if meta.debt_ratio > criteria.get("max_debt_ratio", 9999):
                print(f"   ❌ {symbol} ({meta.name}): High Debt ({meta.debt_ratio}%)")
                continue

            if meta.per > criteria.get("max_per", 9999):
                print(f"   ❌ {symbol} ({meta.name}): Overvalued (PER {meta.per})")
                continue

            # 3. Volatility Check (설정된 시나리오 변동성 기준)
            if meta.volatility < criteria.get("min_volatility", 0):
                print(f"   ❌ {symbol} ({meta.name}): Low Volatility ({meta.volatility*100:.2f}%)")
                continue

            print(f"   ✅ {symbol} ({meta.name}): Passed Selection")
            selected.append(symbol)

        return selected


# 2. Main Execution
async def main():
    print("=" * 80)
    print("🚀 Stock Selection & Strategy Optimization")
    print("=" * 80)

    start_date = datetime(2023, 1, 1)
    periods = 365

    # Initialize Market with diverse stocks (합성 데이터 생성은 scripts/common/data_generator 사용)
    market = SyntheticMarket()

    def add(symbol, name, start_price, volatility, trend, avg_volume, debt_ratio, per):
        scenario = MarketScenario(
            name=symbol,
            trend=trend,
            volatility=volatility,
            start_price=start_price,
            periods=periods,
            avg_volume=avg_volume,
        )
        market.add_stock(
            symbol,
            name,
            scenario=scenario,
            avg_volume=avg_volume,
            volatility=volatility,
            debt_ratio=debt_ratio,
            per=per,
        )

    # Stock A: The Ideal Candidate (High Vol, Good Fin, High Vol)
    add("005930", "Samsung Elec (Sim)", 70000, 0.02, 0.0005, 10000000, 30.0, 15.0)

    # Stock B: Low Volatility (Stable)
    add("000660", "SK Hynix (Sim)", 120000, 0.005, 0.0002, 5000000, 40.0, 12.0)

    # Stock C: Bad Financials (High Debt)
    add("035720", "Kakao (Sim)", 50000, 0.025, -0.0005, 2000000, 150.0, 50.0)

    # Stock D: Low Volume
    add("005380", "Hyundai Motor (Sim)", 200000, 0.015, 0.0003, 100000, 80.0, 8.0)

    # Stock E: High Volatility, Good Financials (Another Candidate)
    add("035420", "Naver (Sim)", 200000, 0.022, 0.0004, 1500000, 45.0, 25.0)

    # Generate Data for all (이미 add_stock 시점에 scenario 캐시됨)
    data_map = market.generate_all(start_date=start_date, periods=periods)

    # Perform Selection
    selector = StockSelector(market)
    selected_symbols = selector.filter_stocks({
        "min_volume": 500000,        # Min 500k avg daily volume
        "min_volatility": 0.015,     # Min 1.5% daily volatility
        "max_debt_ratio": 100.0,     # Max 100% debt ratio
        "max_per": 40.0,             # Max PER 40
    })

    print(f"\n🎯 Selected Stocks: {', '.join(selected_symbols)}")

    # Backtest Configuration (Using 'Strategy F' - Trailing Stop Focus)
    print("\n" + "=" * 80)
    print("🧪 Running Backtest on Selected Stocks")
    print("   Strategy: Bollinger Band + Envelope (Trailing Stop Focus)")
    print("=" * 80)

    strategy_config = StrategyConfigDTO(
        bollinger_band=BollingerBandConfig(period=20, std_multiplier=2.0),
        envelope=EnvelopeConfig(period=20, percentage=2.0),
        position=PositionConfig(allocation_ratio=0.2, max_position_count=1),  # Increased allocation
        risk_management=RiskManagementConfig(
            use_stop_loss=True,
            stop_loss_ratio=-0.05,
            use_take_profit=False,     # Let profits run
            use_trailing_stop=True,    # Use trailing stop
            trailing_stop_ratio=0.03,  # 3% trailing
            use_reverse_signal_exit=True,
        ),
    )

    backtest_config = BacktestConfigDTO(
        initial_capital=Decimal("10000000"),
        use_commission=True,
        use_tax=True,
        use_slippage=True,
    )

    results = {}
    for symbol in selected_symbols:
        df = data_map[symbol]
        engine = BacktestEngine(symbol, strategy_config, backtest_config)

        result = await engine.run(
            df,
            df["timestamp"].iloc[0],
            df["timestamp"].iloc[-1],
        )
        results[symbol] = result

    # Print Results
    print(f"\n{'Symbol':^10} {'Return':>10} {'Win Rate':>10} {'Sharpe':>10} {'MDD':>10} {'Trades':>8}")
    print("-" * 70)

    for symbol, res in results.items():
        print(
            f"{symbol:^10} "
            f"{res.total_return:>9.2f}% "
            f"{res.win_rate:>9.1f}% "
            f"{res.sharpe_ratio:>10.2f} "
            f"{res.mdd:>9.2f}% "
            f"{res.total_trades:>8}"
        )

    print("\n✅ Optimization Complete.")
    print("   These stocks met the criteria for Volume, Volatility, and Financial Health.")
    print("   The backtest demonstrates performance using the optimized 'Trailing Stop' strategy.")


if __name__ == "__main__":
    asyncio.run(main())
