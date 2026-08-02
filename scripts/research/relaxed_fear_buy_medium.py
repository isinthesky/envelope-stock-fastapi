#!/usr/bin/env python
"""
Relaxed Fear Buy Medium Backtest
RSI <= 30 or Drop >=15% from high + Medium market fear filter
On top 100 symbols with OHLCV data
"""
import asyncio
import pandas as pd
from decimal import Decimal
from sqlalchemy import text
from src.adapters.database.connection import get_async_session
from src.application.common.indicators import TechnicalIndicators as TI
from src.application.domain.strategy.ohlcv_data_loader import get_kospi_or_proxy_closes

def to_float(x):
    if isinstance(x, Decimal):
        return float(x)
    return float(x) if x is not None else 0.0

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))

async def load_df(symbol):
    async with get_async_session() as s:
        res = await s.execute(
            text('SELECT "timestamp", close, high FROM ohlcv_cache WHERE symbol = :sym AND interval = :intv ORDER BY "timestamp" ASC LIMIT 800'),
            {"sym": symbol, "intv": "1d"}
        )
        rows = res.fetchall()
    if len(rows) < 200:
        return None
    df = pd.DataFrame(
        [[to_float(r[0]), to_float(r[1]), to_float(r[2])] for r in rows],
        columns=["ts", "close", "high"]
    )
    df = df.sort_values("ts").reset_index(drop=True)
    df["rsi"] = calc_rsi(df["close"])
    df["mh60"] = df["high"].rolling(60).max()
    df["mh120"] = df["high"].rolling(120).max()
    df["d60"] = (df["close"] / df["mh60"] - 1) * 100
    df["d120"] = (df["close"] / df["mh120"] - 1) * 100
    return df

async def get_syms(n=100):
    async with get_async_session() as s:
        res = await s.execute(
            text("SELECT symbol FROM ohlcv_cache WHERE interval = :intv GROUP BY symbol HAVING COUNT(*) >= 200 ORDER BY COUNT(*) DESC LIMIT :lim"),
            {"intv": "1d", "lim": 120}
        )
        rows = res.fetchall()
    return [r[0] for r in rows if r[0] not in ("KOSPI", "KQ11")][:n]

def is_medium_fear(closes):
    if len(closes) < 25:
        return False
    return TI.is_market_fear_by_bollinger(closes)

async def main():
    print("=== Relaxed Fear Buy Medium Backtest (RSI<=30 or Drop -15%) ===")
    syms = await get_syms(100)
    print(f"Symbols selected: {len(syms)}")

    async with get_async_session() as s:
        mcloses, _, src = await get_kospi_or_proxy_closes(s, days=600)
    print(f"Market fear source: {src}")

    all_trades = []
    for sym in syms:
        df = await load_df(sym)
        if df is None or len(df) < 150:
            continue
        pos = None
        entry = 0.0
        for i in range(120, len(df)):
            r = df.iloc[i]
            if pd.isna(r["rsi"]):
                continue
            mf = is_medium_fear(mcloses[:min(i + 1, len(mcloses))])
            drop_ok = (r["d60"] <= -15) or (r["d120"] <= -15)
            rsi_ok = r["rsi"] <= 30
            if pos is None and mf and drop_ok and rsi_ok:
                pos = "long"
                entry = r["close"]
            elif pos == "long":
                pnl = (r["close"] - entry) / entry * 100
                if pnl >= 15 or pnl <= -15 or r["rsi"] >= 70:
                    all_trades.append({"sym": sym, "pnl": pnl, "win": pnl > 0})
                    pos = None

    tot = len(all_trades)
    wins = sum(1 for t in all_trades if t["win"])
    wr = round(wins / tot * 100, 2) if tot > 0 else 0
    apnl = round(sum(t["pnl"] for t in all_trades) / tot, 2) if tot > 0 else 0
    tpnl = round(sum(t["pnl"] for t in all_trades), 2)

    print(f"\n=== Results (Relaxed Medium) ===")
    print(f"Total closed trades: {tot}")
    print(f"Winning trades: {wins}")
    print(f"Win rate: {wr}%")
    print(f"Average PnL per trade: {apnl}%")
    print(f"Total PnL (sum): {tpnl}%")
    print(f"Symbols with trades: {len(set(t['sym'] for t in all_trades))}")
    if tot > 0:
        print(f"Approx trades/year (100 syms, ~2.5y): {tot / 2.5:.1f}")

if __name__ == "__main__":
    asyncio.run(main())
