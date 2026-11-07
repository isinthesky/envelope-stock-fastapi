#!/usr/bin/env python3
"""2026-11-06 수익 가능성 연구 스위트 (H0~H6 + 홀드아웃) — DB 전용, KIS 미호출.

각 실험은 별도 로그/리포트(reports/research_2026-11-06_<exp>.{md,json})로 남기고,
DSR용 누적 시도 수는 reports/research_2026-11-06_trial_ledger.json 에 기록한다
(사전 연구 시도 200회에서 시작, (exp,variant) 단위로 1회만 가산).

실행(컨테이너, compose 네트워크):
  docker run --rm --network kis-strategy-alert-server_kis-network -v <repo>:/work -w /work \
    -e PYTHONPATH=/work -e UV_PROJECT_ENVIRONMENT=/tmp/kis-test-venv \
    -e DATABASE_URL=... (⚠️ --env-file 금지: .env 인라인 주석을 값으로 넘겨 설정 파싱 실패; /work/.env는 settings가 직접 읽음) kis-strategy-alert-server-api \
    uv run python scripts/research/research_suite_20261106.py --exp h0

⚠️ 쓰기 없음(DB read-only). 주문 없음. 캐시 pickle은 --cache 경로(기본 /scratch)에만 쓴다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import pickle
import statistics as _st
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.application.common.performance_metrics import PerformanceMetrics
from src.application.domain.backtest.cash_interest import (
    APPROX_KRW_CASH_RATE_SCHEDULE,
    CashInterestSchedule,
)
from src.application.domain.backtest.dto import BacktestConfigDTO
from src.application.domain.backtest.exit_overlay import ExitOverlay
from src.application.domain.backtest.momentum_rotation import (
    MomentumRotationConfig,
    MomentumRotationEngine,
)
from src.application.domain.backtest.portfolio_parity_engine import (
    PortfolioConstraints,
    PortfolioExecutionOptions,
    PortfolioParityEngine,
)
from src.application.domain.backtest.regime import classify_regimes, decompose_by_regime
from src.application.domain.backtest.regime_filter import (
    RegimeEntryFilter,
    compute_allowed_entry_dates,
)
from src.application.domain.backtest.statistics import (
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
)
from src.application.domain.backtest.walk_forward_runner import (
    WalkForwardCandidate,
    WalkForwardReport,
    WalkForwardRunner,
    stitch_oos_exposure,
    stitch_oos_segments,
)
from src.application.domain.backtest.walk_forward_windows import (
    WalkForwardWindow,
    generate_rolling_windows,
)
from src.application.domain.strategy.dto import (
    GoldenCrossConfigDTO,
    GoldenCrossMAConfig,
    MAGapConfig,
    StochasticConfig,
)

REPO = Path(__file__).resolve().parents[2]
REPORTS = REPO / "reports"
PREFIX = "research_2026-11-06"
LEDGER = REPORTS / f"{PREFIX}_trial_ledger.json"
PRIOR_TRIALS = 200
# 재실행 태그(예: "rerun"): 원장 키와 리포트 파일명에 붙여 이전 결과를 보존하고 시도 수를 별도 가산
SUFFIX = ""
BENCH = "069500"
LOAD_START = date(2018, 1, 1)
DEV_START = date(2020, 1, 1)
DEV_END = date(2026, 11, 6)
HOLDOUT_START = date(2018, 7, 1)
HOLDOUT_END = date(2019, 12, 31)
PRIOR_COVERAGE = REPORTS / "coverage_20260801_210951.json"
C0 = Decimal("10000000")
# 분배금 가정(라벨: 가정치). KODEX200 연 분배수익률 근사.
ASSUMED_DIV_YIELD = (0.015, 0.02)


# ==================== 데이터 ====================
async def _load_from_db() -> dict[str, Any]:
    from sqlalchemy import text

    from src.adapters.database.connection import AsyncSessionLocal
    from src.adapters.database.repositories.ohlcv_repository import OHLCVRepository

    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                text(
                    "select symbol, name, market, is_active from stock_universe "
                    "where market='ETF' order by symbol"
                )
            )
        ).all()
        names = {r[0]: r[1] for r in rows}
        active = [r[0] for r in rows if r[3]]
        want = list(dict.fromkeys([BENCH, *active]))
        repo = OHLCVRepository(s)
        start = datetime(LOAD_START.year, LOAD_START.month, LOAD_START.day, tzinfo=timezone.utc)
        end = datetime(2026, 11, 7, tzinfo=timezone.utc)
        panels: dict[str, pd.DataFrame] = {}
        for i, sym in enumerate(want, 1):
            df = await repo.get_candles_to_dataframe(sym, start, end, "1d")
            if df.empty:
                continue
            df = df.sort_values("timestamp").reset_index(drop=True)
            # tz-aware → naive(KST 날짜 보존: DB는 KST 자정 기준 timestamptz)
            ts = pd.to_datetime(df["timestamp"])
            if getattr(ts.dt, "tz", None) is not None:
                ts = ts.dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
            df["timestamp"] = ts.dt.normalize()
            for c in ("open", "high", "low", "close"):
                df[c] = df[c].astype(float)
            df = df.drop_duplicates("timestamp").reset_index(drop=True)
            panels[sym] = df[["timestamp", "open", "high", "low", "close", "volume"]]
            if i % 50 == 0:
                print(f"  [load] {i}/{len(want)}", flush=True)
    return {"panels": panels, "names": names, "active": active}


def load_data(cache: Path, refresh: bool) -> dict[str, Any]:
    if cache.exists() and not refresh:
        with cache.open("rb") as f:
            return pickle.load(f)
    data = asyncio.run(_load_from_db())
    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.open("wb") as f:
        pickle.dump(data, f)
    return data


def bdates(df: pd.DataFrame) -> list[date]:
    return [ts.date() for ts in df["timestamp"]]


# ==================== 시도 원장(DSR) ====================
def _ledger() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return {"prior_trials": PRIOR_TRIALS, "entries": []}


def reserve_trials(exp: str, variant: str, n: int) -> int:
    """(exp,variant) 최초 1회만 가산하고 누적 시도 수(이번 포함)를 반환. 병렬 실행 대비 flock."""
    import fcntl

    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    lock_path = LEDGER.with_suffix(".lock")
    with lock_path.open("w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        led = _ledger()
        key = f"{exp}{'_' + SUFFIX if SUFFIX else ''}:{variant}"
        if not any(e["key"] == key for e in led["entries"]):
            led["entries"].append(
                {"key": key, "trials": n, "at": datetime.now(timezone.utc).isoformat()}
            )
            LEDGER.write_text(json.dumps(led, ensure_ascii=False, indent=2), encoding="utf-8")
        fcntl.flock(lk, fcntl.LOCK_UN)
    return led["prior_trials"] + sum(e["trials"] for e in led["entries"])


def cumulative_trials() -> int:
    led = _ledger()
    return led["prior_trials"] + sum(e["trials"] for e in led["entries"])


# ==================== 지표 ====================
def _equity_df(dated: list[tuple[Any, float]]) -> tuple[pd.DataFrame, list[float]]:
    eq = [float(C0)]
    for _, r in dated:
        eq.append(eq[-1] * (1.0 + r))
    dts = [dated[0][0]] + [d for d, _ in dated]
    return pd.DataFrame({"timestamp": dts, "equity": eq}), eq


def _core(dated: list[tuple[Any, float]]) -> dict:
    if len(dated) < 2:
        return {}
    df, eq = _equity_df(dated)
    d0, d1 = df["timestamp"].iloc[0], df["timestamp"].iloc[-1]
    years = max((d1 - d0).days / 365.0, 1e-9)
    cagr = ((eq[-1] / eq[0]) ** (1 / years) - 1) * 100
    arr = np.asarray(eq)
    mdd = float((arr / np.maximum.accumulate(arr) - 1).min() * 100)
    return {
        "total_return": round((eq[-1] / eq[0] - 1) * 100, 2),
        "cagr": round(cagr, 2),
        "sharpe": round(PerformanceMetrics.calculate_daily_sharpe_ratio(df, 3.0), 3),
        "sharpe_rf0": round(PerformanceMetrics.calculate_daily_sharpe_ratio(df, 0.0), 3),
        "sortino": round(PerformanceMetrics.calculate_sortino_ratio(df, risk_free_rate=3.0), 3),
        "mdd": round(mdd, 2),
        "days": len(dated),
        "start": str(d0.date() if hasattr(d0, "date") else d0),
        "end": str(d1.date() if hasattr(d1, "date") else d1),
    }


def _bench_returns(bench: pd.DataFrame, on_dates: list[Any]) -> list[tuple[Any, float]]:
    closes = {ts.date(): float(c) for ts, c in zip(bench["timestamp"], bench["close"])}
    cal = sorted(closes)
    pos = {d: i for i, d in enumerate(cal)}
    out = []
    for dt in on_dates:
        d = dt.date() if hasattr(dt, "date") else dt
        i = pos.get(d)
        if i is None or i == 0:
            out.append((dt, 0.0))
            continue
        out.append((dt, closes[d] / closes[cal[i - 1]] - 1.0))
    return out


def _cash_returns(on_dates: list[Any], sched: CashInterestSchedule | None) -> list[float]:
    out = []
    prev = None
    for dt in on_dates:
        d = dt.date() if hasattr(dt, "date") else dt
        out.append(float(sched.accrual_factor(prev, d)) if (sched and prev) else 0.0)
        prev = d
    return out


def summarize(
    dated: list[tuple[Any, float]],
    exposure: list[tuple[Any, float]],
    bench: pd.DataFrame,
    *,
    cash_sched: CashInterestSchedule | None,
    trades: dict | None = None,
    dsr: dict | None = None,
) -> dict:
    core = _core(dated)
    if not core:
        return {"empty": True}
    dates = [d for d, _ in dated]
    avg_exp = float(np.mean([x for _, x in exposure])) if exposure else 0.0
    bh = _bench_returns(bench, dates)
    bh_core = _core(bh)
    cash = _cash_returns(dates, cash_sched)
    blend = [(d, avg_exp * r + (1 - avg_exp) * c) for (d, r), c in zip(bh, cash)]
    blend_core = _core(blend)
    regimes = classify_regimes(bench, long_ma=200)
    decomp = decompose_by_regime(dated, regimes)
    decomp_bh = decompose_by_regime(bh, regimes)
    reg = {
        k: {
            "days": v.n_days,
            "ret": v.total_return,
            "daily_sharpe": v.daily_sharpe,
            "mdd": v.mdd,
            "bh_ret": decomp_bh[k].total_return,
        }
        for k, v in decomp.items()
    }
    lo, hi = ASSUMED_DIV_YIELD
    out = {
        **core,
        "avg_exposure": round(avg_exp, 4),
        "bh": bh_core,
        "exposure_matched_bh": blend_core,
        "excess_cagr_vs_bh": round(core["cagr"] - bh_core["cagr"], 2),
        "excess_cagr_vs_exposure_matched": round(core["cagr"] - blend_core["cagr"], 2),
        # 분배금 근사(가정): B&H는 +y, 노출매칭은 +e·y, 전략은 최대 +e·y(보유가 주식형일 때)
        "div_adj_excess_vs_bh_range": [
            round(core["cagr"] - (bh_core["cagr"] + hi * 100) + avg_exp * hi * 100, 2),
            round(core["cagr"] - (bh_core["cagr"] + lo * 100) + avg_exp * lo * 100, 2),
        ],
        "regime": reg,
    }
    if trades is not None:
        out["trades"] = trades
    if dsr is not None:
        out["dsr"] = dsr
    return out


def fold_trades(report: WalkForwardReport) -> dict:
    w = sum(int(f.test.get("winning_trades", 0)) for f in report.folds if f.test)
    lo = sum(int(f.test.get("losing_trades", 0)) for f in report.folds if f.test)
    tot = sum(int(f.test.get("total_trades", 0)) for f in report.folds if f.test)
    return {
        "completed": w + lo,
        "total_trades": tot,
        "wins": w,
        "win_rate": round(100 * w / (w + lo), 1) if (w + lo) else None,
    }


# ==================== 골든크로스 후보 ====================
def gc_config(oversold: float, recovery: float, max_gap: float) -> GoldenCrossConfigDTO:
    return GoldenCrossConfigDTO(
        ma_config=GoldenCrossMAConfig(short_period=55, long_period=165),
        stochastic_config=StochasticConfig(
            oversold_threshold=oversold, recovery_threshold=recovery, require_momentum_turn=False
        ),
        ma_gap_config=MAGapConfig(min_gap_ratio=0.0, max_gap_ratio=max_gap),
    )


GRID = {
    "live": (25.0, 20.0, 8.0),
    "tight_entry": (20.0, 18.0, 8.0),
    "wide_trend": (25.0, 20.0, 12.0),
    "loose_entry": (30.0, 25.0, 8.0),
}


def gc_candidates(regime: RegimeEntryFilter | None = None) -> list[WalkForwardCandidate]:
    return [WalkForwardCandidate(k, gc_config(*v), regime) for k, v in GRID.items()]


REGIMES = {
    "none": None,
    "adx": RegimeEntryFilter(use_ma=False, use_adx=True, adx_period=14, adx_min=20.0),
    "adx_di": RegimeEntryFilter(
        use_ma=False, use_adx=True, adx_period=14, adx_min=20.0, use_di_direction=True
    ),
    "di_only": RegimeEntryFilter(use_ma=False, use_adx=False, use_di_direction=True),
    "ma200": RegimeEntryFilter(use_ma=True, ma_period=200),
}


# ==================== 실행 컨텍스트 ====================
@dataclass
class Ctx:
    panels: dict[str, pd.DataFrame]
    names: dict[str, str]
    bench: pd.DataFrame
    calendar: list[date]
    universe: list[str]
    exempt: list[str]
    results: dict = field(default_factory=dict)

    def bt_config(self) -> BacktestConfigDTO:
        return BacktestConfigDTO(
            initial_capital=C0,
            execution_timing="same_close",
            use_tax=True,
            etf_tax_exempt=True,
            tax_exempt_symbols=self.exempt,
        )

    def dev_windows(self) -> list[WalkForwardWindow]:
        days = [d for d in self.calendar if DEV_START <= d <= DEV_END]
        return generate_rolling_windows(days, train_size=504, test_size=126, step=126, embargo=5)


def make_ctx(data: dict) -> Ctx:
    panels = data["panels"]
    bench = panels[BENCH]
    cal = bdates(bench)
    universe = sorted(s for s in data["active"] if s in panels)
    exempt = sorted(set(panels))  # 전 종목 ETF → 매도세 면제
    return Ctx(panels, data["names"], bench, cal, universe, exempt)


def run_gc_wf(
    ctx: Ctx,
    exp: str,
    variant: str,
    *,
    candidates: list[WalkForwardCandidate],
    execution: PortfolioExecutionOptions | None = None,
    eligibility: str = "pit",
    symbols: list[str] | None = None,
    windows: list[WalkForwardWindow] | None = None,
    panels: dict[str, pd.DataFrame] | None = None,
) -> dict:
    windows = windows or ctx.dev_windows()
    syms = symbols or ctx.universe
    src = panels or ctx.panels
    use = {s: src[s] for s in syms if s in src}
    n_trials = reserve_trials(exp, variant, len(candidates) * len(windows))
    runner = WalkForwardRunner(
        candidates=candidates,
        constraints=PortfolioConstraints(max_positions=5),
        backtest_config=ctx.bt_config(),
        selection_metric="sharpe_ratio",
        benchmark=ctx.bench,
        regime_long_ma=200,
        n_trials=n_trials,
        execution=execution,
        eligibility=eligibility,
    )
    t0 = datetime.now()
    rep = runner.run(use, ctx.calendar, windows)
    secs = (datetime.now() - t0).total_seconds()
    st = rep.stats
    sched = execution.cash_interest if execution else None
    summ = summarize(
        rep.oos_dated_returns,
        rep.oos_exposure,
        ctx.bench,
        cash_sched=sched,
        trades=fold_trades(rep),
        dsr={
            "dsr": st.get("deflated_sharpe"),
            "n_trials": st.get("n_trials"),
            "pbo": st.get("pbo"),
            "ci": [st.get("oos_sharpe_ci_low"), st.get("oos_sharpe_ci_high")],
        },
    )
    summ["runner_oos"] = rep.oos
    summ["dsr_inputs"] = {
        "observed_daily_sharpe": st.get("observed_daily_sharpe"),
        "expected_max_sharpe": st.get("expected_max_sharpe"),
        "n_trials": st.get("n_trials"),
    }
    summ["oos_returns"] = [round(r, 8) for _, r in rep.oos_dated_returns]
    summ["folds"] = [
        {
            "test": f"{f.window.test_start}~{f.window.test_end}",
            "eligible_train": f.eligible_symbols,
            "eligible_test": f.test_eligible_symbols,
            "selected": f.selected_label,
            "train_sharpe": round(f.train.get("sharpe", 0) or 0, 3) if f.train else None,
            "test_sharpe": round(f.test.get("sharpe", 0) or 0, 3) if f.test else None,
            "test_ret": round(f.test.get("total_return", 0) or 0, 2) if f.test else None,
            "test_trades": f.test.get("total_trades") if f.test else None,
        }
        for f in rep.folds
    ]
    summ["variant"] = variant
    summ["execution"] = execution.describe() if execution else "default"
    summ["eligibility"] = eligibility
    summ["universe_size"] = len(use)
    summ["runtime_s"] = round(secs, 1)
    print(
        f"[{exp}:{variant}] CAGR={summ['cagr']} Sh={summ['sharpe']} Sh0={summ['sharpe_rf0']} "
        f"MDD={summ['mdd']} exp={summ['avg_exposure']} trades={summ['trades']} "
        f"DSR={st.get('deflated_sharpe')} N={st.get('n_trials')} PBO={st.get('pbo')} "
        f"({secs:.0f}s)",
        flush=True,
    )
    return summ


# ==================== 리포트 ====================
_ROW_HDR = (
    "| Variant | CAGR% | Sharpe(rf3) | Sharpe(rf0) | Sortino | MDD% | Trades(완료) | Win% "
    "| AvgExp | B&H CAGR% | ExpMatch CAGR% | Excess vs B&H | Excess vs ExpMatch | DSR (N) | PBO "
    "| bull/bear/chop ret% |\n"
    "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"
)


def row(s: dict) -> str:
    if s.get("empty"):
        return f"| {s.get('variant')} | (no data) |"
    t = s.get("trades") or {}
    d = s.get("dsr") or {}
    rg = s.get("regime") or {}
    reg = "/".join(str(rg.get(k, {}).get("ret")) for k in ("bull", "bear", "chop"))
    return (
        f"| {s.get('variant')} | {s['cagr']} | {s['sharpe']} | {s['sharpe_rf0']} | {s['sortino']} "
        f"| {s['mdd']} | {t.get('total_trades')}({t.get('completed')}) | {t.get('win_rate')} "
        f"| {s['avg_exposure']:.3f} | {s['bh']['cagr']} | {s['exposure_matched_bh']['cagr']} "
        f"| {s['excess_cagr_vs_bh']} | {s['excess_cagr_vs_exposure_matched']} "
        f"| {d.get('dsr')} ({d.get('n_trials')}) | {d.get('pbo')} | {reg} |"
    )


def write_report(exp: str, title: str, rows: list[dict], notes: list[str], extra: dict) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    if SUFFIX:
        exp = f"{SUFFIX}_{exp}"
        title = f"{title} [{SUFFIX}]"
    md = [f"# {title}", "", f"- 생성: {datetime.now(timezone.utc).isoformat(timespec='seconds')}"]
    md += [f"- {n}" for n in notes]
    if rows:
        md += ["", _ROW_HDR] + [row(r) for r in rows]
        md += ["", "## Per-fold", ""]
        for r in rows:
            if r.get("folds"):
                md.append(f"### {r['variant']}")
                md.append("| Test | Elig(train/test) | Selected | Train Sh | Test Sh | Ret% | Trades |")
                md.append("|---|---|---|---:|---:|---:|---:|")
                for f in r["folds"]:
                    md.append(
                        f"| {f['test']} | {f['eligible_train']}/{f['eligible_test']} "
                        f"| {f['selected']} | {f['train_sharpe']} | {f['test_sharpe']} "
                        f"| {f['test_ret']} | {f['test_trades']} |"
                    )
                md.append("")
    (REPORTS / f"{PREFIX}_{exp}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (REPORTS / f"{PREFIX}_{exp}.json").write_text(
        json.dumps({"rows": rows, "extra": extra}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"[{exp}] wrote {REPORTS / f'{PREFIX}_{exp}.md'}", flush=True)


# ==================== H0 ====================
def exp_h0(ctx: Ctx) -> None:
    # 커버리지: 연도별 '해당 연도 1월 첫 거래일 이전 상장 + 이후 데이터 연속' 심볼 수
    cov: dict[int, dict] = {}
    first_bar = {s: ctx.panels[s]["timestamp"].iloc[0].date() for s in ctx.universe}
    for y in range(2018, 2027):
        y0 = date(y, 1, 1)
        full = sum(1 for s in ctx.universe if first_bar[s] <= date(y, 1, 10))
        listed_by_end = sum(1 for s in ctx.universe if first_bar[s] <= date(y, 12, 31))
        cov[y] = {"full_year_from_jan": full, "listed_by_year_end": listed_by_end}
        _ = y0
    # PIT 편입 수(dev fold test 시작일, lookback=195)
    lb = 165 + 30
    pit = {}
    for w in ctx.dev_windows():
        n = 0
        for s in ctx.universe:
            dd = bdates(ctx.panels[s])
            n += sum(1 for d in dd if d < w.test_start) >= lb
        pit[str(w.test_start)] = n
    # 데이터 이상치: 비인버스 종목 |일간수익| > 25%
    jumps = []
    for s in ctx.universe:
        c = ctx.panels[s]["close"].astype(float)
        r = c.pct_change().abs()
        for i in np.where(r > 0.25)[0]:
            jumps.append((s, str(ctx.panels[s]["timestamp"].iloc[i].date()), round(float(r.iloc[i]), 3)))
    # 분배금 실측: KODEX200 vs KODEX200TR / TIGER200 vs TIGER200TR (동일 구간 CAGR 차)
    def cagr_between(sym: str, a: date, b: date) -> float | None:
        df = ctx.panels.get(sym)
        if df is None:
            return None
        sub = df[(df["timestamp"].dt.date >= a) & (df["timestamp"].dt.date <= b)]
        if len(sub) < 200:
            return None
        yrs = (sub["timestamp"].iloc[-1] - sub["timestamp"].iloc[0]).days / 365
        return (float(sub["close"].iloc[-1]) / float(sub["close"].iloc[0])) ** (1 / yrs) - 1

    div = {}
    for px, tr in (("069500", "278530"), ("102110", "310960")):
        if tr in ctx.panels and px in ctx.panels:
            a = max(ctx.panels[tr]["timestamp"].iloc[0].date(), ctx.panels[px]["timestamp"].iloc[0].date())
            b = date(2026, 11, 6)
            cp, ct = cagr_between(px, a, b), cagr_between(tr, a, b)
            if cp is not None and ct is not None:
                div[f"{px}_vs_{tr}"] = {
                    "from": str(a),
                    "price_cagr": round(cp * 100, 2),
                    "tr_cagr": round(ct * 100, 2),
                    "gap_pp": round((ct - cp) * 100, 2),
                }

    # 재현: 이전 8-fold 기준선(98종목, legacy 편입, 2020-01~2026-08)
    prior = json.loads(PRIOR_COVERAGE.read_text(encoding="utf-8"))["included_symbols"]
    rep_start, rep_end = date(2020, 1, 1), date(2026, 8, 1)
    rep_panels = {
        s: df[(df["timestamp"].dt.date >= rep_start) & (df["timestamp"].dt.date <= rep_end)]
        .reset_index(drop=True)
        for s, df in ctx.panels.items()
        if s in prior or s == BENCH
    }
    rep_days = [d for d in ctx.calendar if rep_start <= d <= rep_end]
    rep_windows = generate_rolling_windows(rep_days, train_size=504, test_size=126, step=126, embargo=5)
    rows = []
    s0 = run_gc_wf(
        ctx,
        "h0",
        "repro_prior98_legacy_2020-2026-08",
        candidates=gc_candidates(),
        eligibility="legacy",
        symbols=[s for s in prior if s in rep_panels],
        windows=rep_windows,
        panels=rep_panels,
    )
    rows.append(s0)
    # 새 기준선 B0: 전 ETF 유니버스, PIT 편입, 2018~ 워밍업, dev 9-fold
    b0 = run_gc_wf(ctx, "h0", "B0_allETF_pit_dev", candidates=gc_candidates(), eligibility="pit")
    rows.append(b0)
    ctx.results["B0"] = b0
    notes = [
        f"유니버스: stock_universe ETF 활성 {len(ctx.universe)}종(현재 상장분만 — 생존편향), 벤치 {BENCH}",
        f"이전 리포트(walk_forward_20260802_054935): CAGR 1.91% / Sharpe -0.238 / DSR 0.366 (N=32)",
        "재현 행은 98종목 coverage 목록 + legacy 편입규칙 + 2020-01-01~2026-08-01 로드(워밍업 없음, 이전과 동일 조건)."
        " 단 오늘 바뀐 지표정의/버그픽스/ETF 면세/2026 세율이 적용된 '현재 코드' 기준이다.",
        "B0: 전 ETF, PIT 편입(구간 시작 전 자체 바 ≥ 195), 2018~ 워밍업, dev=2020-01-01~2026-11-06 롤링 504/126/126/5.",
        f"연도별 커버리지: {json.dumps(cov)}",
        f"PIT 편입 수(test 시작일): {json.dumps(pit)}",
        f"일간 |수익|>25% 이상치 {len(jumps)}건: {jumps[:20]}",
        f"분배금 실측(가격형 vs TR형 CAGR 차): {json.dumps(div)}",
    ]
    write_report("h0", "H0 — 데이터 커버리지 / 기준선 재현", rows, notes, {"coverage": cov, "pit": pit, "jumps": jumps, "div": div})


# ==================== H1 ====================
def exp_h1(ctx: Ctx) -> None:
    rows = []
    for name, ex in (
        ("same_close(B0)", None),
        ("next_open", PortfolioExecutionOptions(fill_timing="next_open")),
        ("same_close+liq_end", PortfolioExecutionOptions(liquidate_at_end=True)),
        ("next_open+liq_end", PortfolioExecutionOptions(fill_timing="next_open", liquidate_at_end=True)),
    ):
        rows.append(run_gc_wf(ctx, "h1", name, candidates=gc_candidates(), execution=ex))
    d = rows[1]["sharpe"] - rows[0]["sharpe"]
    notes = [
        "라이브 주문은 장후 시간외 종가(ORD_DVSN 06) → same_close가 구조적으로 정합. next_open은 갭리스크 스트레스.",
        f"ΔSharpe(next_open − same_close) = {d:.3f} → {'⚠️ >0.1 하락: 체결가정 민감(현 수치 신뢰 불가 플래그)' if d < -0.1 else '0.1 이내 — 체결가정 둔감'}",
    ]
    write_report("h1", "H1 — 체결 타이밍 / 종료 청산비용", rows, notes, {})


# ==================== H2 ====================
def exp_h2(ctx: Ctx) -> None:
    rows = []
    sched = APPROX_KRW_CASH_RATE_SCHEDULE
    for name, ex in (
        ("cash_ratio_0%(B0)", None),
        ("cash_ratio+interest", PortfolioExecutionOptions(cash_interest=sched)),
        ("equal_weight_0%", PortfolioExecutionOptions(sizing_mode="equal_weight_equity")),
        (
            "equal_weight+interest",
            PortfolioExecutionOptions(sizing_mode="equal_weight_equity", cash_interest=sched),
        ),
    ):
        rows.append(run_gc_wf(ctx, "h2", name, candidates=gc_candidates(), execution=ex))
    notes = [
        f"현금이자 스케줄(근사 가정, CD/MMF 수준): {sched.describe()}",
        "노출매칭 B&H = avgExp×B&H + (1−avgExp)×현금(해당 행의 이자 가정과 동일; 0% 행은 0%).",
    ]
    write_report("h2", "H2 — 사이징 / 유휴현금 이자", rows, notes, {})


# ==================== H3 ====================
def exp_h3(ctx: Ctx, execution: PortfolioExecutionOptions | None) -> None:
    rows = []
    for name in ("none", "adx", "adx_di", "di_only", "ma200"):
        rows.append(
            run_gc_wf(ctx, "h3", name, candidates=gc_candidates(REGIMES[name]), execution=execution)
        )
    best = max(rows, key=lambda r: r["sharpe"])
    notes = [
        f"기저 실행옵션: {execution.describe() if execution else 'default'}",
        "선택은 dev 폴드 stitched OOS Sharpe(rf3)만으로. 홀드아웃은 미사용.",
        f"dev 최선: {best['variant']} (Sharpe {best['sharpe']})",
    ]
    write_report("h3", "H3 — 레짐 방향 게이트(+DI>−DI)", rows, notes, {"best": best["variant"]})


# ==================== H4 ====================
def momentum_universe(ctx: Ctx) -> list[str]:
    return [s for s in ctx.universe if "인버스" not in ctx.names.get(s, "")]


def run_mom_wf(
    ctx: Ctx, exp: str, variant: str, cfg: MomentumRotationConfig, windows: list[WalkForwardWindow]
) -> dict:
    syms = momentum_universe(ctx)
    n_trials = reserve_trials(exp, variant, len(windows))
    segs = []
    fold_sh = []
    tr_tot = tr_w = tr_l = 0
    idx = {d: i for i, d in enumerate(ctx.calendar)}
    for w in windows:
        i0 = max(0, idx[w.test_start] - (cfg.min_history + 30))
        a = ctx.calendar[i0]
        sl = {
            s: ctx.panels[s][
                (ctx.panels[s]["timestamp"].dt.date >= a)
                & (ctx.panels[s]["timestamp"].dt.date <= w.test_end)
            ].reset_index(drop=True)
            for s in syms
        }
        sl = {s: df for s, df in sl.items() if len(df)}
        cal = [d for d in ctx.calendar if a <= d <= w.test_end]
        res = MomentumRotationEngine(cfg).run(sl, ctx.bt_config(), active_from=w.test_start, calendar=cal)
        segs.append(res.result.daily_stats)
        rets = [s.daily_return / 100 for s in res.result.daily_stats[1:]]
        sd = _st.pstdev(rets) if len(rets) > 1 else 0
        fold_sh.append(_st.fmean(rets) / sd if sd > 0 else 0.0)
        tr_tot += res.result.total_trades
        tr_w += res.result.winning_trades
        tr_l += res.result.losing_trades
    _, dated = stitch_oos_segments(segs, C0)
    expo = stitch_oos_exposure(segs)
    dsr = deflated_sharpe_ratio([r for _, r in dated], fold_sh, n_trials=n_trials)
    summ = summarize(
        dated,
        expo,
        ctx.bench,
        cash_sched=cfg.cash_interest,
        trades={
            "completed": tr_w + tr_l,
            "total_trades": tr_tot,
            "wins": tr_w,
            "win_rate": round(100 * tr_w / (tr_w + tr_l), 1) if tr_w + tr_l else None,
        },
        dsr={"dsr": dsr.deflated_sharpe, "n_trials": n_trials, "pbo": None},
    )
    summ["variant"] = variant
    summ["oos_returns"] = [round(r, 8) for _, r in dated]
    summ["dsr_inputs"] = {
        "observed_daily_sharpe": dsr.observed_sharpe,
        "expected_max_sharpe": dsr.expected_max_sharpe,
        "n_trials": n_trials,
    }
    summ["fold_daily_sharpe"] = [round(x, 4) for x in fold_sh]
    summ["universe_size"] = len(syms)
    print(f"[{exp}:{variant}] CAGR={summ['cagr']} Sh={summ['sharpe']} MDD={summ['mdd']} exp={summ['avg_exposure']} DSR={dsr.deflated_sharpe} N={n_trials}", flush=True)
    return summ


def exp_h4(ctx: Ctx) -> None:
    rows = []
    windows = ctx.dev_windows()
    sched = APPROX_KRW_CASH_RATE_SCHEDULE
    for n in (3, 5):
        for interest_name, s in (("0%", None), ("interest", sched)):
            cfg = MomentumRotationConfig(top_n=n, cash_interest=s, fill_timing="next_open")
            rows.append(run_mom_wf(ctx, "h4", f"mom12-1_top{n}_ma200_next_open_{interest_name}", cfg, windows))
    # 체결 민감도(same_close) — top3/이자 기준 1개
    cfg = MomentumRotationConfig(top_n=3, cash_interest=sched, fill_timing="same_close")
    rows.append(run_mom_wf(ctx, "h4", "mom12-1_top3_ma200_same_close_interest", cfg, windows))
    # 연속 실행(폴드 리셋 없음) — 참고
    notes = [
        "파라미터 사전 고정: 12-1 모멘텀(252/21), MA200 개별 추세필터, top N∈{3,5}, 월말 리밸런스, 동일가중(총자산/N), 유지종목 재조정 없음.",
        f"유니버스: 인버스 제외 ETF {len(momentum_universe(ctx))}종(레버리지 상품 없음). 비용: 수수료 0.015%·슬리피지 0.05%·ETF 매도세 면제.",
        "폴드: GC와 동일 dev test 창, 폴드마다 플랫 시작(첫날 종가 시그널 → 다음날 시가 체결).",
        "⚠️ 해외/채권/원자재 ETF 매매차익 배당소득세 15.4% 미반영(낙관 편향).",
    ]
    write_report("h4", "H4 — ETF 모멘텀 로테이션(대안 전략)", rows, notes, {})


# ==================== H5 ====================
def exp_h5(ctx: Ctx, execution: PortfolioExecutionOptions | None, regime_name: str) -> None:
    rows = []
    variants = {
        "fsm_only(base)": None,
        "trend_stop15": ExitOverlay(trend_stop_pct=0.15),
        "breakdown20d15": ExitOverlay(breakdown_20d_pct=0.15),
        "profit_protect85": ExitOverlay(profit_protect=True),
        "all_hard": ExitOverlay(trend_stop_pct=0.15, breakdown_20d_pct=0.15, profit_protect=True),
    }
    base = execution or PortfolioExecutionOptions()
    for name, ov in variants.items():
        ex = PortfolioExecutionOptions(
            fill_timing=base.fill_timing,
            sizing_mode=base.sizing_mode,
            cash_interest=base.cash_interest,
            liquidate_at_end=base.liquidate_at_end,
            exit_overlay=ov,
        )
        rows.append(
            run_gc_wf(ctx, "h5", name, candidates=gc_candidates(REGIMES[regime_name]), execution=ex)
        )
    notes = [
        f"기저: execution={base.describe()}, regime={regime_name}. dev 폴드만 사용.",
        "보유최고가 −15% 하드손절은 FSM에 이미 포함(중복 없음).",
    ]
    write_report("h5", "H5 — 하이브리드 매도 하드규칙 오버레이(역사 시뮬)", rows, notes, {})


# ==================== H6 ====================
def exp_h6(ctx: Ctx, n_symbols: int = 20) -> None:
    from src.adapters.database.models.strategy_symbol_state import SymbolState
    from src.application.common.indicators import TechnicalIndicators
    from src.application.domain.backtest.generators.golden_cross import (
        GoldenCrossSignalGenerator,
    )
    from src.application.domain.backtest.golden_cross_parity import GoldenCrossParityReplay
    from src.application.domain.strategy.state_machine import (
        GoldenCrossStateMachine,
        IndicatorSnapshot,
        Signal,
    )

    cfg = gc_config(*GRID["live"])
    long_p = cfg.ma_config.long_period
    fetch_days = max(cfg.lookback_days, int((long_p + 20) * 1.6))
    min_candles = long_p + 10
    start_eval = date(2021, 1, 4)
    # 표본: 2019년 이전 상장 ETF 중 심볼 순 균등 추출
    pool = [s for s in ctx.universe if ctx.panels[s]["timestamp"].iloc[0].date() < date(2019, 1, 1)]
    step = max(1, len(pool) // n_symbols)
    sample = pool[::step][:n_symbols]

    def snap(row: pd.Series) -> IndicatorSnapshot:
        return GoldenCrossParityReplay._snapshot(row)

    out = []
    tot_live = tot_match = tot_parity = 0
    gen_match = gen_total = 0
    for sym in sample:
        df = ctx.panels[sym]
        dts = bdates(df)
        eval_days = [d for d in dts if d >= start_eval]
        # ── 라이브 리플레이: 매일 [d − fetch_days, d] 창으로 지표 재계산, 마지막 2행으로 FSM 1스텝
        sm = GoldenCrossStateMachine(cfg)
        state = None
        live_sig: list[tuple[date, str, str | None]] = []
        tsd = df["timestamp"].dt.date
        for d in eval_days:
            win = df[(tsd > d - timedelta(days=fetch_days)) & (tsd <= d)].reset_index(drop=True)
            if len(win) < min_candles:
                continue
            p = TechnicalIndicators.prepare_golden_cross_indicators(
                win, short_ma_period=55, long_ma_period=long_p, stoch_k_period=14, stoch_d_period=3
            )
            cur, prv = snap(p.iloc[-1]), snap(p.iloc[-2])
            if state is None:
                state = {
                    "state": sm.get_initial_state(cur).value,
                    "gc_date": None,
                    "pullback_date": None,
                    "entry_price": None,
                    "entry_date": None,
                    "highest_price": None,
                    "trailing": False,
                }
            tr = sm.process(
                current=cur,
                prev=prv,
                current_state=SymbolState(state["state"]),
                gc_date=state["gc_date"],
                pullback_date=state["pullback_date"],
                entry_price=state["entry_price"],
                entry_date=state["entry_date"],
                highest_price=state["highest_price"],
                trailing_stop_activated=state["trailing"],
            )
            if state["state"] == SymbolState.IN_POSITION.value:
                if state["highest_price"] is None or cur.close > state["highest_price"]:
                    state["highest_price"] = cur.close
                ep = state["entry_price"]
                if ep and ep > 0 and float((cur.close - ep) / ep) >= cfg.risk_config.trailing_stop_activation:
                    state["trailing"] = True
            if tr.signal == Signal.BUY:
                live_sig.append((d, "buy", tr.reason))
                state.update(state=tr.new_state.value, entry_price=cur.close, entry_date=cur.timestamp,
                             highest_price=None, trailing=False, gc_date=None, pullback_date=None)
            elif tr.signal == Signal.SELL:
                live_sig.append((d, "sell", tr.reason))
                state.update(state=SymbolState.WAITING_FOR_GC.value, entry_price=None, entry_date=None,
                             highest_price=None, trailing=False, gc_date=None, pullback_date=None)
            else:
                if tr.new_state.value != state["state"]:
                    state.update(state=tr.new_state.value, gc_date=tr.gc_date, pullback_date=tr.pullback_date)
                else:
                    # 라이브 update_state는 상태가 바뀔 때만 gc/pullback을 기록
                    pass
        # ── parity 리플레이: 첫 평가일이 라이브와 같도록 슬라이스(전체 이력 지표)
        first_live = None
        for d in eval_days:
            win = df[(tsd > d - timedelta(days=fetch_days)) & (tsd <= d)]
            if len(win) >= min_candles:
                first_live = d
                break
        if first_live is None:
            continue
        i_first = dts.index(first_live)
        sl = df.iloc[max(0, i_first - (min_candles - 1)) :].reset_index(drop=True)
        par = GoldenCrossParityReplay(cfg).build_signal_schedule(sl)
        par_sig = [(s.timestamp.date(), s.signal, s.reason) for s in par if s.timestamp.date() >= first_live]
        # ── 레거시 백테스트 생성기(참고: 문서상 divergent) — 같은 슬라이스를 바 단위로 공급,
        #    단일 포지션(플랫일 때 buy, 보유 중 sell)만 집계. 리스크 청산은 생성기 범위 밖.
        gen = GoldenCrossSignalGenerator(short_period=55, long_period=long_p)
        ph: list[float] = []
        hh: list[float] = []
        lh: list[float] = []
        holding = False
        gen_sig: list[tuple[date, str]] = []
        for ts, hi, lo, cl in zip(sl["timestamp"], sl["high"], sl["low"], sl["close"]):
            ph.append(float(cl))
            hh.append(float(hi))
            lh.append(float(lo))
            sgl = gen.generate_signal(ph, Decimal(str(cl)), hh, lh, ph)
            d = ts.date()
            if d < first_live:
                continue
            if sgl == "buy" and not holding:
                gen_sig.append((d, "buy"))
                holding = True
            elif sgl == "sell" and holding:
                gen_sig.append((d, "sell"))
                holding = False
                gen.notify_exit()
        gen_err = None
        ls = {(d, s) for d, s, _ in live_sig}
        ps = {(d, s) for d, s, _ in par_sig}
        match = len(ls & ps)
        tot_live += len(ls)
        tot_parity += len(ps)
        tot_match += match
        gs = set(gen_sig)
        gen_match += len(ls & gs)
        gen_total += len(ls | gs)
        out.append(
            {
                "symbol": sym,
                "name": ctx.names.get(sym),
                "first_eval": str(first_live),
                "live_signals": len(ls),
                "parity_signals": len(ps),
                "matched": match,
                "live_only": sorted(f"{d}:{s}" for d, s in ls - ps)[:10],
                "parity_only": sorted(f"{d}:{s}" for d, s in ps - ls)[:10],
                "generator_signals": len(gs),
                "generator_overlap_with_live": len(ls & gs),
                "generator_error": gen_err,
            }
        )
        print(f"[h6] {sym} live={len(ls)} parity={len(ps)} match={match} gen={len(gs)}", flush=True)
    union = tot_live + tot_parity - tot_match
    rate = tot_match / union if union else 1.0
    md = [
        "# H6 — 라이브 FSM 리플레이 vs 백테스트 parity (실데이터)",
        "",
        f"- 표본 {len(out)}종(2019 이전 상장 ETF 균등추출), 평가 시작 {start_eval}, config=gc_standard(55/165, live 진입)",
        f"- 라이브 리플레이: 매일 [d−{fetch_days}일, d] DB 창으로 지표 재계산 → 마지막 2행 FSM 1스텝, 상태 영속(엔진 _process_symbol 미러, 주문/게이트 제외)",
        "- parity: 첫 평가일 정렬 슬라이스로 `GoldenCrossParityReplay.build_signal_schedule`",
        f"- **일치율(Jaccard, 날짜+방향)**: {tot_match}/{union} = **{rate:.1%}** (목표 ≥95%) — 라이브 {tot_live}, parity {tot_parity}",
        f"- 레거시 생성기 vs 라이브 Jaccard: {gen_match}/{gen_total}",
        "",
        "| Symbol | Name | First | Live | Parity | Match | Live-only | Parity-only | Gen | Gen∩Live |",
        "|---|---|---|---:|---:|---:|---|---|---:|---:|",
    ]
    for o in out:
        md.append(
            f"| {o['symbol']} | {o['name']} | {o['first_eval']} | {o['live_signals']} | {o['parity_signals']} "
            f"| {o['matched']} | {', '.join(o['live_only'])} | {', '.join(o['parity_only'])} "
            f"| {o['generator_signals']} | {o['generator_overlap_with_live']} |"
        )
    h6 = f"{SUFFIX}_h6" if SUFFIX else "h6"
    (REPORTS / f"{PREFIX}_{h6}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (REPORTS / f"{PREFIX}_{h6}.json").write_text(
        json.dumps({"rate": rate, "rows": out}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[h6] match rate {rate:.1%}", flush=True)


# ==================== 홀드아웃 ====================
def exp_holdout(ctx: Ctx, gc_variant: dict, mom_cfg: MomentumRotationConfig) -> None:
    """각 후보 1회 평가. gc_variant = {config_label, regime, execution}."""
    rows = []
    a, b = LOAD_START, HOLDOUT_END
    cal = [d for d in ctx.calendar if a <= d <= b]
    active = next(d for d in cal if d >= HOLDOUT_START)
    # 편입: 2018-01 첫 달 내 첫 바가 있는 종목(= 2018 이전 상장, PIT 유효)
    syms = [s for s in ctx.universe if ctx.panels[s]["timestamp"].iloc[0].date() <= date(2018, 1, 31)]
    sl = {
        s: ctx.panels[s][(ctx.panels[s]["timestamp"].dt.date >= a) & (ctx.panels[s]["timestamp"].dt.date <= b)].reset_index(drop=True)
        for s in syms
    }
    reserve_trials("holdout", "gc_final", 1)
    reserve_trials("holdout", "mom_final", 1)
    n_trials = cumulative_trials()
    cfg = gc_config(*GRID[gc_variant["config_label"]])
    regime = REGIMES[gc_variant["regime"]]
    ex = gc_variant["execution"]
    allowed = compute_allowed_entry_dates(ctx.bench, regime)
    res = PortfolioParityEngine(cfg, PortfolioConstraints(max_positions=5), ex).run(
        sl, ctx.bt_config(), active_from=active, entry_allowed_dates=allowed
    )
    ds = res.result.daily_stats
    _, dated = stitch_oos_segments([ds], C0)
    expo = stitch_oos_exposure([ds])
    dsr = deflated_sharpe_ratio([r for _, r in dated], [0.0, 0.0], n_trials=n_trials)
    first_trade = min((t.entry_date for t in res.result.trades), default=None)
    gc_row = summarize(
        dated, expo, ctx.bench, cash_sched=ex.cash_interest if ex else None,
        trades={"total_trades": res.result.total_trades, "completed": res.result.winning_trades + res.result.losing_trades,
                "wins": res.result.winning_trades, "win_rate": res.result.win_rate},
        dsr={"dsr": dsr.deflated_sharpe, "n_trials": n_trials, "pbo": None, "note": "SR0=0(시도분산 미상) → DSR=P(SR>0) 상한"},
    )
    gc_row["variant"] = f"GC[{gc_variant['config_label']}|{gc_variant['regime']}|{ex.describe() if ex else 'default'}]"
    gc_row["first_trade"] = str(first_trade)
    gc_row["universe_size"] = len(sl)
    rows.append(gc_row)
    # 모멘텀
    msyms = [s for s in syms if "인버스" not in ctx.names.get(s, "")]
    mres = MomentumRotationEngine(mom_cfg).run({s: sl[s] for s in msyms}, ctx.bt_config(), active_from=active, calendar=cal)
    mds = mres.result.daily_stats
    _, mdated = stitch_oos_segments([mds], C0)
    mexpo = stitch_oos_exposure([mds])
    mdsr = deflated_sharpe_ratio([r for _, r in mdated], [0.0, 0.0], n_trials=n_trials)
    first_hold = next((r.signal_date for r in mres.rebalances if r.held_after), None)
    m_row = summarize(
        mdated, mexpo, ctx.bench, cash_sched=mom_cfg.cash_interest,
        trades={"total_trades": mres.result.total_trades, "completed": mres.result.winning_trades + mres.result.losing_trades,
                "wins": mres.result.winning_trades, "win_rate": mres.result.win_rate},
        dsr={"dsr": mdsr.deflated_sharpe, "n_trials": n_trials, "pbo": None, "note": "SR0=0 → 상한"},
    )
    m_row["variant"] = f"MOM[{mom_cfg.describe()}]"
    m_row["first_signal_with_holding"] = str(first_hold)
    m_row["universe_size"] = len(msyms)
    rows.append(m_row)
    notes = [
        f"홀드아웃 {HOLDOUT_START}~{HOLDOUT_END}(최초 평가). 데이터는 {LOAD_START}부터라 워밍업 부족:",
        f"  GC(MA165)는 첫 시그널 가능일 ≈ 상장+175봉 → 첫 거래 {first_trade}; 모멘텀(253봉)은 첫 보유 리밸런스 {first_hold}.",
        f"편입: 2018-01 내 첫 바 보유 ETF {len(sl)}종(현 상장분, 생존편향).",
        "각 후보 1회만 실행. 결과와 무관하게 보고.",
    ]
    write_report("holdout", "FINAL — 단일 홀드아웃(2018-07~2019-12)", rows, notes, {})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", required=True)
    ap.add_argument("--cache", default="/scratch/research_panels_20261106.pkl")
    ap.add_argument("--refresh-cache", action="store_true")
    ap.add_argument("--gc-config", default="live")
    ap.add_argument("--gc-regime", default="none")
    ap.add_argument("--fill", default="same_close")
    ap.add_argument("--sizing", default="cash_ratio")
    ap.add_argument("--interest", action="store_true")
    ap.add_argument("--mom-top", type=int, default=3)
    ap.add_argument("--suffix", default="", help="재실행 태그(리포트 파일명·원장 키에 부착)")
    args = ap.parse_args()
    global SUFFIX
    SUFFIX = args.suffix
    data = load_data(Path(args.cache), args.refresh_cache)
    ctx = make_ctx(data)
    print(f"[suite] panels={len(ctx.panels)} universe={len(ctx.universe)} cal={ctx.calendar[0]}~{ctx.calendar[-1]}", flush=True)
    ex = PortfolioExecutionOptions(
        fill_timing=args.fill,
        sizing_mode=args.sizing,
        cash_interest=APPROX_KRW_CASH_RATE_SCHEDULE if args.interest else None,
    )
    ex_or_none = None if ex.is_default else ex
    if args.exp == "load":
        return
    if args.exp == "h0":
        exp_h0(ctx)
    elif args.exp == "h1":
        exp_h1(ctx)
    elif args.exp == "h2":
        exp_h2(ctx)
    elif args.exp == "h3":
        exp_h3(ctx, ex_or_none)
    elif args.exp == "h4":
        exp_h4(ctx)
    elif args.exp == "h5":
        exp_h5(ctx, ex_or_none, args.gc_regime)
    elif args.exp == "h6":
        exp_h6(ctx)
    elif args.exp == "holdout":
        mom = MomentumRotationConfig(
            top_n=args.mom_top,
            cash_interest=APPROX_KRW_CASH_RATE_SCHEDULE if args.interest else None,
        )
        exp_holdout(ctx, {"config_label": args.gc_config, "regime": args.gc_regime, "execution": ex_or_none}, mom)
    else:
        raise SystemExit(f"unknown exp {args.exp}")


if __name__ == "__main__":
    main()
