import asyncio
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from decimal import Decimal
import random

from src.application.domain.backtest.engine import BacktestEngine
from src.application.domain.backtest.dto import BacktestConfigDTO
from src.application.domain.strategy.dto import (
    StrategyConfigDTO,
    BollingerBandConfig,
    EnvelopeConfig,
    PositionConfig,
    RiskManagementConfig,
)

def generate_synthetic_data(start_date, periods, trend=0.0002, volatility=0.015, seed=None):
    """
    Generates synthetic OHLCV data.
    trend: daily trend component
    volatility: daily volatility (standard deviation)
    """
    if seed is not None:
        np.random.seed(seed)
        random.seed(seed)

    dates = pd.date_range(start=start_date, periods=periods, freq="D")
    
    # Random Walk with Drift
    returns = np.random.normal(loc=trend, scale=volatility, size=periods)
    price_paths = 10000 * np.cumprod(1 + returns)
    
    # Generate OHLC
    opens = price_paths
    closes = price_paths * (1 + np.random.normal(0, 0.005, periods))
    highs = np.maximum(opens, closes) * (1 + np.abs(np.random.normal(0, 0.005, periods)))
    lows = np.minimum(opens, closes) * (1 - np.abs(np.random.normal(0, 0.005, periods)))
    volumes = np.random.randint(100000, 1000000, periods)

    df = pd.DataFrame({
        "timestamp": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes
    })
    
    return df

async def run_single_backtest(df, strategy_config, backtest_config):
    engine = BacktestEngine(
        symbol="SYNTHETIC",
        strategy_config=strategy_config,
        backtest_config=backtest_config
    )
    
    start_date = df["timestamp"].iloc[0]
    end_date = df["timestamp"].iloc[-1]
    
    result = await engine.run(df, start_date, end_date)
    return result

async def main():
    print("=" * 80)
    print("🧪 Offline Strategy Evaluation (Synthetic Data)")
    print("=" * 80)
    
    # Configuration
    strategy_config = StrategyConfigDTO(
        bollinger_band=BollingerBandConfig(period=20, std_multiplier=2.0),
        envelope=EnvelopeConfig(period=20, percentage=2.0),
        position=PositionConfig(allocation_ratio=0.1, max_position_count=1),
        risk_management=RiskManagementConfig(
            use_stop_loss=True,
            stop_loss_ratio=-0.03,
            use_take_profit=True,
            take_profit_ratio=0.05,
            use_trailing_stop=False,
            use_reverse_signal_exit=True
        )
    )
    
    backtest_config = BacktestConfigDTO(
        initial_capital=Decimal("10000000"),
        commission_rate=0.00015,
        tax_rate=0.0023,
        slippage_rate=0.0005,
        use_commission=True,
        use_tax=True,
        use_slippage=True
    )

    # 1. Single Run Analysis
    print("\n1. Single Scenario Analysis (Upward Trend with Volatility)")
    df = generate_synthetic_data(
        start_date=datetime(2023, 1, 1), 
        periods=250, 
        trend=0.0005, # Slight upward trend
        volatility=0.02, # High volatility
        seed=42
    )
    
    result = await run_single_backtest(df, strategy_config, backtest_config)
    
    print(f"  - Total Return: {result.total_return:.2f}%")
    print(f"  - Win Rate: {result.win_rate:.2f}%")
    print(f"  - Profit Factor: {result.profit_factor:.2f}")
    print(f"  - Sharpe Ratio: {result.sharpe_ratio:.2f}")
    print(f"  - MDD: {result.mdd:.2f}%")
    print(f"  - Total Trades: {result.total_trades}")
    
    # 2. Monte Carlo Simulation
    print("\n2. Statistical Significance Verification (Monte Carlo Simulation)")
    print("   Running 20 simulations with random market conditions...")
    
    simulations = 20
    results = []
    
    for i in range(simulations):
        # Vary trend and volatility slightly for each run
        random_trend = np.random.normal(0.0002, 0.0005) # Mean drift 0.02%
        random_vol = np.random.uniform(0.01, 0.03) # Volatility between 1% and 3%
        
        df_sim = generate_synthetic_data(
            start_date=datetime(2023, 1, 1), 
            periods=250, 
            trend=random_trend, 
            volatility=random_vol,
            seed=i
        )
        
        res = await run_single_backtest(df_sim, strategy_config, backtest_config)
        results.append(res)
        print(f"   [Run {i+1:2d}] Return: {res.total_return:6.2f}% | Win Rate: {res.win_rate:5.1f}% | Sharpe: {res.sharpe_ratio:5.2f}")

    # Aggregated Stats
    total_returns = [r.total_return for r in results]
    win_rates = [r.win_rate for r in results]
    sharpe_ratios = [r.sharpe_ratio for r in results]
    
    print("\n📊 Monte Carlo Summary:")
    print(f"  - Average Return: {np.mean(total_returns):.2f}% (Std: {np.std(total_returns):.2f})")
    print(f"  - Average Win Rate: {np.mean(win_rates):.1f}% (Min: {np.min(win_rates):.1f}%, Max: {np.max(win_rates):.1f}%)")
    print(f"  - Average Sharpe: {np.mean(sharpe_ratios):.2f}")
    print(f"  - Positive Return Probability: {sum(r > 0 for r in total_returns) / simulations * 100:.1f}%")

    # 3. Real-time Comparison Check
    print("\n3. Real-time Trading Data Comparison")
    # In a real scenario, we would load trade logs from a DB or file.
    # Here we check for common log locations.
    import os
    log_files = []
    for root, dirs, files in os.walk("logs"):
        for file in files:
            if file.endswith(".log"):
                log_files.append(os.path.join(root, file))
    
    if log_files:
        print(f"  Found log files: {len(log_files)}")
        print("  (Analysis of real-time logs would proceed here if format matches backtest trades)")
    else:
        print("  ⚠️ No real-time trading logs found in 'logs/' directory.")
        print("  Unable to compare with real-time performance directly.")
        print("  Recommendation: Enable logging in live strategy and export trade history to CSV for comparison.")

if __name__ == "__main__":
    asyncio.run(main())
