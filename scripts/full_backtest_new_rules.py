#!/usr/bin/env python3
"""
Full Backtest Simulation for New Separated Rules
- Buy: Golden Cross (MA55/165) + RSI <= 40 (daily close)
- Sell Simple: RSI>=70 OR 20d high DD>=15% OR 85% profit protection
- Sell Hybrid: Legacy Phase (mock) + Simple overlay (upgrade stage)

Runs Monte Carlo style on synthetic data.
Compares: Legacy Sell vs Simple Sell vs Hybrid Sell
Metrics: Total Return, Win Rate, Max DD, Number of Trades, Avg Hold Days
"""

import random
import math
from dataclasses import dataclass
from typing import List, Dict

@dataclass
class Trade:
    entry_date: int
    entry_price: float
    exit_date: int
    exit_price: float
    exit_reason: str
    profit_pct: float

def generate_synthetic_prices(periods: int = 300, trend: float = 0.0003, vol: float = 0.018, seed: int = None) -> List[float]:
    if seed is not None:
        random.seed(seed)
    prices = [100.0]
    for _ in range(1, periods):
        ret = trend + random.gauss(0, vol)
        prices.append(prices[-1] * (1 + ret))
    return prices

def calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
    rsis = [50.0] * len(prices)
    if len(prices) <= period:
        return rsis
    gains = []
    losses = []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(prices)):
        if i > period:
            avg_gain = (avg_gain * (period-1) + gains[i-1]) / period
            avg_loss = (avg_loss * (period-1) + losses[i-1]) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsis[i] = 100 - (100 / (1 + rs))
    return rsis

def calculate_ma(prices: List[float], period: int) -> List[float]:
    mas = [0.0] * len(prices)
    for i in range(period-1, len(prices)):
        mas[i] = sum(prices[i-period+1:i+1]) / period
    return mas

def run_backtest(prices: List[float], sell_mode: str = "simple") -> Dict:
    """
    sell_mode: "legacy", "simple", "hybrid"
    Legacy here is a mock of old Phase (more conservative: only strong death cross + high RSI)
    """
    n = len(prices)
    rsi = calculate_rsi(prices)
    ma55 = calculate_ma(prices, 55)
    ma165 = calculate_ma(prices, 165)

    position = None  # (entry_idx, entry_price, peak_profit, highest_price)
    trades: List[Trade] = []
    equity = 10000.0
    peak_equity = 10000.0
    max_dd = 0.0

    for i in range(165, n):  # enough data for MAs
        close = prices[i]
        current_rsi = rsi[i]
        gc_active = ma55[i] > ma165[i] if ma55[i] > 0 and ma165[i] > 0 else False

        # === BUY LOGIC (New Rule) ===
        buy_signal = gc_active and current_rsi <= 40 and position is None

        if buy_signal:
            position = {
                "entry_idx": i,
                "entry_price": close,
                "peak_profit": 0.0,
                "highest_price": close
            }
            continue

        if position is None:
            continue

        # Update position
        entry_p = position["entry_price"]
        highest = max(position["highest_price"], close)
        position["highest_price"] = highest
        curr_profit = (close - entry_p) / entry_p
        position["peak_profit"] = max(position["peak_profit"], curr_profit)

        # === SELL LOGIC ===
        sell = False
        reason = ""

        # Simple rule
        simple_sell = False
        simple_reasons = []
        if current_rsi >= 70:
            simple_sell = True
            simple_reasons.append("RSI>=70")
        # 20d high DD (approx last 20 bars)
        if i >= 20:
            recent_high = max(prices[i-19:i+1])
            if close < recent_high * 0.85:
                simple_sell = True
                dd = (recent_high - close) / recent_high
                simple_reasons.append(f"20dDD{dd*100:.1f}%")
        if position["peak_profit"] > 0 and curr_profit < position["peak_profit"] * 0.85:
            simple_sell = True
            simple_reasons.append("85%ProfitProtect")

        # Legacy mock (more conservative)
        legacy_sell = False
        if i > 5:
            death_cross = ma55[i] < ma165[i] and ma55[i-1] >= ma165[i-1]
            if death_cross and current_rsi > 72:
                legacy_sell = True
                reason = "Legacy: DeathCross+RSI"

        # Mode decision
        if sell_mode == "simple":
            sell = simple_sell
            reason = "Simple:" + ",".join(simple_reasons) if simple_reasons else ""
        elif sell_mode == "legacy":
            sell = legacy_sell
            reason = reason or "Legacy"
        elif sell_mode == "hybrid":
            sell = legacy_sell or simple_sell
            if simple_sell and not legacy_sell:
                reason = "Hybrid:SimpleOverlay-" + ",".join(simple_reasons)
            else:
                reason = reason or "Hybrid:Legacy"

        if sell and position:
            exit_p = close
            profit = (exit_p - entry_p) / entry_p
            trades.append(Trade(
                entry_date=position["entry_idx"],
                entry_price=entry_p,
                exit_date=i,
                exit_price=exit_p,
                exit_reason=reason,
                profit_pct=profit
            ))
            equity *= (1 + profit)
            if equity > peak_equity:
                peak_equity = equity
            else:
                dd = (peak_equity - equity) / peak_equity
                if dd > max_dd:
                    max_dd = dd
            position = None

    # Close open position at end
    if position:
        profit = (prices[-1] - position["entry_price"]) / position["entry_price"]
        trades.append(Trade(position["entry_idx"], position["entry_price"], n-1, prices[-1], "EOD", profit))
        equity *= (1 + profit)

    # Metrics
    if not trades:
        return {"mode": sell_mode, "trades": 0, "total_return": 0, "win_rate": 0, "max_dd": 0, "avg_hold": 0}

    wins = sum(1 for t in trades if t.profit_pct > 0)
    win_rate = wins / len(trades)
    total_return = (equity - 10000) / 10000
    avg_hold = sum(t.exit_date - t.entry_date for t in trades) / len(trades)

    return {
        "mode": sell_mode,
        "trades": len(trades),
        "total_return": round(total_return, 4),
        "win_rate": round(win_rate, 3),
        "max_dd": round(max_dd, 4),
        "avg_hold_days": round(avg_hold),
        "final_equity": round(equity, 2)
    }

