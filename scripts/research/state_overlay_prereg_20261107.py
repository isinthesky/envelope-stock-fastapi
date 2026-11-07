#!/usr/bin/env python3
"""사전 등록 오버레이 검증 1회 실행 (docs/plans/state-overlay-preregistration.md).

입력: reports/data/index_daily_{2001,0001}.csv (date, close) — KIS 업종 일봉
출력: reports/state_overlay_prereg_result.{md,json}
DB/KIS 호출 없음. 결과 확인 후 규칙을 바꿔 재실행하면 사후(탐색) 결과다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from src.application.domain.backtest.state_overlay import (
    RULES,
    OverlayConfig,
    block_bootstrap_sharpe_diff,
    daily_returns,
    evaluate_gates,
    metrics,
    static_mix_returns,
)

ROOT = Path(__file__).resolve().parents[2]
PREREG = ROOT / "docs/plans/state-overlay-preregistration.md"
CASH_RATES = {
    2001: 0.050, 2002: 0.048, 2003: 0.043, 2004: 0.038, 2005: 0.036, 2006: 0.044,
    2007: 0.050, 2008: 0.055, 2009: 0.026, 2010: 0.027, 2011: 0.034, 2012: 0.030,
    2013: 0.027, 2014: 0.024, 2015: 0.017, 2016: 0.015, 2017: 0.014,
}  # fmt: skip
EVAL_START, EVAL_END = "2002-01-02", "2017-12-28"
SUBPERIODS = {
    "P1": ("2002-01-01", "2007-12-31"),
    "P2": ("2008-01-01", "2012-12-31"),
    "P3": ("2013-01-01", "2017-12-31"),
}
WARMUP = 200


def _load(code: str, data_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(data_dir / f"index_daily_{code}.csv", parse_dates=["date"])
    return df.sort_values("date").drop_duplicates("date").reset_index(drop=True)


def _window(daily: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    return daily[(daily["date"] >= start) & (daily["date"] <= end)].reset_index(drop=True)


def _rnd(m: dict) -> dict:
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}


def run_series(frame: pd.DataFrame, config: OverlayConfig) -> dict:
    start = EVAL_START
    if frame["date"].iloc[0] > pd.Timestamp("2001-01-31"):
        start = str(frame["date"].iloc[min(WARMUP, len(frame) - 1)].date())  # 사전등록 §2 대체 규칙
    close = frame["close"].astype(float)
    full = {k: daily_returns(frame, fn(close), CASH_RATES, config) for k, fn in RULES.items()}
    win = {k: _window(v, start, EVAL_END) for k, v in full.items()}
    res = {k: metrics(v) for k, v in win.items()}
    xm = static_mix_returns(win["BH"], res["S1"]["avg_exposure"], CASH_RATES, config)
    res["XM"] = metrics(xm)
    sub = {}
    for name, (a, b) in SUBPERIODS.items():
        a = max(a, start)
        s1, bh = metrics(_window(win["S1"], a, b)), metrics(_window(win["BH"], a, b))
        sub[name] = {"S1": _rnd(s1), "BH": _rnd(bh), "G1": s1["mdd"] >= bh["mdd"] + 0.10}
    point, lo, hi = block_bootstrap_sharpe_diff(win["S1"], win["BH"])
    gates = evaluate_gates(res["S1"], res["BH"], res["XM"], [v["G1"] for v in sub.values()])
    return {
        "eval_start": start,
        "eval_end": str(win["BH"]["date"].iloc[-1].date()),
        "metrics": {k: _rnd(v) for k, v in res.items()},
        "subperiods": sub,
        "sharpe_diff_S1_minus_BH": {"point": round(point, 4), "ci95": [round(lo, 4), round(hi, 4)]},
        "gates": gates,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(ROOT / "reports/data"))
    ap.add_argument("--out-dir", default=str(ROOT / "reports"))
    args = ap.parse_args()
    data_dir, out_dir = Path(args.data_dir), Path(args.out_dir)

    prereg_hash = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    recorded = (out_dir / "state_overlay_prereg.sha256").read_text().split()[0]
    primary_cfg = OverlayConfig(cost_rate=0.0005, dividend_yield=0.017)

    result: dict = {
        "prereg_sha256": prereg_hash,
        "prereg_hash_matches_recorded": prereg_hash == recorded,
        "primary": {},
        "sensitivity": {},
        "robustness": {},
    }
    kospi200 = _load("2001", data_dir)
    result["data"] = {
        "2001_first": str(kospi200["date"].iloc[0].date()),
        "2001_last": str(kospi200["date"].iloc[-1].date()),
        "2001_rows": len(kospi200),
        "big_moves_gt15pct": int((kospi200["close"].pct_change().abs() > 0.15).sum()),
    }
    result["primary"] = run_series(kospi200, primary_cfg)
    for label, cfg in {
        "dividend_0": OverlayConfig(cost_rate=0.0005, dividend_yield=0.0),
        "cash_minus_1pp": OverlayConfig(cost_rate=0.0005, dividend_yield=0.017, cash_rate_shift=-0.01),
        "cash_plus_1pp": OverlayConfig(cost_rate=0.0005, dividend_yield=0.017, cash_rate_shift=0.01),
    }.items():
        r = run_series(kospi200, cfg)
        result["sensitivity"][label] = {"metrics": r["metrics"], "gates": r["gates"]}
    kospi_path = data_dir / "index_daily_0001.csv"
    if kospi_path.exists():
        r = run_series(_load("0001", data_dir), primary_cfg)
        result["robustness"]["KOSPI_0001"] = {"metrics": r["metrics"], "gates": r["gates"]}

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "state_overlay_prereg_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1)
    )
    (out_dir / "state_overlay_prereg_result.md").write_text(_to_md(result))
    print(json.dumps({"verdict": result["primary"]["gates"], "hash_ok": result["prereg_hash_matches_recorded"]}))


def _to_md(r: dict) -> str:
    p = r["primary"]
    lines = [
        "# State Overlay 사전등록 검증 결과",
        "",
        f"- 사전등록 해시 일치: {r['prereg_hash_matches_recorded']} (`{r['prereg_sha256'][:16]}…`)",
        f"- 데이터: KOSPI200 {r['data']['2001_first']}~{r['data']['2001_last']} ({r['data']['2001_rows']}행)",
        f"- 평가 구간: {p['eval_start']} ~ {p['eval_end']}",
        "",
        "| 규칙 | CAGR | Sharpe | MDD | 평균노출 | 전환 | 최장회복(일) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for k in ["BH", "S1", "S2", "S3", "XM"]:
        m = p["metrics"][k]
        lines.append(
            f"| {k} | {m['cagr']*100:.2f}% | {m['sharpe']:.2f} | {m['mdd']*100:.1f}% | "
            f"{m['avg_exposure']:.2f} | {m['switches']} | {m['longest_recovery_days']} |"
        )
    d = p["sharpe_diff_S1_minus_BH"]
    lines += [
        "",
        f"- Sharpe(S1)−Sharpe(BH): {d['point']:.3f}, 95% CI [{d['ci95'][0]:.3f}, {d['ci95'][1]:.3f}]",
        f"- 판정: {p['gates']}",
        "",
        "## 하위 구간 (S1 vs BH)",
        "",
        "| 구간 | S1 CAGR | BH CAGR | S1 MDD | BH MDD | G1 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for name, v in p["subperiods"].items():
        lines.append(
            f"| {name} | {v['S1']['cagr']*100:.2f}% | {v['BH']['cagr']*100:.2f}% | "
            f"{v['S1']['mdd']*100:.1f}% | {v['BH']['mdd']*100:.1f}% | {v['G1']} |"
        )
    lines += ["", "## 민감도 / 견고성 (판정 미사용)", ""]
    for label, v in {**r["sensitivity"], **r["robustness"]}.items():
        s1, bh = v["metrics"]["S1"], v["metrics"]["BH"]
        lines.append(
            f"- {label}: S1 CAGR {s1['cagr']*100:.2f}% / Sharpe {s1['sharpe']:.2f} / MDD {s1['mdd']*100:.1f}%"
            f" vs BH {bh['cagr']*100:.2f}% / {bh['sharpe']:.2f} / {bh['mdd']*100:.1f}% → {v['gates']['verdict']}"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
