#!/usr/bin/env python3
"""실 데이터 Walk-Forward 검증 실행 (P3/P4/regime) — 진짜 OOS 숫자 산출.

P1에서 DB에 적재된 실 OHLCV(98종목)를 backfill 없이 읽어, 검증된
`WalkForwardRunner`로 롤링 train/test를 돌리고 DSR/PBO/국면분해까지 산출한다.

⚠️ 런타임 전용: Postgres 접속이 필요하므로 컨테이너에서 실행한다. **KIS API는
호출하지 않는다**(DB 캐시만 읽음 → 토큰 발급 없음).

  docker compose exec api uv run python scripts/run_walk_forward.py

옵션:
  --coverage    included 종목을 읽을 P1 커버리지 JSON(기본: reports/ 최신)
  --codes       쉼표구분 종목코드(지정 시 커버리지 대신 사용)
  --benchmark   국면/거래일 달력 기준 종목(기본 069500 KODEX 200)
  --start/--end 로드 구간(기본: 2020-01-01 ~ 2026-08-01)
  --train/--test/--step/--embargo  롤링 창(거래일 수, 기본 504/126/126/5)
  --max-positions   동시 보유 상한(기본 5)
  --alloc           신규 포지션당 현금비율(기본: config 값)
  --no-tax          매도세 미적용(국내 주식형 ETF 실제 면제 반영)
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.adapters.database.connection import AsyncSessionLocal
from src.adapters.database.repositories.ohlcv_repository import OHLCVRepository
from src.application.domain.backtest.dto import BacktestConfigDTO
from src.application.domain.backtest.gates import (
    evaluate_gates,
    gate_inputs_from_report,
)
from src.application.domain.backtest.portfolio_parity_engine import PortfolioConstraints
from src.application.domain.backtest.regime import (
    classify_regimes,
    decompose_by_regime,
    regime_summary_dict,
)
from src.application.domain.backtest.regime_filter import RegimeEntryFilter
from src.application.domain.backtest.walk_forward_runner import (
    WalkForwardCandidate,
    WalkForwardRunner,
)
from src.application.domain.backtest.walk_forward_windows import generate_rolling_windows
from src.application.domain.strategy.dto import (
    GoldenCrossConfigDTO,
    GoldenCrossMAConfig,
    GoldenCrossRiskConfig,
    MAGapConfig,
    StochasticConfig,
)

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"


# ==================== 후보 그리드 ====================
# 라이브 config를 중심으로 소규모 그리드(PBO 정의 위해 ≥2). 과도한 그리드는
# 데이터 스누핑을 키우므로 핵심 축(진입 민감도/추세 여유)만 변주한다.
def _candidate(
    label: str,
    *,
    oversold: float,
    recovery: float,
    max_gap: float,
    regime_filter: RegimeEntryFilter | None = None,
) -> WalkForwardCandidate:
    return WalkForwardCandidate(
        label=label,
        config=GoldenCrossConfigDTO(
            ma_config=GoldenCrossMAConfig(short_period=55, long_period=165),
            stochastic_config=StochasticConfig(
                oversold_threshold=oversold,
                recovery_threshold=recovery,
                require_momentum_turn=False,
            ),
            # ma_gap 단위는 퍼센트(%): min ge=-5..10, max ge=5..20
            ma_gap_config=MAGapConfig(min_gap_ratio=0.0, max_gap_ratio=max_gap),
        ),
        regime_filter=regime_filter,
    )


def build_candidates(
    regime_filter: RegimeEntryFilter | None = None,
) -> list[WalkForwardCandidate]:
    """후보 그리드. regime_filter 지정 시 전 후보에 동일 진입 국면 필터를 적용한다
    (A/B 변형 실행용). 미지정이면 기존 무필터 그리드."""
    return [
        _candidate("live", oversold=25.0, recovery=20.0, max_gap=8.0, regime_filter=regime_filter),
        _candidate(
            "tight_entry", oversold=20.0, recovery=18.0, max_gap=8.0, regime_filter=regime_filter
        ),
        _candidate(
            "wide_trend", oversold=25.0, recovery=20.0, max_gap=12.0, regime_filter=regime_filter
        ),
        _candidate(
            "loose_entry", oversold=30.0, recovery=25.0, max_gap=8.0, regime_filter=regime_filter
        ),
    ]


def build_exit_ablation_candidates() -> list[WalkForwardCandidate]:
    """E1 winner-capping 규칙을 한 번에 하나씩 제거한 사전 정의 후보군."""
    base = GoldenCrossConfigDTO(ma_config=GoldenCrossMAConfig(short_period=55, long_period=165))
    return [
        WalkForwardCandidate("exit_baseline", base),
        WalkForwardCandidate(
            "no_fixed_take_profit",
            base.model_copy(
                update={
                    "risk_config": base.risk_config.model_copy(update={"use_take_profit": False})
                }
            ),
        ),
        WalkForwardCandidate(
            "no_trailing_stop",
            base.model_copy(
                update={
                    "risk_config": base.risk_config.model_copy(update={"use_trailing_stop": False})
                }
            ),
        ),
        WalkForwardCandidate(
            "max_hold_180d",
            base.model_copy(
                update={
                    "risk_config": GoldenCrossRiskConfig(
                        **{
                            **base.risk_config.model_dump(),
                            "max_hold_days": 180,
                        }
                    )
                }
            ),
        ),
        WalkForwardCandidate(
            "atr_dynamic_stop_2x",
            base.model_copy(
                update={
                    "risk_config": base.risk_config.model_copy(
                        update={"use_atr_stop_loss": True, "atr_stop_loss_multiplier": 2.0}
                    )
                }
            ),
        ),
        WalkForwardCandidate(
            "atr_trailing_2x",
            base.model_copy(
                update={
                    "risk_config": base.risk_config.model_copy(
                        update={
                            "use_atr_trailing_stop": True,
                            "atr_trailing_multiplier": 2.0,
                        }
                    )
                }
            ),
        ),
    ]


def _load_sector_map(path: str | None) -> dict[str, str]:
    if path is None:
        return {}
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(
        isinstance(symbol, str) and isinstance(sector, str) for symbol, sector in raw.items()
    ):
        raise SystemExit("--sector-map must be a JSON object: {symbol: sector}")
    return raw


# A/B 진입 국면 필터 변형: 무필터 vs MA200 vs ADX vs MA200+ADX
REGIME_VARIANTS: dict[str, RegimeEntryFilter | None] = {
    "none": None,
    "ma200": RegimeEntryFilter(use_ma=True, ma_period=200, use_adx=False),
    "adx": RegimeEntryFilter(use_ma=False, use_adx=True, adx_period=14, adx_min=20.0),
    "ma200_adx": RegimeEntryFilter(
        use_ma=True, ma_period=200, use_adx=True, adx_period=14, adx_min=20.0
    ),
}


# ==================== 데이터 로드(DB 전용) ====================
async def _load_panels(
    symbols: list[str], benchmark: str, start: datetime, end: datetime
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    panels: dict[str, pd.DataFrame] = {}
    bench_df = pd.DataFrame()
    want = list(dict.fromkeys([benchmark, *symbols]))  # 벤치마크 우선, 중복 제거
    async with AsyncSessionLocal() as s:
        repo = OHLCVRepository(s)
        for i, sym in enumerate(want, 1):
            df = await repo.get_candles_to_dataframe(sym, start, end, "1d")
            if df.empty:
                print(f"  ! {sym}: DB 데이터 없음 — 건너뜀", flush=True)
                continue
            df = df.sort_values("timestamp").reset_index(drop=True)
            if sym == benchmark:
                bench_df = df
            if sym in symbols:
                panels[sym] = df
            if i % 20 == 0:
                print(f"  [{i}/{len(want)}] loaded", flush=True)
    return panels, bench_df


def _benchmark_oos_metrics(bench_df, trading_days, windows) -> tuple[float | None, float | None]:
    """OOS 창(union)에서 벤치 buy&hold 수익%와 약세장 MDD%를 산출한다(G3/G4 근거).

    - buy&hold 수익: OOS 첫 거래일 종가 → 마지막 거래일 종가.
    - 약세장 MDD: 벤치 자체 국면 라벨로 OOS 일별수익을 분해한 bear MDD.
    두 값 모두 전략 OOS와 동일 날짜집합·동일 국면라벨을 써 apples-to-apples 비교.
    """
    # OOS 날짜집합(fold test 창 union ∩ 거래일)
    oos_dates = sorted(
        {d for d in trading_days if any(w.test_start <= d <= w.test_end for w in windows)}
    )
    if len(oos_dates) < 2:
        return None, None
    close_by_date = {
        ts.date(): (ts, float(c)) for ts, c in zip(bench_df["timestamp"], bench_df["close"])
    }
    oos_dates = [d for d in oos_dates if d in close_by_date]
    if len(oos_dates) < 2:
        return None, None

    first_c = close_by_date[oos_dates[0]][1]
    last_c = close_by_date[oos_dates[-1]][1]
    oos_return_pct = (last_c / first_c - 1.0) * 100.0 if first_c > 0 else None

    # 벤치 일별수익(연속 OOS 거래일 기준) → 국면 분해 → bear MDD
    pairs: list[tuple] = []
    for i in range(1, len(oos_dates)):
        prev_c = close_by_date[oos_dates[i - 1]][1]
        cur_ts, cur_c = close_by_date[oos_dates[i]]
        if prev_c > 0:
            pairs.append((cur_ts, cur_c / prev_c - 1.0))
    bear_mdd = None
    if pairs:
        regimes = classify_regimes(bench_df, long_ma=200)
        decomp = regime_summary_dict(decompose_by_regime(pairs, regimes))
        bear = decomp.get("bear") or {}
        bear_mdd = bear.get("mdd")
    return oos_return_pct, bear_mdd


def _resolve_symbols(args) -> list[str]:
    if args.codes:
        return [c.strip() for c in args.codes.split(",") if c.strip()]
    cov_path = Path(args.coverage) if args.coverage else _latest_coverage()
    data = json.loads(cov_path.read_text(encoding="utf-8"))
    return list(data["included_symbols"])


def _latest_coverage() -> Path:
    files = sorted(REPORTS_DIR.glob("coverage_*.json"))
    if not files:
        raise SystemExit("커버리지 JSON을 찾을 수 없습니다. --codes 또는 --coverage 지정 필요.")
    return files[-1]


# ==================== 실행 ====================
async def run(args) -> None:
    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    symbols = _resolve_symbols(args)
    print(
        f"[wf] symbols={len(symbols)} benchmark={args.benchmark} {start.date()}~{end.date()}",
        flush=True,
    )

    panels, bench_df = await _load_panels(symbols, args.benchmark, start, end)
    if not panels:
        raise SystemExit("패널이 비었습니다. DB 적재 여부(P1 backfill)를 확인하세요.")
    if bench_df.empty:
        raise SystemExit(f"벤치마크 {args.benchmark} 데이터가 DB에 없습니다.")
    print(f"[wf] loaded panels={len(panels)} benchmark_bars={len(bench_df)}", flush=True)

    # 거래일 달력 = 벤치마크 거래일
    trading_days = sorted({ts.date() for ts in bench_df["timestamp"]})
    windows = generate_rolling_windows(
        trading_days,
        train_size=args.train,
        test_size=args.test,
        step=args.step,
        embargo=args.embargo,
    )
    if not windows:
        raise SystemExit(
            f"윈도우 생성 실패: 거래일 {len(trading_days)}일 < train+embargo+test "
            f"({args.train}+{args.embargo}+{args.test})."
        )
    print(f"[wf] trading_days={len(trading_days)} folds={len(windows)}", flush=True)
    print(
        f"[wf] fold1 train {windows[0].train_start}~{windows[0].train_end} "
        f"test {windows[0].test_start}~{windows[0].test_end}",
        flush=True,
    )

    candidates = (
        build_exit_ablation_candidates()
        if args.experiment == "exit-ablation"
        else build_candidates()
    )
    constraints = PortfolioConstraints(
        max_positions=args.max_positions,
        allocation_ratio=args.alloc,  # None이면 config 값 사용
        max_sector_weight=args.max_sector_weight,
        sector_map=_load_sector_map(args.sector_map),
    )
    backtest_config = BacktestConfigDTO(
        execution_timing="same_close",  # 라이브 15:35 종가주문 정합
        use_tax=not args.no_tax,
    )

    runner = WalkForwardRunner(
        candidates=candidates,
        constraints=constraints,
        backtest_config=backtest_config,
        selection_metric="sharpe_ratio",
        benchmark=bench_df,  # 국면 분해 활성화
        regime_long_ma=200,
    )
    print(f"[wf] running {len(candidates)} candidates × {len(windows)} folds …", flush=True)
    report = runner.run(panels, trading_days, windows)

    # ── P5 Go/No-Go 게이트: 벤치 OOS 수익·약세장 MDD를 채워 판정
    bench_oos_ret, bench_bear_mdd = _benchmark_oos_metrics(bench_df, trading_days, windows)
    gate_inputs = gate_inputs_from_report(
        report,
        benchmark_oos_return_pct=bench_oos_ret,
        benchmark_bear_mdd=bench_bear_mdd,
        slippage_2x_positive=None,  # 비용 민감도는 별도 실행 필요 → NA(미측정)
    )
    gate_result = evaluate_gates(gate_inputs)
    # 게이트 판정을 리포트 상단(headline 다음)에 삽입
    report_md = report.markdown + "\n" + gate_result.markdown()

    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    md_path = REPORTS_DIR / f"walk_forward_{stamp}.md"
    json_path = REPORTS_DIR / f"walk_forward_{stamp}.json"
    md_path.write_text(report_md, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "window": {
                    "start": start.date().isoformat(),
                    "end": end.date().isoformat(),
                    "train": args.train,
                    "test": args.test,
                    "step": args.step,
                    "embargo": args.embargo,
                },
                "symbols": len(panels),
                "candidates": [c.label for c in candidates],
                "constraints": {
                    "max_positions": args.max_positions,
                    "allocation_ratio": args.alloc,
                    "max_sector_weight": args.max_sector_weight,
                    "sector_map": args.sector_map,
                },
                "use_tax": not args.no_tax,
                "oos": report.oos,
                "stats": report.stats,
                "gate": {
                    "verdict": gate_result.verdict,
                    "reason": gate_result.reason,
                    "passed": gate_result.passed,
                    "failed": gate_result.failed,
                    "na": gate_result.na,
                    "benchmark_oos_return_pct": bench_oos_ret,
                    "benchmark_bear_mdd": bench_bear_mdd,
                    "checks": [
                        {"key": c.key, "name": c.name, "status": c.status, "detail": c.detail}
                        for c in gate_result.checks
                    ],
                },
                "folds": [
                    {
                        "train": f"{f.window.train_start}~{f.window.train_end}",
                        "test": f"{f.window.test_start}~{f.window.test_end}",
                        "eligible": f.eligible_symbols,
                        "excluded": f.excluded_symbols,
                        "selected": f.selected_label,
                        "train_metrics": f.train,
                        "test_metrics": f.test,
                    }
                    for f in report.folds
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    o = report.oos
    st = report.stats
    print("=" * 64, flush=True)
    print(
        f"[wf] OOS  CAGR={o['cagr']}%  Sharpe={o['sharpe']}  MDD={o['mdd']}%  "
        f"days={o['trading_days']} folds={o['folds']}",
        flush=True,
    )
    print(
        f"[wf] DSR={st.get('deflated_sharpe')}  PBO={st.get('pbo')}  "
        f"OOS_dailySharpeCI=[{st.get('oos_sharpe_ci_low')},{st.get('oos_sharpe_ci_high')}]",
        flush=True,
    )
    regime = st.get("regime") or {}
    for name in ("bull", "bear", "chop"):
        m = regime.get(name)
        if m:
            print(
                f"[wf] regime {name}: days={m['n_days']} ret={m['total_return']}% "
                f"dailySharpe={m['daily_sharpe']} mdd={m['mdd']}%",
                flush=True,
            )
    print("-" * 64, flush=True)
    print(
        f"[wf] GATE verdict={gate_result.verdict}  "
        f"PASS={gate_result.passed} FAIL={gate_result.failed} NA={gate_result.na}",
        flush=True,
    )
    for c in gate_result.checks:
        print(f"[wf]   {c.key} {c.status:4} {c.name} — {c.detail}", flush=True)
    print(f"[wf] GATE reason: {gate_result.reason}", flush=True)
    print(f"[wf] report: {md_path}", flush=True)
    print(f"[wf] json:   {json_path}", flush=True)


async def run_regime_ab(args) -> None:
    """진입 국면 필터 A/B 검증: 동일 후보 그리드를 4개 필터 변형으로 돌려
    OOS/게이트를 비교한다. 표준 walk_forward_*.json은 건드리지 않고
    walk_forward_regime_ab_*.{json,md} 로 비교 결과만 저장한다."""
    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    symbols = _resolve_symbols(args)
    print(f"[wf-ab] symbols={len(symbols)} benchmark={args.benchmark}", flush=True)

    panels, bench_df = await _load_panels(symbols, args.benchmark, start, end)
    if not panels or bench_df.empty:
        raise SystemExit("패널/벤치마크 데이터가 비었습니다(P1 backfill 확인).")

    trading_days = sorted({ts.date() for ts in bench_df["timestamp"]})
    windows = generate_rolling_windows(
        trading_days,
        train_size=args.train,
        test_size=args.test,
        step=args.step,
        embargo=args.embargo,
    )
    if not windows:
        raise SystemExit("윈도우 생성 실패(거래일 부족).")
    print(f"[wf-ab] trading_days={len(trading_days)} folds={len(windows)}", flush=True)

    constraints = PortfolioConstraints(
        max_positions=args.max_positions, allocation_ratio=args.alloc
    )
    backtest_config = BacktestConfigDTO(execution_timing="same_close", use_tax=not args.no_tax)
    bench_oos_ret, bench_bear_mdd = _benchmark_oos_metrics(bench_df, trading_days, windows)

    results: list[dict] = []
    for name, filt in REGIME_VARIANTS.items():
        candidates = build_candidates(regime_filter=filt)
        runner = WalkForwardRunner(
            candidates=candidates,
            constraints=constraints,
            backtest_config=backtest_config,
            selection_metric="sharpe_ratio",
            benchmark=bench_df,
            regime_long_ma=200,
        )
        print(f"[wf-ab] variant={name} ({filt.describe() if filt else 'no-filter'}) …", flush=True)
        report = runner.run(panels, trading_days, windows)
        gate_inputs = gate_inputs_from_report(
            report,
            benchmark_oos_return_pct=bench_oos_ret,
            benchmark_bear_mdd=bench_bear_mdd,
            slippage_2x_positive=None,
        )
        gate = evaluate_gates(gate_inputs)
        o, st = report.oos, report.stats
        regime = st.get("regime") or {}
        # OOS 승률: 폴드별 test 완료거래(이익/손실) 합산 → 거래가중 승률
        w_tr = sum(int(f.test.get("winning_trades", 0)) for f in report.folds if f.test)
        l_tr = sum(int(f.test.get("losing_trades", 0)) for f in report.folds if f.test)
        completed = w_tr + l_tr
        win_rate = round(100.0 * w_tr / completed, 1) if completed else 0.0
        trades = {
            "winning": w_tr,
            "losing": l_tr,
            "completed": completed,
            "win_rate": win_rate,
        }
        results.append(
            {
                "variant": name,
                "filter": filt.describe() if filt else "no-filter",
                "oos": o,
                "trades": trades,
                "stats": {
                    k: st.get(k)
                    for k in ("deflated_sharpe", "pbo", "oos_sharpe_ci_low", "oos_sharpe_ci_high")
                },
                "regime": regime,
                "gate": {
                    "verdict": gate.verdict,
                    "passed": gate.passed,
                    "failed": gate.failed,
                    "na": gate.na,
                    "reason": gate.reason,
                    "checks": [
                        {"key": c.key, "name": c.name, "status": c.status, "detail": c.detail}
                        for c in gate.checks
                    ],
                },
            }
        )
        print(
            f"[wf-ab]   → verdict={gate.verdict} return={o['total_return']}% CAGR={o['cagr']}% "
            f"WinRate={win_rate}%({completed}건) Sharpe={o['sharpe']} MDD={o['mdd']}% "
            f"bear={regime.get('bear', {}).get('total_return')}% "
            f"chop={regime.get('chop', {}).get('total_return')}%",
            flush=True,
        )

    # 최선 변형: 게이트 통과 수 → OOS Sharpe 순
    best = max(results, key=lambda r: (r["gate"]["passed"], r["oos"]["sharpe"]))

    # 비교 마크다운
    md = [
        "# Walk-Forward 진입 국면 필터 A/B 비교",
        "",
        f"- 기간: {start.date()}~{end.date()} | folds: {len(windows)} | 종목: {len(panels)}",
        (
            f"- 벤치 OOS buy&hold: {bench_oos_ret:.2f}%"
            if bench_oos_ret is not None
            else "- 벤치 OOS: n/a"
        ),
        "",
        "| Variant | Filter | Verdict | Return% | WinRate%(건) | CAGR% | Sharpe | MDD% | DSR | bear% | chop% |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in results:
        o, rg, tr = r["oos"], r["regime"], r["trades"]
        md.append(
            f"| {r['variant']} | {r['filter']} | {r['gate']['verdict']} "
            f"| {o['total_return']} | {tr['win_rate']}({tr['completed']}) | {o['cagr']} "
            f"| {o['sharpe']} | {o['mdd']} | {r['stats'].get('deflated_sharpe')} "
            f"| {rg.get('bear', {}).get('total_return')} | {rg.get('chop', {}).get('total_return')} |"
        )
    md += [
        "",
        f"> **최선 변형: `{best['variant']}` ({best['filter']})** — "
        f"verdict={best['gate']['verdict']}, OOS Sharpe={best['oos']['sharpe']}.",
        "> 무필터(none) 대비 개선 여부로 필터 효용을 판단하라. 개선 시에만 라이브 적용 검토.",
    ]

    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    md_path = REPORTS_DIR / f"walk_forward_regime_ab_{stamp}.md"
    json_path = REPORTS_DIR / f"walk_forward_regime_ab_{stamp}.json"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "window": {
                    "start": start.date().isoformat(),
                    "end": end.date().isoformat(),
                    "train": args.train,
                    "test": args.test,
                    "step": args.step,
                    "embargo": args.embargo,
                },
                "symbols": len(panels),
                "benchmark_oos_return_pct": bench_oos_ret,
                "benchmark_bear_mdd": bench_bear_mdd,
                "best_variant": best["variant"],
                "variants": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("=" * 64, flush=True)
    print(
        f"[wf-ab] BEST variant={best['variant']} ({best['filter']}) verdict={best['gate']['verdict']}",
        flush=True,
    )
    print(f"[wf-ab] md:   {md_path}", flush=True)
    print(f"[wf-ab] json: {json_path}", flush=True)


async def run_sector_cap_ab(args) -> None:
    """동일 OOS folds에서 섹터 캡 OFF/ON의 Sharpe·MDD를 직접 비교한다."""
    sector_map = _load_sector_map(args.sector_map)
    if not sector_map:
        raise SystemExit("--sector-cap-ab requires a non-empty --sector-map JSON")
    if not 0 < args.max_sector_weight < 1:
        raise SystemExit("--sector-cap-ab requires 0 < --max-sector-weight < 1")

    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    symbols = _resolve_symbols(args)
    panels, bench_df = await _load_panels(symbols, args.benchmark, start, end)
    if not panels or bench_df.empty:
        raise SystemExit("패널/벤치마크 데이터가 비었습니다(P1 backfill 확인).")
    trading_days = sorted({ts.date() for ts in bench_df["timestamp"]})
    windows = generate_rolling_windows(
        trading_days,
        train_size=args.train,
        test_size=args.test,
        step=args.step,
        embargo=args.embargo,
    )
    candidates = (
        build_exit_ablation_candidates()
        if args.experiment == "exit-ablation"
        else build_candidates()
    )
    backtest_config = BacktestConfigDTO(execution_timing="same_close", use_tax=not args.no_tax)
    results = []
    for label, cap in (("off", 1.0), ("on", args.max_sector_weight)):
        report = WalkForwardRunner(
            candidates,
            constraints=PortfolioConstraints(
                max_positions=args.max_positions,
                allocation_ratio=args.alloc,
                max_sector_weight=cap,
                sector_map=sector_map,
            ),
            backtest_config=backtest_config,
            benchmark=bench_df,
        ).run(panels, trading_days, windows)
        results.append({"variant": label, "cap": cap, "oos": report.oos, "stats": report.stats})

    baseline, capped = results
    comparison = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sector_map": args.sector_map,
        "variants": results,
        "delta": {
            "sharpe": capped["oos"]["sharpe"] - baseline["oos"]["sharpe"],
            "mdd_pct_point": capped["oos"]["mdd"] - baseline["oos"]["mdd"],
            "total_return_pct_point": (
                capped["oos"]["total_return"] - baseline["oos"]["total_return"]
            ),
        },
    }
    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = REPORTS_DIR / f"walk_forward_sector_cap_ab_{stamp}.json"
    md_path = REPORTS_DIR / f"walk_forward_sector_cap_ab_{stamp}.md"
    json_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(
        "# Walk-Forward Sector Cap A/B\n\n"
        "| Variant | Cap | Return% | Sharpe | MDD% |\n"
        "|---|---:|---:|---:|---:|\n"
        + "\n".join(
            f"| {row['variant']} | {row['cap']} | {row['oos']['total_return']} | "
            f"{row['oos']['sharpe']} | {row['oos']['mdd']} |"
            for row in results
        )
        + "\n\n"
        + f"Delta Sharpe: {comparison['delta']['sharpe']}; "
        + f"Delta MDD: {comparison['delta']['mdd_pct_point']}%p\n",
        encoding="utf-8",
    )
    print(f"[sector-ab] md: {md_path}")
    print(f"[sector-ab] json: {json_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", type=str, default=None)
    ap.add_argument("--codes", type=str, default=None)
    ap.add_argument("--benchmark", type=str, default="069500")
    ap.add_argument("--start", type=str, default="2020-01-01")
    ap.add_argument("--end", type=str, default="2026-08-01")
    ap.add_argument("--train", type=int, default=504)
    ap.add_argument("--test", type=int, default=126)
    ap.add_argument("--step", type=int, default=126)
    ap.add_argument("--embargo", type=int, default=5)
    ap.add_argument("--max-positions", type=int, default=5)
    ap.add_argument("--alloc", type=float, default=None)
    ap.add_argument(
        "--experiment",
        choices=("entry-grid", "exit-ablation"),
        default="entry-grid",
        help="exit-ablation은 고정익절/트레일링/최대보유 규칙의 E1 knock-out 후보를 검증",
    )
    ap.add_argument(
        "--max-sector-weight",
        type=float,
        default=1.0,
        help="단일 섹터 최대 비중. 1.0은 비활성, 예: 0.30",
    )
    ap.add_argument(
        "--sector-map",
        type=str,
        default=None,
        help="symbol->sector JSON 파일. 섹터 캡 활성화 시 필수",
    )
    ap.add_argument("--no-tax", action="store_true")
    ap.add_argument(
        "--regime-ab",
        action="store_true",
        help="진입 국면 필터 A/B 비교(none/ma200/adx/ma200_adx) 실행 — "
        "표준 리포트 대신 walk_forward_regime_ab_*.{json,md} 생성",
    )
    ap.add_argument(
        "--sector-cap-ab",
        action="store_true",
        help="동일 OOS folds에서 섹터 캡 OFF/ON 비교 리포트 생성",
    )
    args = ap.parse_args()
    if args.regime_ab and args.sector_cap_ab:
        raise SystemExit("--regime-ab and --sector-cap-ab cannot be combined")
    target = run_sector_cap_ab if args.sector_cap_ab else run_regime_ab if args.regime_ab else run
    asyncio.run(target(args))


if __name__ == "__main__":
    main()
