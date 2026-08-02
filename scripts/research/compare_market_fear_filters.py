#!/usr/bin/env python
"""
Compare strict / medium / lenient versions of the market fear filter.
- Prefers real KOSPI (symbol='KOSPI') from DB
- Falls back to equal-weighted proxy from major large-caps
- Uses the BB(20,2) + bandwidth logic from indicators
Run: uv run python scripts/compare_market_fear_filters.py --days 600
"""
import argparse
import asyncio
from datetime import datetime
from typing import List, Tuple, Optional

import pandas as pd
from sqlalchemy import text

from src.adapters.database.connection import get_async_session
from src.application.common.indicators import TechnicalIndicators as TI


MAJOR_PROXY_SYMBOLS = ["005930", "000660", "035420", "006400", "207940"]  # Samsung, SKHynix, Naver, SamsungSDI, Ecopro


async def get_kospi_or_proxy_closes(days: int = 600) -> Tuple[List[float], List[datetime], str]:
    """
    Reusable helper: Returns (closes, timestamps, source)
    Prefers real KOSPI data. Falls back to proxy.
    """
    async with get_async_session() as session:
        # 1. Try real KOSPI
        res = await session.execute(
            text("""
                SELECT timestamp, close 
                FROM ohlcv_cache 
                WHERE symbol = :sym AND interval = '1d' 
                ORDER BY timestamp ASC 
                LIMIT :lim
            """),
            {"sym": "KOSPI", "lim": days + 10}
        )
        rows = res.fetchall()
        if len(rows) >= 100:  # need enough history for BB
            df = pd.DataFrame(rows, columns=["timestamp", "close"])
            df = df.sort_values("timestamp").tail(days)
            closes = df["close"].astype(float).tolist()
            ts = df["timestamp"].tolist()
            print(f"Using REAL KOSPI data: {len(closes)} days ({ts[0].date()} ~ {ts[-1].date()})")
            return closes, ts, "KOSPI"

        # 2. Fallback to proxy (average of major symbols, normalized)
        print("KOSPI data insufficient or empty. Building proxy from major caps...")
        frames = []
        for sym in MAJOR_PROXY_SYMBOLS:
            res = await session.execute(
                text("""
                    SELECT timestamp, close 
                    FROM ohlcv_cache 
                    WHERE symbol = :sym AND interval = '1d' 
                    ORDER BY timestamp ASC 
                    LIMIT :lim
                """),
                {"sym": sym, "lim": days + 10}
            )
            rows = res.fetchall()
            if rows:
                df = pd.DataFrame(rows, columns=["timestamp", "close"]).set_index("timestamp")
                frames.append(df["close"].astype(float).rename(sym))

        if not frames:
            raise RuntimeError("No data available for proxy either.")

        proxy_df = pd.concat(frames, axis=1).dropna()
        # Equal weight normalized (each stock divided by its mean, then average)
        norm = proxy_df / proxy_df.mean()
        proxy_close = norm.mean(axis=1).tail(days).tolist()
        ts = proxy_df.tail(days).index.tolist()

        print(f"Using PROXY (equal-weight normalized majors): {len(proxy_close)} days ({ts[0].date()} ~ {ts[-1].date()})")
        return proxy_close, ts, "PROXY"


def fear_filter_lenient(closes: List[float]) -> bool:
    """관대한 버전"""
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
    return close < lower * 1.01 or bw > avg * 1.05


def fear_filter_medium(closes: List[float]) -> bool:
    """기본 추천 조합 (현재)"""
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
    return close < lower and bw > avg * 1.10


def fear_filter_strict(closes: List[float]) -> bool:
    """엄격 버전"""
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
    prev_close = closes[-2] if len(closes) >= 2 else close
    return close < lower and bw > avg * 1.20 and close < prev_close


async def run_comparison(days: int = 600):
    closes, timestamps, source = await get_kospi_or_proxy_closes(days=days)
    print(f"\n=== 시장 공포 필터 비교 ({source}, {len(closes)} days) ===\n")

    results = {}
    for name, func in [("Lenient", fear_filter_lenient), ("Medium", fear_filter_medium), ("Strict", fear_filter_strict)]:
        fear_days = []
        for i in range(20, len(closes)):
            if func(closes[:i+1]):
                fear_days.append(timestamps[i])
        results[name] = fear_days
        print(f"{name:8s}: {len(fear_days):3d} fear days")

    print("\n--- Sample fear periods (recent) ---")
    for name in ["Lenient", "Medium", "Strict"]:
        days = results[name]
        if days:
            recent = [d.date() for d in days[-8:]]
            print(f"{name}: {recent}")
        else:
            print(f"{name}: (none)")

    # Rough estimate: clusters + trades/year
    print("\n--- Rough trading frequency estimate (if used as entry gate) ---")
    for name, days in results.items():
        if not days:
            print(f"{name}: 0 signals")
            continue
        # Count clusters (gaps > 5 trading days)
        clusters = 1
        for a, b in zip(days, days[1:]):
            if (b - a).days > 7:
                clusters += 1
        years = max(1, (days[-1] - days[0]).days / 365)
        per_year = clusters / years
        print(f"{name:8s}: ~{clusters} clusters over {years:.1f}y → ~{per_year:.2f} entries/year (conservative)")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=600)
    args = parser.parse_args()
    asyncio.run(run_comparison(days=args.days))
