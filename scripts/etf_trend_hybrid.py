#!/usr/bin/env python3
"""ETF 추세추종(MA50/120) + 손절/트레일링 하이브리드 비교.

walk-forward에서 약세·횡보장(2021~22) whipsaw 손실이 드러남 → 손절/트레일링이
손실·회전을 개선하는지 검증. 진입=골든크로스(MA50>120), 청산 규칙만 변형.

변형:
  V0 데드크로스only(기준) / V1 +하드손절 / V2 +트레일링 / V3 데드크로스+트레일링 동시
Run: ./.venv/bin/python -m scripts.etf_trend_hybrid --codes "069500,..."
"""
import argparse
import asyncio

import pandas as pd

from src.adapters.database.connection import get_async_session
from scripts.fear_buy_acceptance import _top_symbols, _load_symbol

SHORT, LONG = 50, 120


def _sim(symdata, exit_mode, stop_pct):
    """exit_mode: 'dc'(데드크로스), 'hard'(+진입가 손절), 'trail'(+트레일링), 'dc_trail'."""
    trades = []  # (year, pnl)
    for closes, dates in symdata:
        s = pd.Series(closes)
        ma_s = s.rolling(SHORT).mean()
        ma_l = s.rolling(LONG).mean()
        pos = None  # (entry_idx, entry_price, peak)
        n = len(closes)
        for t in range(LONG, n):
            if pd.isna(ma_s[t]) or pd.isna(ma_l[t]) or pd.isna(ma_s[t - 1]) or pd.isna(ma_l[t - 1]):
                continue
            gc = ma_s[t] > ma_l[t] and ma_s[t - 1] <= ma_l[t - 1]
            dc = ma_s[t] < ma_l[t] and ma_s[t - 1] >= ma_l[t - 1]
            if pos is None:
                if gc:
                    pos = (t, closes[t], closes[t])
            else:
                ei, ep, peak = pos
                peak = max(peak, closes[t])
                pos = (ei, ep, peak)
                exit_now = False
                if exit_mode in ("dc", "dc_trail") and dc:
                    exit_now = True
                if exit_mode == "hard" and closes[t] <= ep * (1 - stop_pct):
                    exit_now = True
                if exit_mode == "hard" and dc:
                    exit_now = True  # 하드손절 모드도 데드크로스는 청산
                if exit_mode in ("trail", "dc_trail") and closes[t] <= peak * (1 - stop_pct):
                    exit_now = True
                if t == n - 1:
                    exit_now = True
                if exit_now:
                    trades.append((dates[ei].year, (closes[t] - ep) / ep))
                    pos = None
    return trades


def _metrics(trades):
    pnls = [p for (_, p) in trades]
    if not pnls:
        return {"trades": 0, "win_rate": 0.0, "avg_pnl": 0.0, "avg_loss": 0.0, "choppy": 0.0}
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    choppy = [p for (y, p) in trades if y in (2021, 2022)]  # 약세·횡보 구간
    return {
        "trades": len(pnls),
        "win_rate": len(wins) / len(pnls),
        "avg_pnl": sum(pnls) / len(pnls),
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "choppy": (sum(choppy) / len(choppy)) if choppy else 0.0,
    }


async def run(n_symbols, codes=None):
    async with get_async_session() as session:
        syms = codes if codes else await _top_symbols(session, n_symbols)
        symdata = []
        for sym in syms:
            df = await _load_symbol(session, sym)
            if len(df) >= 210:
                symdata.append((df["close"].tolist(), df["d"].tolist()))
    variants = [
        ("V0 데드크로스only", "dc", 0.0),
        ("V1 +하드손절 8%", "hard", 0.08),
        ("V1 +하드손절 12%", "hard", 0.12),
        ("V2 트레일링 8%", "trail", 0.08),
        ("V2 트레일링 12%", "trail", 0.12),
        ("V3 데드크로스+트레일15%", "dc_trail", 0.15),
    ]
    rows = [{"name": nm, **_metrics(_sim(symdata, m, sp))} for (nm, m, sp) in variants]
    return {"symbols": len(symdata), "rows": rows}


def _fmt(res):
    print("=" * 96)
    print(f"ETF 추세추종(MA50/120) 하이브리드 청산 비교 (symbols={res['symbols']})")
    print("=" * 96)
    print(f"{'변형':24} {'거래':>6} {'승률':>7} {'평균수익':>9} {'평균손실':>9} {'약세장(21-22)평균':>16}")
    print("-" * 96)
    for r in res["rows"]:
        print(f"{r['name']:24} {r['trades']:>6} {r['win_rate']*100:>6.1f}% {r['avg_pnl']*100:>+8.2f}% "
              f"{r['avg_loss']*100:>+8.2f}% {r['choppy']*100:>+15.2f}%")
    print("=" * 96)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=100)
    ap.add_argument("--codes", type=str, default=None)
    a = ap.parse_args()
    codes = [c.strip() for c in a.codes.split(",")] if a.codes else None
    _fmt(asyncio.run(run(a.symbols, codes)))


if __name__ == "__main__":
    main()
