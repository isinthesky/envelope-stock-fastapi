#!/usr/bin/env python3
"""사전 등록 레버리지 오버레이 검증 1회 실행 (docs/plans/leverage-overlay-preregistration.md).

입력: reports/data/index_daily_0001_1990s.csv, index_daily_2001_1990s.csv (D1, D2 — 신규)
      reports/data/index_daily_2001.csv (D3 — 2001~2017, 재사용)
출력: reports/leverage_overlay_prereg_result.{md,json}
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from src.application.domain.backtest.leverage_overlay import (
    RULES,
    LeverageConfig,
    daily_returns,
    evaluate_gates,
    yearly_returns,
)
from src.application.domain.backtest.state_overlay import metrics

ROOT = Path(__file__).resolve().parents[2]
PREREG = ROOT / "docs/plans/leverage-overlay-preregistration.md"
RATES = {
    1990: 0.150, 1991: 0.170, 1992: 0.155, 1993: 0.125, 1994: 0.130, 1995: 0.140,
    1996: 0.125, 1997: 0.135, 1998: 0.140, 1999: 0.065, 2000: 0.070,
    2001: 0.050, 2002: 0.048, 2003: 0.043, 2004: 0.038, 2005: 0.036, 2006: 0.044,
    2007: 0.050, 2008: 0.055, 2009: 0.026, 2010: 0.027, 2011: 0.034, 2012: 0.030,
    2013: 0.027, 2014: 0.024, 2015: 0.017, 2016: 0.015, 2017: 0.014,
}  # fmt: skip
WARMUP = 200
DATASETS = {
    "D1": ("index_daily_0001_1990s.csv", None, "2000-12-31"),
    "D2": ("index_daily_2001_1990s.csv", None, "2000-12-31"),
    "D3": ("index_daily_2001.csv", "2002-01-02", "2017-12-28"),
}


def _rnd(m: dict) -> dict:
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}


def run_dataset(path: Path, start: str | None, end: str, cfg: LeverageConfig) -> dict:
    frame = pd.read_csv(path, parse_dates=["date"]).sort_values("date").drop_duplicates("date")
    frame = frame[frame["date"] <= end].reset_index(drop=True)
    eval_start = start or str(frame["date"].iloc[WARMUP].date())
    close = frame["close"].astype(float)
    out = {}
    for name, rule in RULES.items():
        daily = daily_returns(frame, rule(close), RATES, cfg)
        win = daily[daily["date"] >= eval_start].reset_index(drop=True)
        out[name] = {"metrics": _rnd(metrics(win)), "yearly": {y: round(v, 4) for y, v in yearly_returns(win).items()}}
    return {"eval_start": eval_start, "eval_end": str(frame["date"].iloc[-1].date()), "rules": out}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(ROOT / "reports/data"))
    ap.add_argument("--out-dir", default=str(ROOT / "reports"))
    ap.add_argument("--hash-file", default=str(ROOT / "docs/plans/leverage-overlay-preregistration.sha256"))
    args = ap.parse_args()
    data_dir, out_dir = Path(args.data_dir), Path(args.out_dir)

    prereg_hash = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    recorded = Path(args.hash_file).read_text().split()[0]
    primary = LeverageConfig()
    result: dict = {"prereg_sha256": prereg_hash, "prereg_hash_matches_recorded": prereg_hash == recorded}

    runs = {k: run_dataset(data_dir / f, s, e, primary) for k, (f, s, e) in DATASETS.items()}
    result["primary"] = runs
    d1 = {k: runs["D1"]["rules"][k]["metrics"] for k in ("L1", "L3", "BH")}
    beats = [runs[k]["rules"]["L1"]["metrics"]["cagr"] > runs[k]["rules"]["BH"]["metrics"]["cagr"] for k in runs]
    result["gates"] = evaluate_gates(d1, beats)
    result["cagr_beats_bh_by_dataset"] = dict(zip(runs.keys(), beats))

    sens = {
        "dividend_0": LeverageConfig(dividend_yield=0.0),
        "rates_minus_2pp": LeverageConfig(rate_shift=-0.02),
        "rates_plus_2pp": LeverageConfig(rate_shift=0.02),
        "borrow_spread_1pp": LeverageConfig(borrow_spread=0.01),
    }
    result["sensitivity"] = {}
    for label, cfg in sens.items():
        runs_s = {k: run_dataset(data_dir / f, s, e, cfg) for k, (f, s, e) in DATASETS.items()}
        d1s = {k: runs_s["D1"]["rules"][k]["metrics"] for k in ("L1", "L3", "BH")}
        beats_s = [runs_s[k]["rules"]["L1"]["metrics"]["cagr"] > runs_s[k]["rules"]["BH"]["metrics"]["cagr"] for k in runs_s]
        result["sensitivity"][label] = {
            "gates": evaluate_gates(d1s, beats_s),
            "D1": {k: runs_s["D1"]["rules"][k]["metrics"] for k in RULES},
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "leverage_overlay_prereg_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    (out_dir / "leverage_overlay_prereg_result.md").write_text(_to_md(result))
    print(json.dumps({"gates": result["gates"], "hash_ok": result["prereg_hash_matches_recorded"]}))


def _to_md(r: dict) -> str:
    lines = [
        "# Leverage Overlay 사전등록 검증 결과",
        "",
        f"- 사전등록 해시 일치: {r['prereg_hash_matches_recorded']} (`{r['prereg_sha256'][:16]}…`)",
        f"- 판정: {r['gates']}",
        f"- 데이터셋별 CAGR(L1) > CAGR(BH): {r['cagr_beats_bh_by_dataset']}",
        "",
    ]
    for ds, run in r["primary"].items():
        lines += [
            f"## {ds} ({run['eval_start']} ~ {run['eval_end']})",
            "",
            "| 규칙 | CAGR | Sharpe | MDD | 평균노출 | 전환 | 최장회복(일) |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for name, v in run["rules"].items():
            m = v["metrics"]
            lines.append(
                f"| {name} | {m['cagr']*100:.2f}% | {m['sharpe']:.2f} | {m['mdd']*100:.1f}% | "
                f"{m['avg_exposure']:.2f} | {m['switches']} | {m['longest_recovery_days']} |"
            )
        years = sorted(run["rules"]["BH"]["yearly"])
        lines += ["", "| 연도 | " + " | ".join(run["rules"]) + " |", "|---|" + "---:|" * len(run["rules"])]
        for y in years:
            lines.append(f"| {y} | " + " | ".join(f"{run['rules'][n]['yearly'].get(y, float('nan'))*100:.1f}%" for n in run["rules"]) + " |")
        lines.append("")
    lines += ["## 민감도 (판정 미사용, D1 L1 vs BH)", ""]
    for label, v in r["sensitivity"].items():
        l1, bh = v["D1"]["L1"], v["D1"]["BH"]
        lines.append(
            f"- {label}: L1 CAGR {l1['cagr']*100:.2f}% / MDD {l1['mdd']*100:.1f}% vs BH {bh['cagr']*100:.2f}% / "
            f"{bh['mdd']*100:.1f}% → {v['gates']['verdict']}"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
