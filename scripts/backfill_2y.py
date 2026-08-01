#!/usr/bin/env python3
"""상위 N종목 2년치 일봉을 KIS에서 받아 DB에 적재 (백테스트용).

전제: retention 730일(config), load_from_api date→datetime 버그 수정 완료.
Run: ./.venv/bin/python scripts/backfill_2y.py --symbols 100 --days 760 --concurrency 3
"""
import argparse
import asyncio
from datetime import datetime, timezone, timedelta

from sqlalchemy import text

from src.adapters.database.connection import AsyncSessionLocal, get_async_session
from src.application.domain.ohlcv.core_loader import OHLCVCoreLoader


async def top_symbols(n: int) -> list[str]:
    async with get_async_session() as s:
        res = await s.execute(
            text(
                "SELECT symbol, count(*) c FROM ohlcv_cache WHERE interval='1d' "
                "GROUP BY symbol ORDER BY c DESC LIMIT :n"
            ),
            {"n": n},
        )
        return [r[0] for r in res.fetchall() if r[0] != "KOSPI"]


async def backfill_one(sym: str, start, end) -> tuple[str, int, int]:
    async with AsyncSessionLocal() as s:
        loader = OHLCVCoreLoader(s)
        try:
            df, calls, failed = await loader.load_from_api(sym, start_date=start, end_date=end, interval="1d")
            if failed > 0:  # 부분 실패 → 갭 캐싱 방지, 실패로 분류(다음 실행 재시도)
                await s.rollback()
                return sym, -1, 0
            saved = await loader.cache_to_db(sym, df, "1d")
            await s.commit()
            return sym, len(df), saved
        except Exception as e:  # noqa: BLE001
            await s.rollback()
            return sym, -1, 0


async def run(n: int, days: int, concurrency: int) -> None:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    syms = await top_symbols(n)
    print(f"backfill {len(syms)} symbols, {days}d, concurrency={concurrency}", flush=True)

    sem = asyncio.Semaphore(concurrency)
    done = {"n": 0}

    async def _worker(sym):
        async with sem:
            res = await backfill_one(sym, start, end)
            done["n"] += 1
            if done["n"] % 10 == 0 or res[1] < 0:
                print(f"  [{done['n']}/{len(syms)}] {res[0]} fetched={res[1]} saved={res[2]}", flush=True)
            return res

    results = await asyncio.gather(*[_worker(s) for s in syms])
    ok = [r for r in results if r[1] > 0]
    fail = [r for r in results if r[1] < 0]
    total_saved = sum(r[2] for r in ok)
    print("=" * 50, flush=True)
    print(f"done: {len(ok)} ok, {len(fail)} failed, total_saved={total_saved}", flush=True)
    if ok:
        avg = sum(r[1] for r in ok) / len(ok)
        print(f"avg rows/symbol fetched: {avg:.0f}", flush=True)
    if fail:
        print(f"failed: {[r[0] for r in fail][:20]}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=100)
    ap.add_argument("--days", type=int, default=760)
    ap.add_argument("--concurrency", type=int, default=3)
    a = ap.parse_args()
    asyncio.run(run(a.symbols, a.days, a.concurrency))


if __name__ == "__main__":
    main()
