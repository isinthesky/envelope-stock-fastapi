import asyncio
import numpy as np
import pandas as pd
from datetime import datetime
from decimal import Decimal
import random
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from src.application.domain.backtest.engine import BacktestEngine
from src.application.domain.backtest.dto import BacktestConfigDTO
from src.application.domain.strategy.dto import (
    StrategyConfigDTO,
    BollingerBandConfig,
    EnvelopeConfig,
    PositionConfig,
    RiskManagementConfig,
)

# 1. Synthetic Data Generator with Metadata
class SyntheticMarket:
    def __init__(self):
        self.stocks = {}

    def add_stock(self, symbol, name, start_price, volatility, trend, avg_volume, financials):
        self.stocks[symbol] = {
            "name": name,
            "start_price": start_price,
            "volatility": volatility,
            "trend": trend,
            "avg_volume": avg_volume,
            "financials": financials,
            "data": None
        }

    def generate_data(self, symbol, start_date, periods):
        stock = self.stocks.get(symbol)
        if not stock:
            return None

        np.random.seed(hash(symbol) % 2**32) # Deterministic per symbol
        
        dates = pd.date_range(start=start_date, periods=periods, freq="D")
        
        # Price Generation
        returns = np.random.normal(loc=stock["trend"], scale=stock["volatility"], size=periods)
        price_paths = stock["start_price"] * np.cumprod(1 + returns)
        
        # OHLC Generation
        opens = price_paths
        closes = price_paths * (1 + np.random.normal(0, 0.005, periods))
        highs = np.maximum(opens, closes) * (1 + np.abs(np.random.normal(0, 0.005, periods)))
        lows = np.minimum(opens, closes) * (1 - np.abs(np.random.normal(0, 0.005, periods)))
        
        # Volume Generation (with noise)
        volumes = np.random.normal(loc=stock["avg_volume"], scale=stock["avg_volume"]*0.2, size=periods)
        volumes = np.maximum(volumes, 1000).astype(int) # Ensure positive volume

        df = pd.DataFrame({
            "timestamp": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes
        })
        
        stock["data"] = df
        return df

# 2. Stock Selection Logic
class StockSelector:
    def __init__(self, market):
        self.market = market

    def filter_stocks(self, criteria):
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

        for symbol, info in self.market.stocks.items():
            # 1. Volume Check
            avg_vol = info["avg_volume"]
            if avg_vol < criteria.get("min_volume", 0):
                print(f"   ❌ {symbol} ({info['name']}): Volume too low ({avg_vol:,})")
                continue

            # 2. Financial Check
            fin = info["financials"]
            if fin["debt_ratio"] > criteria.get("max_debt_ratio", 9999):
                print(f"   ❌ {symbol} ({info['name']}): High Debt ({fin['debt_ratio']}%)")
                continue
            
            if fin["per"] > criteria.get("max_per", 9999):
                print(f"   ❌ {symbol} ({info['name']}): Overvalued (PER {fin['per']})")
                continue

            # 3. Volatility Check (using generated data)
            if info["data"] is None:
                # Generate strictly for analysis if not present
                self.market.generate_data(symbol, datetime(2023,1,1), 100)
            
            # Calculate daily returns std dev
            returns = info["data"]["close"].pct_change().std()
            if returns < criteria.get("min_volatility", 0):
                print(f"   ❌ {symbol} ({info['name']}): Low Volatility ({returns*100:.2f}%)")
                continue

            print(f"   ✅ {symbol} ({info['name']}): Passed Selection")
            selected.append(symbol)
            
        return selected

# 3. Main Execution
async def main():
    print("=" * 80)
    print("🚀 Stock Selection & Strategy Optimization")
    print("=" * 80)

    # Initialize Market with diverse stocks
    market = SyntheticMarket()
    
    # Stock A: The Ideal Candidate (High Vol, Good Fin, High Vol)
    market.add_stock("005930", "Samsung Elec (Sim)", 70000, 0.02, 0.0005, 10000000, 
                     {"debt_ratio": 30.0, "per": 15.0})
    
    # Stock B: Low Volatility (Stable)
    market.add_stock("000660", "SK Hynix (Sim)", 120000, 0.005, 0.0002, 5000000, 
                     {"debt_ratio": 40.0, "per": 12.0})
    
    # Stock C: Bad Financials (High Debt)
    market.add_stock("035720", "Kakao (Sim)", 50000, 0.025, -0.0005, 2000000, 
                     {"debt_ratio": 150.0, "per": 50.0})
    
    # Stock D: Low Volume
    market.add_stock("005380", "Hyundai Motor (Sim)", 200000, 0.015, 0.0003, 100000, 
                     {"debt_ratio": 80.0, "per": 8.0})
    
    # Stock E: High Volatility, Good Financials (Another Candidate)
    market.add_stock("035420", "Naver (Sim)", 200000, 0.022, 0.0004, 1500000, 
                     {"debt_ratio": 45.0, "per": 25.0})

    # Generate Data for all
    for sym in market.stocks:
        market.generate_data(sym, datetime(2023, 1, 1), 365)

    # Perform Selection
    selector = StockSelector(market)
    selected_symbols = selector.filter_stocks({
        "min_volume": 500000,        # Min 500k avg daily volume
        "min_volatility": 0.015,     # Min 1.5% daily volatility
        "max_debt_ratio": 100.0,     # Max 100% debt ratio
        "max_per": 40.0              # Max PER 40
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
        position=PositionConfig(allocation_ratio=0.2, max_position_count=1), # Increased allocation
        risk_management=RiskManagementConfig(
            use_stop_loss=True,
            stop_loss_ratio=-0.05,
            use_take_profit=False,     # Let profits run
            use_trailing_stop=True,    # Use trailing stop
            trailing_stop_ratio=0.03,  # 3% trailing
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

    results = {}
    for symbol in selected_symbols:
        df = market.stocks[symbol]["data"]
        engine = BacktestEngine(symbol, strategy_config, backtest_config)
        
        result = await engine.run(
            df, 
            df["timestamp"].iloc[0], 
            df["timestamp"].iloc[-1]
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
