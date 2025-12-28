import asyncio
import numpy as np
import pandas as pd
from datetime import datetime
from decimal import Decimal
import logging

# Logging Setup
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
from src.application.common.indicators import TechnicalIndicators

# ==============================================================================
# 1. Custom Strategy Logic (Golden Cross + Stochastic Pullback)
# ==============================================================================

class GoldenCrossStrategy:
    def __init__(self, symbol):
        self.symbol = symbol
        self.state = "WAITING_FOR_GC"  # WAITING_FOR_GC -> WAITING_FOR_PULLBACK -> READY_TO_BUY -> IN_POSITION
        self.gc_date = None
        self.pullback_date = None
        
    def calculate_indicators(self, df):
        # Moving Averages
        df['ma60'] = df['close'].rolling(window=60).mean()
        df['ma200'] = df['close'].rolling(window=200).mean()
        
        # Stochastic Oscillator (14, 3, 3)
        low_min = df['low'].rolling(window=14).min()
        high_max = df['high'].rolling(window=14).max()
        
        df['stoch_k'] = 100 * ((df['close'] - low_min) / (high_max - low_min))
        df['stoch_d'] = df['stoch_k'].rolling(window=3).mean()
        
        return df

    def get_signal(self, row, prev_row):
        """
        Returns: 'buy', 'sell', 'hold' based on state machine
        """
        current_price = row['close']
        
        # Debug for S001 to trace logic
        if self.symbol == "S001" and row['timestamp'].day % 10 == 0:
            # logger.info(f"[{self.symbol}] {row['timestamp'].date()} State: {self.state} | P: {current_price:.0f} | MA60: {row['ma60']:.0f} | MA200: {row['ma200']:.0f} | Stoch: {row['stoch_k']:.1f}")
            pass

        # 1. Check for Golden Cross (MA60 crosses above MA200)
        if self.state == "WAITING_FOR_GC":
            if prev_row['ma60'] <= prev_row['ma200'] and row['ma60'] > row['ma200']:
                self.state = "WAITING_FOR_PULLBACK"
                self.gc_date = row['timestamp']
                print(f"[{self.symbol}] DEBUG: Golden Cross on {row['timestamp'].date()}")
                return "hold"

        # 2. Wait for First Stochastic Pullback (Oversold < 20)
        elif self.state == "WAITING_FOR_PULLBACK":
            # If GC is invalidated (MA60 drops below MA200), reset
            if row['ma60'] < row['ma200']:
                self.state = "WAITING_FOR_GC"
                print(f"[{self.symbol}] DEBUG: GC Invalidated on {row['timestamp'].date()}")
                return "hold"

            if row['stoch_k'] < 25: # Relaxed threshold to 25
                self.state = "READY_TO_BUY"
                self.pullback_date = row['timestamp']
                print(f"[{self.symbol}] DEBUG: Pullback Detected (Stoch {row['stoch_k']:.1f}) on {row['timestamp'].date()}")
                return "hold"

        # 3. Trigger Entry (Second Wave Start)
        # Buy when Stoch K crosses back above 20 (or D)
        elif self.state == "READY_TO_BUY":
            # If GC is invalidated, reset
            if row['ma60'] < row['ma200']:
                self.state = "WAITING_FOR_GC"
                print(f"[{self.symbol}] DEBUG: GC Invalidated (during Ready) on {row['timestamp'].date()}")
                return "hold"
                
            if row['stoch_k'] > 20 and prev_row['stoch_k'] <= 20:
                self.state = "IN_POSITION"
                return "buy"
            
            # Auto-enter if stoch is already recovering strongly
            if row['stoch_k'] > 30:
                 self.state = "IN_POSITION"
                 return "buy"

        # 4. Exit Logic (Simple for this demo)
        elif self.state == "IN_POSITION":
            # Exit if MA60 crosses below MA200 (Trend change) OR Stop Loss (handled by engine)
            if row['ma60'] < row['ma200']:
                self.state = "WAITING_FOR_GC"
                return "sell"
            
        return "hold"

# ==============================================================================
# 2. Simulation Environment (Synthetic Data with Market Cap)
# ==============================================================================

class MarketSimulator:
    def __init__(self):
        self.stocks = {}

    def add_stock(self, symbol, name, market_cap, volatility, trend_type="random"):
        """
        trend_type: 
          - 'random': Random walk
          - 'gc_scenario': Force a Golden Cross scenario
        """
        self.stocks[symbol] = {
            "name": name,
            "market_cap": market_cap,
            "volatility": volatility,
            "trend_type": trend_type,
            "data": None
        }

    def generate_data(self, symbol, start_date, periods):
        stock = self.stocks.get(symbol)
        if not stock: return None

        np.random.seed(hash(symbol) % 2**32)
        dates = pd.date_range(start=start_date, periods=periods, freq="D")
        
        # Base Price
        start_price = 10000
        
        if stock["trend_type"] == "gc_scenario":
            # Construct a price path that guarantees a GC and Pullback
            # Use a longer, clearer sequence to ensure MA calculations work
            # 1. Flat at 5000 for 250 days (Stabilize MA200)
            # 2. Strong Rally to 10000 (250-300 days) -> GC happens here
            # 3. Sharp Pullback to 7500 (300-320 days) -> Stoch drops
            # 4. Second Wave to 15000 (320+ days)
            
            p1_len = 250
            p2_len = 50
            p3_len = 20
            p4_len = periods - (p1_len + p2_len + p3_len)
            
            phase1 = np.full(p1_len, 5000.0)
            phase2 = np.linspace(5000, 10000, p2_len)
            phase3 = np.linspace(10000, 7500, p3_len)
            phase4 = np.linspace(7500, 15000, p4_len)
            
            trend_line = np.concatenate([phase1, phase2, phase3, phase4])
            
            # Add minimal noise to keep indicators clean
            noise = np.random.normal(0, stock["volatility"] * 1000, periods)
            prices = trend_line + noise
        else:
            # Random Walk
            returns = np.random.normal(0.0002, stock["volatility"], periods)
            prices = start_price * np.cumprod(1 + returns)

        # OHLCV Generation
        opens = prices
        closes = prices * (1 + np.random.normal(0, 0.005, periods))
        highs = np.maximum(opens, closes) * (1 + np.abs(np.random.normal(0, 0.005, periods)))
        lows = np.minimum(opens, closes) * (1 - np.abs(np.random.normal(0, 0.005, periods)))
        volumes = np.random.randint(50000, 500000, periods)

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