def run_full_backtest(simulations: int = 50, periods: int = 400):
    print("=" * 75)
    print("FULL BACKTEST: New Buy (GC+RSI<=40) + Sell Modes (Simple vs Hybrid vs Legacy)")
    print(f"Simulations: {simulations} | Periods per sim: {periods}")
    print("=" * 75)

    modes = ["legacy", "simple", "hybrid"]
    all_results = {m: [] for m in modes}

    for sim in range(simulations):
        seed = 42 + sim
        prices = generate_synthetic_prices(periods=periods, trend=random.uniform(0.0001, 0.0006), vol=random.uniform(0.012, 0.025), seed=seed)

        for mode in modes:
            res = run_backtest(prices, sell_mode=mode)
            all_results[mode].append(res)

    # Aggregate
    print("\n--- AGGREGATED RESULTS ---")
    for mode in modes:
        results = all_results[mode]
        avg_ret = sum(r["total_return"] for r in results) / len(results)
        avg_wr = sum(r["win_rate"] for r in results) / len(results)
        avg_dd = sum(r["max_dd"] for r in results) / len(results)
        avg_trades = sum(r["trades"] for r in results) / len(results)
        print(f"\n{mode.upper()}:")
        print(f"  Avg Total Return: {avg_ret*100:+.2f}%")
        print(f"  Avg Win Rate:     {avg_wr*100:.1f}%")
        print(f"  Avg Max DD:       {avg_dd*100:.1f}%")
        print(f"  Avg Trades:       {avg_trades:.1f}")

    print("\n" + "=" * 75)
    print("Note: Synthetic data (trend + volatility variation). Real data would use OHLCV cache + SellStrategyService.")
    print("Simple tends to exit faster on rules. Hybrid balances with legacy filters.")
    print("=" * 75)

if __name__ == "__main__":
    run_full_backtest(simulations=60, periods=450)