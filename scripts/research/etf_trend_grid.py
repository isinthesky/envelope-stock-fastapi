#!/usr/bin/env python3
"""ETF 추세추종(듀얼 MA 골든/데드크로스) 9-type 그리드 백테스트.

부드러운 ETF엔 역추세(fear-buy)보다 추세추종이 적합하다는 가설 검증용.
- 진입: MA_short 상향돌파(golden cross)
- 청산: MA_short 하향돌파(death cross), 또는 데이터 끝
- 9 type: short ∈ {10,20,50} × long ∈ {60,120,200}

Run: ./.venv/bin/python -m scripts.etf_trend_grid --codes "069500,..."
"""
import argparse
import asyncio

import pandas as pd

from src.adapters.database.connection import get_async_session
from scripts.research.fear_buy_acceptance import _top_symbols, _load_symbol

SHORTS = [10, 20, 50]
LONGS = [60, 120, 200]


def _simulate(symdata, short, long_):
    closed = []  # (pnl, hold_days)
    for cl in symdata:
        s = pd.Series(cl)
        ma_s = s.rolling(short).mean()
        ma_l = s.rolling(long_).mean()
        pos = None  # (entry_idx, entry_price)
        n = len(cl)
        for t in range(long_, n):
            if pd.isna(ma_s[t]) or pd.isna(ma_l[t]) or pd.isna(ma_s[t - 1]) or pd.isna(ma_l[t - 1]):
                continue
            gc = ma_s[t] > ma_l[t] and ma_s[t - 1] <= ma_l[t - 1]
            dc = ma_s[t] < ma_l[t] and ma_s[t - 1] >= ma_l[t - 1]
            if pos is None:
                if gc:
                    pos = (t, cl[t])
            else:
                if dc or t == n - 1:
                    ei, ep = pos
                    closed.append(((cl[t] - ep) / ep, t - ei))
                    pos = None
    pnls = [c[0] for c in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    holds = [c[1] for c in closed]
    return {
        "trades": len(closed),
        "win_rate": (len(wins) / len(pnls)) if pnls else 0.0,
        "avg_pnl": (sum(pnls) / len(pnls)) if pnls else 0.0,
        "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "avg_hold": (sum(holds) / len(holds)) if holds else 0.0,
    }


async def run(n_symbols, lookback_min, codes=None):
    async with get_async_session() as session:
        syms = codes if codes else await _top_symbols(session, n_symbols)
        symdata = []
        for sym in syms:
            df = await _load_symbol(session, sym)
            if len(df) >= lookback_min:
                symdata.append(df["close"].tolist())
    rows = []
    tno = 0
    for short in SHORTS:
        for long_ in LONGS:
            tno += 1
            m = _simulate(symdata, short, long_)
            rows.append({"type": f"T{tno}", "short": short, "long": long_, **m})
    return {"symbols": len(symdata), "rows": rows}


def _fmt(res):
    rows = res["rows"]
    print("=" * 96)
    print(f"ETF 추세추종(듀얼 MA 골든/데드크로스) 9-TYPE GRID  (symbols={res['symbols']})")
    print("=" * 96)
    best_wr = max(rows, key=lambda r: (r["win_rate"], r["trades"]))
    best_pnl = max(rows, key=lambda r: r["avg_pnl"])
    print(f"{'Type':4} {'MA단':>5} {'MA장':>5} {'거래':>6} {'승률':>7} {'평균수익':>9} {'평균익':>8} {'평균손':>8} {'보유일':>7}")
    print("-" * 96)
    for r in rows:
        mark = (" ★승률" if r["type"] == best_wr["type"] else "") + (" ◆수익" if r["type"] == best_pnl["type"] else "")
        print(f"{r['type']:4} {r['short']:>5} {r['long']:>5} {r['trades']:>6} {r['win_rate']*100:>6.1f}% "
              f"{r['avg_pnl']*100:>+8.2f}% {r['avg_win']*100:>+7.2f}% {r['avg_loss']*100:>+7.2f}% {r['avg_hold']:>6.0f}"
              f"{mark}")
    print("-" * 96)
    print(f"★ 최고 승률 : {best_wr['type']} (MA{best_wr['short']}/{best_wr['long']}) → 승률 {best_wr['win_rate']*100:.1f}%, "
          f"평균 {best_wr['avg_pnl']*100:+.2f}%, {best_wr['trades']}거래")
    print(f"◆ 최고 수익 : {best_pnl['type']} (MA{best_pnl['short']}/{best_pnl['long']}) → 평균 {best_pnl['avg_pnl']*100:+.2f}%, "
          f"승률 {best_pnl['win_rate']*100:.1f}%, {best_pnl['trades']}거래")
    print("=" * 96)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=100)
    ap.add_argument("--codes", type=str, default=None)
    a = ap.parse_args()
    codes = [c.strip() for c in a.codes.split(",")] if a.codes else None
    res = asyncio.run(run(a.symbols, 210, codes))
    _fmt(res)


if __name__ == "__main__":
    main()
