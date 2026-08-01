#!/usr/bin/env python3
"""ETF 추세추종 + 시장 레짐 필터.

추세추종의 약점(횡보/약세장 whipsaw)을 KOSPI 레짐 필터로 완화하는지 검증.
- 레짐 UP = KOSPI 종가 > KOSPI MA200 (장기 상승추세).
- 변형: R0 무필터 / R1 진입게이트(레짐UP일 때만 진입) / R2 진입게이트+레짐이탈 청산.
- base MA: 50/120, 50/200.

Run: ./.venv/bin/python -m scripts.etf_trend_regime --codes "069500,..."
"""
import argparse
import asyncio

import pandas as pd

from src.adapters.database.connection import get_async_session
from scripts.fear_buy_acceptance import _top_symbols, _load_symbol
from src.application.domain.strategy.ohlcv_data_loader import get_kospi_or_proxy_closes

REGIME_MA = 200
CONFIGS = [(50, 120), (50, 200)]
VARIANTS = ["R0", "R1", "R2"]


def _regime_by_date(m_closes, m_ts):
    s = pd.Series(m_closes)
    ma = s.rolling(REGIME_MA).mean()
    dates = [pd.Timestamp(t).date() for t in m_ts]
    reg = {}
    for i in range(len(m_closes)):
        reg[dates[i]] = (not pd.isna(ma[i])) and (m_closes[i] > ma[i])
    return reg


def _sim(symdata, short, long_, variant, regime):
    trades = []  # (entry_year, pnl)
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
            up = regime.get(dates[t], True)  # 레짐(없으면 fail-open)
            if pos is None:
                if gc and (variant == "R0" or up):
                    pos = (t, closes[t])
            else:
                ei, ep = pos
                exit_now = dc or t == n - 1
                if variant == "R2" and not up:  # 레짐 이탈 청산
                    exit_now = True
                if exit_now:
                    trades.append((dates[ei].year, (closes[t] - ep) / ep))
                    pos = None
    return trades


def _metrics(trades):
    pnls = [p for (_, p) in trades]
    if not pnls:
        return {"trades": 0, "win_rate": 0.0, "avg_pnl": 0.0, "avg_loss": 0.0, "choppy": 0.0, "choppy_n": 0}
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    ch = [p for (y, p) in trades if y in (2021, 2022)]
    return {
        "trades": len(pnls),
        "win_rate": len(wins) / len(pnls),
        "avg_pnl": sum(pnls) / len(pnls),
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "choppy": (sum(ch) / len(ch)) if ch else 0.0,
        "choppy_n": len(ch),
    }


async def run(n_symbols, codes=None):
    async with get_async_session() as session:
        m_closes, m_ts, m_src = await get_kospi_or_proxy_closes(session, days=2600)
        regime = _regime_by_date(m_closes, m_ts)
        syms = codes if codes else await _top_symbols(session, n_symbols)
        symdata = []
        for sym in syms:
            df = await _load_symbol(session, sym)
            if len(df) >= 210:
                symdata.append((df["close"].tolist(), df["d"].tolist()))
    reg_days = sum(1 for v in regime.values() if v)
    rows = []
    for (short, long_) in CONFIGS:
        for v in VARIANTS:
            m = _metrics(_sim(symdata, short, long_, v, regime))
            rows.append({"ma": f"{short}/{long_}", "variant": v, **m})
    return {"symbols": len(symdata), "market": m_src, "reg_up_days": reg_days,
            "reg_total": len(regime), "rows": rows}


def _fmt(res):
    vlabel = {"R0": "무필터", "R1": "진입게이트", "R2": "게이트+레짐청산"}
    print("=" * 100)
    print(f"ETF 추세추종 + 시장레짐(KOSPI>MA200) 필터  (symbols={res['symbols']}, "
          f"market={res['market']}, 레짐UP {res['reg_up_days']}/{res['reg_total']}일)")
    print("=" * 100)
    print(f"{'MA':>8} {'변형':16} {'거래':>6} {'승률':>7} {'평균수익':>9} {'평균손실':>9} {'약세장21-22평균(n)':>20}")
    print("-" * 100)
    prev = None
    for r in res["rows"]:
        if prev and prev != r["ma"]:
            print("-" * 100)
        prev = r["ma"]
        print(f"{r['ma']:>8} {vlabel[r['variant']]:16} {r['trades']:>6} {r['win_rate']*100:>6.1f}% "
              f"{r['avg_pnl']*100:>+8.2f}% {r['avg_loss']*100:>+8.2f}% "
              f"{r['choppy']*100:>+13.2f}%({r['choppy_n']})")
    print("=" * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=100)
    ap.add_argument("--codes", type=str, default=None)
    a = ap.parse_args()
    codes = [c.strip() for c in a.codes.split(",")] if a.codes else None
    _fmt(asyncio.run(run(a.symbols, codes)))


if __name__ == "__main__":
    main()
