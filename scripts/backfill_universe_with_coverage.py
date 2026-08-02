#!/usr/bin/env python3
"""ETF 유니버스 다년 일봉 백필 + 커버리지 게이트 리포트 (P1).

walk-forward 검증 하네스가 사용할 데이터를 실 OHLCV로 적재하고, 각 종목의
데이터 품질을 하드 게이트로 판정한다. 제외 종목도 반드시 사유와 함께 리포트에
남긴다(무음 누락 금지).

커버리지 분모는 벤치마크(기본 069500 KODEX 200)의 실제 거래일 달력을 사용한다.

⚠️ 런타임 전용: KIS 토큰 + Postgres + Redis가 필요하므로 컨테이너에서 실행한다.
  docker compose exec api python scripts/backfill_universe_with_coverage.py \
      --start 2019-01-01 --concurrency 3

옵션:
  --start/--end    수집 구간(기본: start=2019-01-01, end=오늘)
  --concurrency    동시 수집 수(KIS rate limit 고려, 기본 3)
  --min-bars       최소 거래일 수 게이트(기본 285 ≈ long_period 165 + test 120)
  --min-coverage   최소 커버리지(기본 0.98)
  --benchmark      기준 거래일 달력 종목(기본 069500)
  --codes          쉼표구분 종목코드(지정 시 유니버스 대신 사용)
  --no-cache       DB 저장 없이 커버리지 평가만 수행
"""
import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.adapters.database.connection import AsyncSessionLocal
from src.application.domain.backtest.coverage_gate import (
    CoverageParams,
    build_coverage_report,
    evaluate_symbol_coverage,
    trading_days_from_df,
)
from src.application.domain.ohlcv.core_loader import OHLCVCoreLoader
from src.settings.config import settings

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


async def _load_symbol(sym: str, start, end, write_cache: bool):
    """단일 종목 일봉 로드(+선택적 캐시). Returns (sym, df, failed_chunks)."""
    async with AsyncSessionLocal() as s:
        loader = OHLCVCoreLoader(s)
        try:
            df, _calls, failed = await loader.load_from_api(sym, start, end, "1d")
            if write_cache and failed == 0 and not df.empty:
                await loader.cache_to_db(sym, df, "1d")
                await s.commit()
            else:
                await s.rollback()
            return sym, df, failed
        except Exception as e:  # noqa: BLE001
            await s.rollback()
            print(f"  ! {sym} load failed: {e}", flush=True)
            return sym, None, -1


async def run(args) -> None:
    end = datetime.now(timezone.utc)
    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    if args.end:
        end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)

    symbols = (
        [c.strip() for c in args.codes.split(",")]
        if args.codes
        else list(settings.etf_universe_symbols)
    )
    benchmark = args.benchmark
    write_cache = not args.no_cache

    print(
        f"[coverage] {len(symbols)} symbols, {start.date()}~{end.date()}, "
        f"benchmark={benchmark}, cache={write_cache}",
        flush=True,
    )

    # 1) 벤치마크 달력 먼저 로드(분모 기준)
    _, bench_df, bench_failed = await _load_symbol(benchmark, start, end, write_cache)
    calendar_dates = trading_days_from_df(bench_df) if bench_df is not None else set()
    if not calendar_dates:
        raise SystemExit(f"benchmark {benchmark} 거래일 달력을 만들 수 없습니다(로드 실패). 중단.")
    print(f"[coverage] benchmark calendar: {len(calendar_dates)} trading days", flush=True)

    # 2) 유니버스 종목 로드(동시성 제한)
    sem = asyncio.Semaphore(args.concurrency)
    done = {"n": 0}

    async def _worker(sym: str):
        async with sem:
            res = await _load_symbol(sym, start, end, write_cache)
            done["n"] += 1
            if done["n"] % 10 == 0:
                print(f"  [{done['n']}/{len(symbols)}] loaded", flush=True)
            return res

    loaded = await asyncio.gather(*[_worker(s) for s in symbols])

    # 3) 게이트 판정
    params = CoverageParams(min_bars=args.min_bars, min_coverage_rate=args.min_coverage)
    verdicts = [
        evaluate_symbol_coverage(
            symbol=sym,
            symbol_dates=trading_days_from_df(df) if df is not None else set(),
            calendar_dates=calendar_dates,
            params=params,
        )
        for sym, df, _failed in loaded
    ]

    # 4) 리포트 작성
    generated_at = datetime.now(timezone.utc)
    markdown, payload = build_coverage_report(
        verdicts,
        params=params,
        requested_start=start.date(),
        requested_end=end.date(),
        benchmark=benchmark,
        generated_at=generated_at,
    )
    payload["benchmark_failed_chunks"] = bench_failed

    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = generated_at.strftime("%Y%m%d_%H%M%S")
    md_path = REPORTS_DIR / f"coverage_{stamp}.md"
    json_path = REPORTS_DIR / f"coverage_{stamp}.json"
    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    s = payload["summary"]
    print("=" * 60, flush=True)
    print(
        f"[coverage] included={s['included']} excluded={s['excluded']} " f"total={s['total']}",
        flush=True,
    )
    print(f"[coverage] report: {md_path}", flush=True)
    print(f"[coverage] json:   {json_path}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=str, default="2019-01-01")
    ap.add_argument("--end", type=str, default=None)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--min-bars", type=int, default=285)
    ap.add_argument("--min-coverage", type=float, default=0.98)
    ap.add_argument("--benchmark", type=str, default="069500")
    ap.add_argument("--codes", type=str, default=None)
    ap.add_argument("--no-cache", action="store_true")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
