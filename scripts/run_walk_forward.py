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
from src.application.domain.backtest.portfolio_parity_engine import PortfolioConstraints
from src.application.domain.backtest.walk_forward_runner import (
    WalkForwardCandidate,
    WalkForwardRunner,
)
from src.application.domain.backtest.walk_forward_windows import generate_rolling_windows
from src.application.domain.strategy.dto import (
    GoldenCrossConfigDTO,
    GoldenCrossMAConfig,
    MAGapConfig,
    StochasticConfig,
)

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


# ==================== 후보 그리드 ====================
# 라이브 config를 중심으로 소규모 그리드(PBO 정의 위해 ≥2). 과도한 그리드는
# 데이터 스누핑을 키우므로 핵심 축(진입 민감도/추세 여유)만 변주한다.
def _candidate(label: str, *, oversold: float, recovery: float, max_gap: float) -> WalkForwardCandidate:
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
    )


def build_candidates() -> list[WalkForwardCandidate]:
    return [
        _candidate("live", oversold=25.0, recovery=20.0, max_gap=8.0),
        _candidate("tight_entry", oversold=20.0, recovery=18.0, max_gap=8.0),
        _candidate("wide_trend", oversold=25.0, recovery=20.0, max_gap=12.0),
        _candidate("loose_entry", oversold=30.0, recovery=25.0, max_gap=8.0),
    ]


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
    print(f"[wf] symbols={len(symbols)} benchmark={args.benchmark} {start.date()}~{end.date()}", flush=True)

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

    candidates = build_candidates()
    constraints = PortfolioConstraints(
        max_positions=args.max_positions,
        allocation_ratio=args.alloc,  # None이면 config 값 사용
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

    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    md_path = REPORTS_DIR / f"walk_forward_{stamp}.md"
    json_path = REPORTS_DIR / f"walk_forward_{stamp}.json"
    md_path.write_text(report.markdown, encoding="utf-8")
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
                },
                "use_tax": not args.no_tax,
                "oos": report.oos,
                "stats": report.stats,
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
    print(f"[wf] report: {md_path}", flush=True)
    print(f"[wf] json:   {json_path}", flush=True)


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
    ap.add_argument("--no-tax", action="store_true")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