# ==============================================================================
# 3. Main Execution Script
# ==============================================================================

async def main():
    print("=" * 80)
    print("🌊 'Second Wave' Strategy Simulation")
    print("   Criteria: Small Cap + GC(60/200) + Stoch Pullback + Rebound")
    print("=" * 80)

    # 1. Setup Market
    sim = MarketSimulator()
    
    # Add Stocks (Small Cap < 300B KRW, Large Cap > 1T KRW)
    sim.add_stock("S001", "Small Cap Target A", 150_000_000_000, 0.01, "gc_scenario") # Ideal
    sim.add_stock("S002", "Small Cap Target B", 200_000_000_000, 0.02, "gc_scenario") # Ideal but volatile
    sim.add_stock("L001", "Large Cap Bluechip", 50_000_000_000_000, 0.015, "gc_scenario") # Too big
    sim.add_stock("S003", "Small Cap Random",   100_000_000_000, 0.025, "random")      # No setup
    
    # Generate 500 days of data (enough for new scenario)
    start_date = datetime(2023, 1, 1)
    periods = 500
    
    print("\n🔍 1. Screening Stocks (Market Cap < 300B KRW)...")
    target_stocks = []
    
    for symbol, info in sim.stocks.items():
        sim.generate_data(symbol, start_date, periods)
        
        # Filter Logic
        if info["market_cap"] < 300_000_000_000: # 300 Billion
            target_stocks.append(symbol)
            print(f"   ✅ {symbol} ({info['name']}): Cap {info['market_cap']:,} - Selected")
        else:
            print(f"   ❌ {symbol} ({info['name']}): Cap {info['market_cap']:,} - Too Large")
            
    print(f"\n   Targets: {', '.join(target_stocks)}")

    # 2. Run Strategy on Targets
    print("\n🚀 2. Running Strategy Simulation...")
    print(f"{ 'Date':^12} {'Symbol':^8} {'Action':^10} {'Price':^10} {'Note'}")
    print("-" * 60)

    trades = []
    
    # Backtest Configuration (Reuse DTOs)
    # Note: We are using custom logic, so the engine's default strategy is bypassed/mocked
    # or we simulate the engine loop manually here for the custom logic.
    # Manual loop is better for this custom state machine.
    
    initial_balance = 10_000_000
    balance = initial_balance
    holdings = {} # {symbol: {'qty': 0, 'entry_price': 0}}

    for symbol in target_stocks:
        df = sim.stocks[symbol]["data"]
        strategy = GoldenCrossStrategy(symbol)
        df = strategy.calculate_indicators(df)
        
        # Simulate day by day
        qty = 0
        entry_price = 0
        
        # Skip first 200 days for MA calculation
        for i in range(200, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i-1]
            
            signal = strategy.get_signal(row, prev_row)
            
            if signal == "buy" and qty == 0:
                # Buy Logic (Allocating 50% of initial balance per trade for simplicity)
                invest_amount = 5_000_000 
                qty = int(invest_amount / row['close'])
                entry_price = row['close']
                balance -= (qty * entry_price)
                
                print(f"{row['timestamp'].date()}   {symbol}     BUY      {row['close']:,.0f}      2nd Wave Start (Stoch {prev_row['stoch_k']:.1f}->{row['stoch_k']:.1f})")
                
            elif signal == "sell" and qty > 0:
                # Sell Logic
                revenue = qty * row['close']
                profit = (revenue - (qty * entry_price)) / (qty * entry_price) * 100
                balance += revenue
                
                print(f"{row['timestamp'].date()}   {symbol}     SELL     {row['close']:,.0f}      Trend End (Profit: {profit:+.2f}%)")
                qty = 0
                
        # Final Valuation
        if qty > 0:
            final_price = df.iloc[-1]['close']
            revenue = qty * final_price
            balance += revenue
            print(f"   * {symbol} Position held until end. Final Price: {final_price:,.0f}")

    print("\n" + "=" * 60)
    print("📊 Simulation Result")
    print(f"   Initial Balance: {initial_balance:,.0f}")
    print(f"   Final Balance:   {balance:,.0f}")
    print(f"   Return:          {((balance - initial_balance) / initial_balance * 100):+.2f}%")

if __name__ == "__main__":
    asyncio.run(main())
