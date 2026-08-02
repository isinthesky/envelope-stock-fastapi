#!/usr/bin/env python3
"""ETF 추세추종 walk-forward 검증.

인샘플 최적화(9 type 중 최고 선택)가 out-of-sample에서 유지되는지 검증.
- 각 test 연도 Y: train = Y 이전 전체 거래(expanding) → 최고 avg_pnl type 선택
  → 그 type의 Y년 진입 거래로 OOS 평가.
- T8(MA50/120)·T9(MA50/200) 고정 성과의 연도별 안정성도 출력.

Run: ./.venv/bin/python -m scripts.etf_trend_walkforward --codes "069500,..."
"""
import argparse
import asyncio

import pandas as pd

from src.adapters.database.connection import get_async_session
from scripts.research.fear_buy_acceptance import _top_symbols, _load_symbol

TYPES = [(s, l) for s in (10, 20, 50) for l in (60, 120, 200)]  # 9


def _trades_for_type(symdata, short, long_):
    """type별 전체 거래 (entry_year, pnl) 리스트."""
    out = []
    for closes, dates in symdata:
        s = pd.Series(closes)
        ma_s = s.rolling(short).mean()
        ma_l = s.rolling(long_).mean()
        pos = None
        n = len(closes)
        for t in range(long_, n):
            if pd.isna(ma_s[t]) or pd.isna(ma_l[t]) or pd.isna(ma_s[t - 1]) or pd.isna(ma_l[t - 1]):
                continue
            gc = ma_s[t] > ma_l[t] and ma_s[t - 1] <= ma_l[t - 1]
            dc = ma_s[t] < ma_l[t] and ma_s[t - 1] >= ma_l[t - 1]
            if pos is None:
                if gc:
                    pos = (t, closes[t])
            elif dc or t == n - 1:
                _, ep = pos
                out.append((dates[t].year if hasattr(dates[t], "year") else dates[pos[0]].year,
                            (closes[t] - ep) / ep, dates[pos[0]].year))
                pos = None
    # (진입연도, pnl) — 진입연도 기준 귀속
    return [(entry_y, pnl) for (_, pnl, entry_y) in out]


def _metrics(pnls):
    if not pnls:
        return {"trades": 0, "win_rate": 0.0, "avg_pnl": 0.0}
    wins = sum(1 for p in pnls if p > 0)
    return {"trades": len(pnls), "win_rate": wins / len(pnls), "avg_pnl": sum(pnls) / len(pnls)}


async def run(n_symbols, codes=None):
    async with get_async_session() as session:
        syms = codes if codes else await _top_symbols(session, n_symbols)
        symdata = []
        for sym in syms:
            df = await _load_symbol(session, sym)
            if len(df) >= 210:
                symdata.append((df["close"].tolist(), df["d"].tolist()))

    # type별 (진입연도,pnl)
    by_type = {}
    for (short, long_) in TYPES:
        by_type[(short, long_)] = _trades_for_type(symdata, short, long_)

    years = sorted({y for tr in by_type.values() for (y, _) in tr})
    test_years = [y for y in years if y >= min(years) + 1]  # 첫해는 train 부족

    wf_oos = []  # 선택전략 OOS 거래
    rows = []
    MIN_TRAIN = 15
    for Y in test_years:
        # train: Y 이전 전체
        best, best_pnl = None, -1e9
        for k, tr in by_type.items():
            train = [p for (y, p) in tr if y < Y]
            if len(train) >= MIN_TRAIN:
                ap = sum(train) / len(train)
                if ap > best_pnl:
                    best_pnl, best = ap, k
        if best is None:
            continue
        test = [p for (y, p) in by_type[best] if y == Y]
        m = _metrics(test)
        wf_oos.extend(test)
        rows.append({"year": Y, "picked": best, "train_avg": best_pnl, **m})

    return {
        "symbols": len(symdata),
        "wf_rows": rows,
        "wf_oos": _metrics(wf_oos),
        "fixed": {
            "T8(50/120)": {y: _metrics([p for (yy, p) in by_type[(50, 120)] if yy == y]) for y in test_years},
            "T9(50/200)": {y: _metrics([p for (yy, p) in by_type[(50, 200)] if yy == y]) for y in test_years},
        },
        "insample": {
            "T8(50/120)": _metrics([p for (_, p) in by_type[(50, 120)]]),
            "T9(50/200)": _metrics([p for (_, p) in by_type[(50, 200)]]),
        },
    }


def _fmt(res):
    print("=" * 90)
    print(f"ETF 추세추종 WALK-FORWARD 검증 (symbols={res['symbols']})")
    print("=" * 90)
    print("[A] 매년 train(직전 전체)에서 best MA-type 선택 → 해당연도 OOS 평가")
    print(f"{'연도':>6} {'선택MA':>10} {'train평균':>9} {'OOS거래':>7} {'OOS승률':>8} {'OOS수익':>8}")
    print("-" * 90)
    for r in res["wf_rows"]:
        ma = f"{r['picked'][0]}/{r['picked'][1]}"
        print(f"{r['year']:>6} {ma:>10} {r['train_avg']*100:>+8.2f}% "
              f"{r['trades']:>7} {r['win_rate']*100:>7.1f}% {r['avg_pnl']*100:>+7.2f}%")
    o = res["wf_oos"]
    print("-" * 90)
    print(f"  ▶ Walk-forward OOS 종합: {o['trades']}거래, 승률 {o['win_rate']*100:.1f}%, 평균 {o['avg_pnl']*100:+.2f}%")
    print()
    print("[B] 고정 전략 연도별 안정성")
    for name, per in res["fixed"].items():
        ins = res["insample"][name]
        segs = " | ".join(f"{y}:{m['win_rate']*100:.0f}%/{m['avg_pnl']*100:+.0f}%({m['trades']})" for y, m in per.items())
        print(f"  {name} [인샘플 전체 {ins['win_rate']*100:.1f}%/{ins['avg_pnl']*100:+.1f}%, {ins['trades']}]")
        print(f"     {segs}")
    print("=" * 90)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=100)
    ap.add_argument("--codes", type=str, default=None)
    a = ap.parse_args()
    codes = [c.strip() for c in a.codes.split(",")] if a.codes else None
    _fmt(asyncio.run(run(a.symbols, codes)))


if __name__ == "__main__":
    main()
