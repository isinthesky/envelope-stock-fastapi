#!/usr/bin/env python
"""
Fear Buy Backtest: RSI<=25 + big drop + Market Fear Filter (Medium vs Strict)
Uses real DB data + get_kospi_or_proxy_closes for market filter.
Compares Medium vs Strict versions.
"""
import asyncio
import pandas as pd
from sqlalchemy import text
from datetime import datetime, timedelta
from decimal import Decimal

from src.adapters.database.connection import get_async_session
from src.application.common.indicators import TechnicalIndicators as TI
from src.application.domain.strategy.ohlcv_data_loader import get_kospi_or_proxy_closes


SYMBOLS = ["005930", "000660", "035420", "006400", "207940"]
DAYS = 600


def calc_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


async def load_symbol_data(symbol: str, days: int = DAYS):
    async with get_async_session() as session:
        res = await session.execute(
            text('SELECT "timestamp", open, high, low, close, volume FROM ohlcv_cache '
                 'WHERE symbol = :sym AND interval = \'1d\' ORDER BY "timestamp" ASC LIMIT :lim'),
            {"sym": symbol, "lim": days + 20}
        )
        rows = res.fetchall()
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df = df.sort_values("timestamp").tail(days).reset_index(drop=True)
        df["close"] = df["close"].astype(float)
        df["high"] = df["high"].astype(float)
        df["rsi"] = calc_rsi(df["close"])
        df["max_high_60"] = df["high"].rolling(60).max()
        df["max_high_120"] = df["high"].rolling(120).max()
        df["drop_60"] = (df["close"] / df["max_high_60"] - 1) * 100
        df["drop_120"] = (df["close"] / df["max_high_120"] - 1) * 100
        return df


def is_fear_buy(df_row, market_fear_func, drop_threshold=-20, rsi_th=25):
    if pd.isna(df_row["rsi"]):
        return False
    rsi_ok = df_row["rsi"] <= rsi_th
    drop_ok = (df_row["drop_60"] <= drop_threshold) or (df_row["drop_120"] <= drop_threshold * 0.8)
    market_ok = market_fear_func  # precomputed per day
    return rsi_ok and drop_ok and market_ok


async def run_fear_backtest(filter_name: str, market_fear_func):
    """
    market_fear_func: a function that takes list of closes up to now and returns bool
    """
    print(f"\n=== Fear Buy Backtest - {filter_name} ===")
    results = {}
    total_trades = 0
    total_pnl = 0.0
    all_trades = []

    async with get_async_session() as session:
        market_closes, mts, _ = await get_kospi_or_proxy_closes(session, days=DAYS)

    for sym in SYMBOLS:
        df = await load_symbol_data(sym)
        if df is None or len(df) < 100:
            continue

        position = None
        trades = []
        equity = 1.0
        entry_price = 0.0
        shares = 0.0

        for i in range(120, len(df)):
            row = df.iloc[i]
            current_close = row["close"]
            # market fear up to this point
            m_idx = min(i, len(market_closes)-1)
            m_closes_up_to_now = market_closes[:m_idx+1] if m_idx >= 0 else [current_close]
            is_market_fear = market_fear_func(m_closes_up_to_now)

            fear_buy = is_fear_buy(row, is_market_fear)

            if position is None and fear_buy:
                # enter (simple full position for simplicity; can split in future)
                position = "long"
                entry_price = current_close
                shares = 1.0 / current_close   # normalize to 1 unit capital
                trades.append({"type": "buy", "date": row["timestamp"], "price": entry_price})

            elif position == "long":
                pnl = (current_close - entry_price) / entry_price * 100
                if pnl >= 15 or pnl <= -15 or (not pd.isna(row["rsi"]) and row["rsi"] >= 70):
                    # sell
                    equity *= (1 + pnl/100)
                    total_pnl += pnl
                    trades.append({"type": "sell", "date": row["timestamp"], "price": current_close, "pnl_pct": round(pnl, 2)})
                    position = None
                    total_trades += 1
                    all_trades.append({"sym": sym, "entry": trades[-2]["date"] if len(trades)>1 else None, "exit": row["timestamp"], "pnl": round(pnl,2)})

        # close open if any
        if position == "long":
            final_pnl = (df.iloc[-1]["close"] - entry_price) / entry_price * 100
            equity *= (1 + final_pnl/100)
            total_pnl += final_pnl

        results[sym] = {"trades": len([t for t in trades if t["type"]=="sell"]), "final_equity": round(equity, 3)}

    print("Per symbol:", results)
    print(f"Total closed trades: {total_trades}")
    avg_pnl = total_pnl / max(1, total_trades)
    print(f"Avg pnl per trade: {avg_pnl:.2f}%")
    print("Sample trades:", all_trades[:5])
    return results, total_trades, avg_pnl


def medium_fear(closes):
    return TI.is_market_fear_by_bollinger(closes)


def strict_fear(closes):
    if len(closes) < 25:
        return False
    bb = TI.calculate_bollinger_bands(closes[-21:], 20, 2.0)
    if not bb["lower"]:
        return False
    close = closes[-1]
    lower = bb["lower"]
    middle = bb["middle"] or 1
    bw = (bb["upper"] - lower) / middle
    prev_bws = []
    for j in range(-6, -1):
        w = closes[j-20:j+1]
        if len(w) >= 20:
            b = TI.calculate_bollinger_bands(w, 20, 2.0)
            if b["middle"]:
                prev_bws.append((b["upper"] - b["lower"]) / b["middle"])
    avg = sum(prev_bws) / len(prev_bws) if prev_bws else bw
    prev_c = closes[-2] if len(closes) >= 2 else close
    return close < lower and bw > avg * 1.20 and close < prev_c


async def main():
    print("Running Medium filter backtest...")
    med_res, med_tr, med_avg = await run_fear_backtest("Medium", medium_fear)

    print("\nRunning Strict filter backtest...")
    str_res, str_tr, str_avg = await run_fear_backtest("Strict", strict_fear)

    print("\n=== Summary Comparison ===")
    print(f"Medium: trades={med_tr}, avg_pnl={med_avg:.2f}%")
    print(f"Strict: trades={str_tr}, avg_pnl={str_avg:.2f}%")


if __name__ == "__main__":
    asyncio.run(main())
