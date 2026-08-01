#!/usr/bin/env python3
"""ETF 추세추종 + 레짐필터 walk-forward 검증.

레짐필터 개선이 인샘플 편향(2022 회피)인지, 진짜 OOS에서 유지되는지 검증.
- 18 설정 = 9 MA쌍 × {R0 무필터, R1 레짐게이트(KOSPI>MA200)}.
- 매 test 연도: 직전 전체(expanding)에서 best avg_pnl 설정 선택 → 해당연도 OOS 평가.
- MA50/200 R0 vs R1 연도별 고정 성과도 비교(레짐필터 기여의 시점 안정성).

Run: ./.venv/bin/python -m scripts.etf_trend_regime_walkforward --codes "069500,..."
"""
import argparse
import asyncio

import pandas as pd

from src.adapters.database.connection import get_async_session
from scripts.fear_buy_acceptance import _top_symbols, _load_symbol
from src.application.domain.strategy.ohlcv_data_loader import get_kospi_or_proxy_closes

REGIME_MA = 200
MA_PAIRS = [(s, l) for s in (10, 20, 50) for l in (60, 120, 200)]
VARIANTS = ["R0", "R1"]  # R0 무필터, R1 레짐 진입게이트


def _regime_by_date(m_closes, m_ts):
    ma = pd.Series(m_closes).rolling(REGIME_MA).mean()
    dates = [pd.Timestamp(t).date() for t in m_ts]
    return {dates[i]: ((not pd.isna(ma[i])) and m_closes[i] > ma[i]) for i in range(len(m_closes))}


def _trades(symdata, short, long_, variant, regime):
    out = []  # (entry_year, pnl)
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
            up = regime.get(dates[t], True)
            if pos is None:
                if gc and (variant == "R0" or up):
                    pos = (t, closes[t])
            elif dc or t == n - 1:
                out.append((dates[pos[0]].year, (closes[t] - pos[1]) / pos[1]))
                pos = None
    return out


def _m(pnls):
    if not pnls:
        return {"trades": 0, "win_rate": 0.0, "avg_pnl": 0.0}
    return {"trades": len(pnls), "win_rate": sum(1 for p in pnls if p > 0) / len(pnls),
            "avg_pnl": sum(pnls) / len(pnls)}


async def run(n_symbols, codes=None):
    async with get_async_session() as session:
        m_closes, m_ts, _ = await get_kospi_or_proxy_closes(session, days=2600)
        regime = _regime_by_date(m_closes, m_ts)
        syms = codes if codes else await _top_symbols(session, n_symbols)
        symdata = []
        for sym in syms:
            df = await _load_symbol(session, sym)
            if len(df) >= 210:
                symdata.append((df["close"].tolist(), df["d"].tolist()))

    cfg = {}
    for (s, l) in MA_PAIRS:
        for v in VARIANTS:
            cfg[(s, l, v)] = _trades(symdata, s, l, v, regime)

    years = sorted({y for tr in cfg.values() for (y, _) in tr})
    test_years = [y for y in years if y >= min(years) + 1]

    wf, rows = [], []
    MIN_TRAIN = 15
    for Y in test_years:
        best, bp = None, -1e9
        for k, tr in cfg.items():
            train = [p for (y, p) in tr if y < Y]
            if len(train) >= MIN_TRAIN:
                ap = sum(train) / len(train)
                if ap > bp:
                    bp, best = ap, k
        if best is None:
            continue
        test = [p for (y, p) in cfg[best] if y == Y]
        wf.extend(test)
        rows.append({"year": Y, "pick": best, "train_avg": bp, **_m(test)})

    def per_year(key):
        return {y: _m([p for (yy, p) in cfg[key] if yy == y]) for y in test_years}

    return {
        "symbols": len(symdata), "rows": rows, "oos": _m(wf),
        "fixed": {
            "MA50/200 무필터": (per_year((50, 200, "R0")), _m([p for (_, p) in cfg[(50, 200, "R0")]])),
            "MA50/200 레짐게이트": (per_year((50, 200, "R1")), _m([p for (_, p) in cfg[(50, 200, "R1")]])),
        },
    }


def _fmt(res):
    print("=" * 92)
    print(f"ETF 추세추종+레짐필터 WALK-FORWARD (symbols={res['symbols']}, 18설정=9MA×{{무필터,레짐게이트}})")
    print("=" * 92)
    print("[A] 매년 직전데이터 best 설정 선택 → 해당연도 OOS")
    print(f"{'연도':>6} {'선택설정':>16} {'train평균':>9} {'OOS거래':>7} {'OOS승률':>8} {'OOS수익':>8}")
    print("-" * 92)
    for r in res["rows"]:
        s, l, v = r["pick"]
        lbl = f"MA{s}/{l}·{'레짐' if v == 'R1' else '무필터'}"
        print(f"{r['year']:>6} {lbl:>16} {r['train_avg']*100:>+8.2f}% {r['trades']:>7} "
              f"{r['win_rate']*100:>7.1f}% {r['avg_pnl']*100:>+7.2f}%")
    o = res["oos"]
    print("-" * 92)
    print(f"  ▶ Walk-forward OOS 종합: {o['trades']}거래, 승률 {o['win_rate']*100:.1f}%, 평균 {o['avg_pnl']*100:+.2f}%")
    print()
    print("[B] MA50/200 무필터 vs 레짐게이트 — 연도별 (레짐신호는 과거만 사용=인과적)")
    for name, (per, ins) in res["fixed"].items():
        segs = " | ".join(f"{y}:{m['win_rate']*100:.0f}%/{m['avg_pnl']*100:+.0f}%({m['trades']})" for y, m in per.items())
        print(f"  {name} [전체 {ins['win_rate']*100:.1f}%/{ins['avg_pnl']*100:+.1f}%, {ins['trades']}]")
        print(f"     {segs}")
    print("=" * 92)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=100)
    ap.add_argument("--codes", type=str, default=None)
    a = ap.parse_args()
    codes = [c.strip() for c in a.codes.split(",")] if a.codes else None
    _fmt(asyncio.run(run(a.symbols, codes)))


if __name__ == "__main__":
    main()
