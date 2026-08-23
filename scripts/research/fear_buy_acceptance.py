#!/usr/bin/env python3
"""Fear Buy 신뢰 백테스트 = acceptance test (#4).

운영 함수만 재사용하여 리포트의 '조합 0건'을 실측하고, 수정 후 >0 으로 바뀌는지 검증한다.
- 시장 공포: TechnicalIndicators.is_market_fear_by_bollinger (KOSPI, 없으면 대형주 프록시)
- RSI: TechnicalIndicators.calculate_rsi_series (Wilder, 운영 표준)
- 매도: SellStrategyService.compute_simple_sell_signal (운영)
- 정렬: 날짜 기준(위치 인덱스 금지), lookahead 금지

Run: ./.venv/bin/python scripts/fear_buy_acceptance.py --symbols 100 --window 7 --rsi 30 --drop 0.15
"""
import argparse
import asyncio
from datetime import date

import pandas as pd
from sqlalchemy import text

from src.adapters.database.connection import get_async_session
from src.application.common.indicators import TechnicalIndicators as TI
from src.application.domain.strategy.ohlcv_data_loader import get_kospi_or_proxy_closes
from src.application.domain.strategy.sell_strategy_service import SellStrategyService


async def _top_symbols(session, n: int, min_rows: int = 200) -> list[str]:
    res = await session.execute(
        text(
            "SELECT symbol, count(*) c FROM ohlcv_cache WHERE interval='1d' "
            "GROUP BY symbol HAVING count(*) >= :m ORDER BY c DESC LIMIT :n"
        ),
        {"m": min_rows, "n": n},
    )
    return [r[0] for r in res.fetchall() if r[0] != "KOSPI"]


async def _load_symbol(session, sym: str) -> pd.DataFrame:
    res = await session.execute(
        text(
            "SELECT timestamp, close FROM ohlcv_cache WHERE symbol=:s AND interval='1d' "
            "ORDER BY timestamp ASC"
        ),
        {"s": sym},
    )
    rows = res.fetchall()
    df = pd.DataFrame(rows, columns=["timestamp", "close"])
    df["close"] = df["close"].astype(float)
    df["d"] = pd.to_datetime(df["timestamp"]).dt.date
    # 날짜 단위 방어적 dedup(잔여 팬텀/중복이 RSI·rolling-high를 밀지 않도록)
    df = df.drop_duplicates(subset=["d"], keep="last").reset_index(drop=True)
    return df


def _market_fear_window_by_date(closes, timestamps, window: int) -> dict[date, bool]:
    """시장 시계열에서 날짜→(최근 window일 내 공포 존재) 매핑."""
    dates = [pd.Timestamp(t).date() for t in timestamps]
    fear_flag = [False] * len(closes)
    for t in range(25, len(closes)):
        fear_flag[t] = TI.is_market_fear_by_bollinger(closes[: t + 1])
    win = {}
    for t in range(len(closes)):
        lo = max(0, t - window)
        win[dates[t]] = any(fear_flag[lo : t + 1])
    return win


async def run(n_symbols: int, window: int, rsi_th: float, drop_pct: float, lookback: int) -> dict:
    svc = SellStrategyService(session=None)
    async with get_async_session() as session:
        syms = await _top_symbols(session, n_symbols)
        m_closes, m_ts, m_src = await get_kospi_or_proxy_closes(session, days=1200)
        if len(m_closes) < 25:
            return {"error": f"market series too short ({len(m_closes)}, src={m_src})"}
        fear_win = _market_fear_window_by_date(m_closes, m_ts, window)
        fear_days = sum(1 for v in fear_win.values() if v)

        individual = 0
        combined = 0
        closed = []  # pnl list

        for sym in syms:
            df = await _load_symbol(session, sym)
            if len(df) < lookback + 5:
                continue
            closes = df["close"]
            rsi = TI.calculate_rsi_series(df.rename(columns={"close": "close"}), 14).tolist()
            roll_high = closes.rolling(lookback, min_periods=lookback).max().tolist()
            dates = df["d"].tolist()
            cl = closes.tolist()

            pos = None  # (entry_idx, entry_price, highest)
            for t in range(lookback, len(df)):
                if pos is None:
                    r = rsi[t]
                    rh = roll_high[t]
                    if r is None or pd.isna(r) or rh is None or pd.isna(rh):
                        continue
                    indiv = (r <= rsi_th) and (cl[t] <= rh * (1 - drop_pct))
                    if indiv:
                        individual += 1
                        if fear_win.get(dates[t], False):  # 날짜 정렬된 시장 공포 윈도우
                            combined += 1
                            pos = (t, cl[t], cl[t])
                else:
                    entry_i, entry_p, high = pos
                    high = max(high, cl[t])
                    win_df = df.iloc[max(0, t - 5) : t + 1][["close"]]
                    sig = svc.compute_simple_sell_signal(
                        df=win_df, rsi=rsi[t] if rsi[t] is not None else 50.0,
                        current_price=cl[t], entry_price=entry_p, highest_price=high,
                    )
                    if sig["should_sell"] or t == len(df) - 1:
                        closed.append((cl[t] - entry_p) / entry_p)
                        pos = None

        wins = sum(1 for p in closed if p > 0)
        return {
            "symbols": len(syms),
            "market_source": m_src,
            "market_days": len(m_closes),
            "fear_days": fear_days,
            "individual_signals": individual,
            "combined_trades": combined,
            "closed_trades": len(closed),
            "win_rate": round(wins / len(closed), 3) if closed else None,
            "avg_pnl": round(sum(closed) / len(closed), 4) if closed else None,
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=100)
    ap.add_argument("--window", type=int, default=7)
    ap.add_argument("--rsi", type=float, default=30.0)
    ap.add_argument("--drop", type=float, default=0.15)
    ap.add_argument("--lookback", type=int, default=120)
    a = ap.parse_args()
    res = asyncio.run(run(a.symbols, a.window, a.rsi, a.drop, a.lookback))
    print("=" * 60)
    print("FEAR BUY ACCEPTANCE BACKTEST (production functions, real OHLCV)")
    print("=" * 60)
    for k, v in res.items():
        print(f"  {k:20s}: {v}")
    print("=" * 60)
    if isinstance(res.get("combined_trades"), int):
        verdict = "PASS (combined > 0)" if res["combined_trades"] > 0 else "STILL ZERO"
        print(f"  ACCEPTANCE: {verdict}")


if __name__ == "__main__":
    main()
