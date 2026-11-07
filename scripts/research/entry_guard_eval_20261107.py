#!/usr/bin/env python3
"""SafetyGuard(일일·주간·월간 손실, 연속손실, 시장급락, 일 진입 수) 연결 여부 판정용 수익률 검증.

결정 규칙(실행 전 고정, 2026-11-07):
  V1(SafetyGuard 기본 한도 전부) vs V0(가드 없음 = 현재 라이브의 무효 가드) 비교에서
  dev OOS Sharpe(rf3) 하락이 0.02 이하이고 MDD가 1%p 이상 개선되면 → "연결",
  그 외 → "제거". 개별 가드(V2~V7)는 판정에 쓰지 않고 원인 분해에만 쓴다.

대상: 운영 설정 그대로 — GC live(55/165, stoch 25/20, gap≤8), ADX14≥20 레짐, 잔여현금×10%, 최대 5종목,
same_close, 현금이자(APPROX_KRW_CASH_RATE_SCHEDULE). 후보는 1개(폴드별 선택 없음).
DB 읽기만 한다(KIS 호출·주문·DB 쓰기 없음).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1].parent
_spec = importlib.util.spec_from_file_location(
    "research_suite", REPO / "scripts/research/research_suite_20261106.py"
)
suite = importlib.util.module_from_spec(_spec)
sys.modules["research_suite"] = suite  # dataclass가 모듈을 sys.modules에서 찾는다
assert _spec.loader
_spec.loader.exec_module(suite)

from src.application.domain.backtest.cash_interest import (
    APPROX_KRW_CASH_RATE_SCHEDULE,
)  # noqa: E402
from src.application.domain.backtest.entry_guard import EntryGuardConfig  # noqa: E402
from src.application.domain.backtest.portfolio_parity_engine import (  # noqa: E402
    PortfolioConstraints,
    PortfolioExecutionOptions,
    PortfolioParityEngine,
)
from src.application.domain.backtest.regime_filter import compute_allowed_entry_dates  # noqa: E402
from src.application.domain.backtest.walk_forward_runner import (  # noqa: E402
    WalkForwardCandidate,
    stitch_oos_exposure,
    stitch_oos_segments,
)

ALL_OFF = dict(
    daily_loss_limit=None,
    weekly_loss_limit=None,
    monthly_loss_limit=None,
    max_daily_entries=None,
    max_consecutive_losses_today=None,
    market_crash_threshold=None,
)


def _bench_returns(bench) -> dict[date, float]:
    s = bench.set_index(bench["timestamp"].dt.date)["close"].astype(float)
    return {d: float(r) for d, r in s.pct_change().dropna().items()}


def variants(bench_ret: dict[date, float]) -> dict[str, EntryGuardConfig | None]:
    full = EntryGuardConfig(benchmark_returns=bench_ret)
    only = lambda **kw: replace(
        EntryGuardConfig(**ALL_OFF, benchmark_returns=bench_ret), **kw
    )  # noqa: E731
    return {
        "V0_no_guard": None,
        "V1_safetyguard_all": full,
        "V2_daily_loss_only": only(daily_loss_limit=-0.04),
        "V3_weekly_monthly_only": only(weekly_loss_limit=-0.07, monthly_loss_limit=-0.15),
        "V4_market_crash_only": only(market_crash_threshold=-0.02),
        "V5_max_entries_only": only(max_daily_entries=3),
        "V6_consecutive_only": only(max_consecutive_losses_today=3),
    }


def execution(guard: EntryGuardConfig | None) -> PortfolioExecutionOptions:
    return PortfolioExecutionOptions(cash_interest=APPROX_KRW_CASH_RATE_SCHEDULE, entry_guard=guard)


def run_dev(ctx, name: str, guard) -> dict:
    cand = [
        WalkForwardCandidate("live", suite.gc_config(*suite.GRID["live"]), suite.REGIMES["adx"])
    ]
    summ = suite.run_gc_wf(ctx, "guard", name, candidates=cand, execution=execution(guard))
    return {
        k: summ.get(k)
        for k in (
            "cagr",
            "sharpe",
            "sharpe_rf0",
            "mdd",
            "avg_exposure",
            "trades",
            "excess_cagr_vs_bh",
            "excess_cagr_vs_exposure_matched",
        )
    }


def run_holdout(ctx, guard) -> dict:
    a, b = suite.LOAD_START, suite.HOLDOUT_END
    cal = [d for d in ctx.calendar if a <= d <= b]
    active = next(d for d in cal if d >= suite.HOLDOUT_START)
    syms = [
        s for s in ctx.universe if ctx.panels[s]["timestamp"].iloc[0].date() <= date(2018, 1, 31)
    ]
    sl = {
        s: ctx.panels[s][
            (ctx.panels[s]["timestamp"].dt.date >= a) & (ctx.panels[s]["timestamp"].dt.date <= b)
        ].reset_index(drop=True)
        for s in syms
    }
    allowed = compute_allowed_entry_dates(ctx.bench, suite.REGIMES["adx"])
    res = PortfolioParityEngine(
        suite.gc_config(*suite.GRID["live"]),
        PortfolioConstraints(max_positions=5),
        execution(guard),
    ).run(sl, ctx.bt_config(), active_from=active, entry_allowed_dates=allowed)
    _, dated = stitch_oos_segments([res.result.daily_stats], suite.C0)
    expo = stitch_oos_exposure([res.result.daily_stats])
    summ = suite.summarize(
        dated,
        expo,
        ctx.bench,
        cash_sched=APPROX_KRW_CASH_RATE_SCHEDULE,
        trades={"total_trades": res.result.total_trades},
        dsr={},
    )
    out = {k: summ.get(k) for k in ("cagr", "sharpe", "mdd", "avg_exposure", "trades")}
    out["guard_blocks"] = res.guard_blocks
    return out


def decide(v0: dict, v1: dict) -> dict:
    d_sharpe = (v1["sharpe"] or 0) - (v0["sharpe"] or 0)
    d_mdd = (v1["mdd"] or 0) - (v0["mdd"] or 0)  # MDD는 음수(%) — 양수면 개선
    connect = d_sharpe >= -0.02 and d_mdd >= 1.0
    return {
        "d_sharpe": round(d_sharpe, 4),
        "d_mdd_pp": round(d_mdd, 3),
        "decision": "연결" if connect else "제거",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--refresh-cache", action="store_true")
    ap.add_argument("--out", default=str(REPO / "reports/entry_guard_eval_20261107.json"))
    args = ap.parse_args()
    ctx = suite.make_ctx(suite.load_data(Path(args.cache), args.refresh_cache))
    bench_ret = _bench_returns(ctx.bench)
    result: dict = {"dev": {}, "holdout": {}}
    for name, guard in variants(bench_ret).items():
        result["dev"][name] = run_dev(ctx, name, guard)
        result["holdout"][name] = run_holdout(ctx, guard)
        print(name, "dev", result["dev"][name], "holdout", result["holdout"][name], flush=True)
    result["decision_dev"] = decide(
        result["dev"]["V0_no_guard"], result["dev"]["V1_safetyguard_all"]
    )
    result["decision_holdout_check"] = decide(
        result["holdout"]["V0_no_guard"], result["holdout"]["V1_safetyguard_all"]
    )
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    print(
        "DECISION",
        json.dumps(result["decision_dev"], ensure_ascii=False),
        "HOLDOUT",
        json.dumps(result["decision_holdout_check"], ensure_ascii=False),
    )


if __name__ == "__main__":
    main()
