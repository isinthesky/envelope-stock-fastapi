#!/usr/bin/env python3
"""Fear Buy 매수조건 9-type 그리드 백테스트 (3년, 실 KOSPI).

매수 개별조건을 RSI임계 × 하락률 3×3 = 9 type으로 확대해 비교.
- 시장 공포 윈도우(window=7)는 공통, exit는 운영 compute_simple_sell_signal 공통.
- 데이터/지표는 1회만 로드·계산 후 9 type 재사용.

Run: ./.venv/bin/python scripts/fear_buy_grid.py --symbols 100 --window 7 --lookback 120
"""
import argparse
import asyncio

import pandas as pd

from src.adapters.database.connection import get_async_session
from src.application.common.indicators import TechnicalIndicators as TI
from src.application.domain.strategy.ohlcv_data_loader import get_kospi_or_proxy_closes
from src.application.domain.strategy.sell_strategy_service import SellStrategyService
from scripts.research.fear_buy_acceptance import (
    _top_symbols,
    _load_symbol,
    _market_fear_window_by_date,
)

RSI_THRESHOLDS = [25.0, 30.0, 35.0]
DROP_PCTS = [0.10, 0.15, 0.20]


def _simulate(svc, symdata, fear_win, rsi_th, drop_pct):
    """한 type(rsi_th, drop_pct)에 대해 전 심볼 진입/청산 시뮬레이션."""
    individual = 0
    combined = 0
    closed = []
    for d in symdata:
        dates, cl, rsi, roll_high, df = d["dates"], d["cl"], d["rsi"], d["roll_high"], d["df"]
        lookback = d["lookback"]
        pos = None
        n = len(cl)
        for t in range(lookback, n):
            if pos is None:
                r, rh = rsi[t], roll_high[t]
                if r is None or pd.isna(r) or rh is None or pd.isna(rh):
                    continue
                if (r <= rsi_th) and (cl[t] <= rh * (1 - drop_pct)):
                    individual += 1
                    if fear_win.get(dates[t], False):
                        combined += 1
                        pos = (t, cl[t], cl[t])
            else:
                _, entry_p, high = pos
                high = max(high, cl[t])
                win_df = df.iloc[max(0, t - 5): t + 1][["close"]]
                sig = svc.compute_simple_sell_signal(
                    df=win_df, rsi=rsi[t] if rsi[t] is not None else 50.0,
                    current_price=cl[t], entry_price=entry_p, highest_price=high,
                )
                if sig["should_sell"] or t == n - 1:
                    closed.append((cl[t] - entry_p) / entry_p)
                    pos = None
    wins = sum(1 for p in closed if p > 0)
    losses = [p for p in closed if p <= 0]
    win_list = [p for p in closed if p > 0]
    return {
        "individual": individual,
        "combined": combined,
        "trades": len(closed),
        "win_rate": (wins / len(closed)) if closed else 0.0,
        "avg_pnl": (sum(closed) / len(closed)) if closed else 0.0,
        "avg_win": (sum(win_list) / len(win_list)) if win_list else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
    }


async def run(n_symbols: int, window: int, lookback: int, codes: list[str] | None = None):
    svc = SellStrategyService(session=None)
    async with get_async_session() as session:
        syms = codes if codes else await _top_symbols(session, n_symbols)
        m_closes, m_ts, m_src = await get_kospi_or_proxy_closes(session, days=2600)
        fear_win = _market_fear_window_by_date(m_closes, m_ts, window)
        fear_days = sum(1 for v in fear_win.values() if v)

        # 심볼별 지표 1회 계산 (type 무관)
        symdata = []
        for sym in syms:
            df = await _load_symbol(session, sym)
            if len(df) < lookback + 5:
                continue
            closes = df["close"]
            symdata.append({
                "df": df,
                "dates": df["d"].tolist(),
                "cl": closes.tolist(),
                "rsi": TI.calculate_rsi_series(df, 14).tolist(),
                "roll_high": closes.rolling(lookback, min_periods=lookback).max().tolist(),
                "lookback": lookback,
            })

    rows = []
    tno = 0
    for rsi_th in RSI_THRESHOLDS:
        for drop_pct in DROP_PCTS:
            tno += 1
            m = _simulate(svc, symdata, fear_win, rsi_th, drop_pct)
            rows.append({"type": f"T{tno}", "rsi": rsi_th, "drop": drop_pct, **m})

    return {
        "market_source": m_src, "market_days": len(m_closes), "fear_days": fear_days,
        "symbols": len(symdata), "window": window, "lookback": lookback, "rows": rows,
    }


def _fmt(res):
    rows = res["rows"]
    print("=" * 92)
    print(f"FEAR BUY 9-TYPE GRID  (source={res['market_source']}, days={res['market_days']}, "
          f"fear_days={res['fear_days']}, symbols={res['symbols']}, window={res['window']}, "
          f"lookback={res['lookback']})")
    print("=" * 92)
    best_wr = max(rows, key=lambda r: (r["win_rate"], r["trades"]))
    best_pnl = max(rows, key=lambda r: r["avg_pnl"])
    hdr = f"{'Type':4} {'RSI≤':>5} {'Drop≥':>6} {'Trades':>7} {'Win%':>7} {'AvgPnl%':>8} {'AvgWin%':>8} {'AvgLoss%':>9}"
    print(hdr)
    print("-" * 92)
    for r in rows:
        mark = ""
        if r["type"] == best_wr["type"]:
            mark += " ★승률"
        if r["type"] == best_pnl["type"]:
            mark += " ◆수익"
        print(f"{r['type']:4} {r['rsi']:>5.0f} {r['drop']*100:>5.0f}% {r['trades']:>7} "
              f"{r['win_rate']*100:>6.1f}% {r['avg_pnl']*100:>+7.2f}% {r['avg_win']*100:>+7.2f}% "
              f"{r['avg_loss']*100:>+8.2f}%{mark}")
    print("-" * 92)
    print(f"★ 최고 승률 : {best_wr['type']} (RSI≤{best_wr['rsi']:.0f}, Drop≥{best_wr['drop']*100:.0f}%) "
          f"→ 승률 {best_wr['win_rate']*100:.1f}%, 평균 {best_wr['avg_pnl']*100:+.2f}%, {best_wr['trades']}거래")
    print(f"◆ 최고 수익 : {best_pnl['type']} (RSI≤{best_pnl['rsi']:.0f}, Drop≥{best_pnl['drop']*100:.0f}%) "
          f"→ 평균 {best_pnl['avg_pnl']*100:+.2f}%, 승률 {best_pnl['win_rate']*100:.1f}%, {best_pnl['trades']}거래")
    print("=" * 92)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=100)
    ap.add_argument("--window", type=int, default=7)
    ap.add_argument("--lookback", type=int, default=120)
    ap.add_argument("--codes", type=str, default=None, help="쉼표구분 종목코드(지정 시 top-N 대신 사용)")
    a = ap.parse_args()
    codes = [c.strip() for c in a.codes.split(",")] if a.codes else None
    res = asyncio.run(run(a.symbols, a.window, a.lookback, codes))
    _fmt(res)


if __name__ == "__main__":
    main()
