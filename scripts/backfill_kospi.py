#!/usr/bin/env python
"""
Backfill KOSPI index OHLCV into ohlcv_cache (symbol='KOSPI').
Tries multiple TRs / params because KIS index endpoints are picky.
Run: uv run python scripts/backfill_kospi.py --days 900 --force
"""
import argparse
import asyncio
from datetime import datetime, timedelta

from sqlalchemy import text

from src.adapters.database.connection import get_async_session
from src.adapters.external.kis_api.client import get_kis_client
from src.adapters.cache.redis_client import get_redis_client
from src.application.domain.market_data.service import MarketDataService


TR_CANDIDATES = [
    ("FHKST03010100", "J", "KOSPI"),
    ("FHKST03010100", "J", "0001"),
    ("FHKST03010100", "U", "KOSPI"),
    ("FHKUP03500100", "J", "KOSPI"),
    ("FHKST03010100", "J", "KS11"),
]


async def fetch_kospi_candles(days: int = 900, force: bool = True):
    kis = get_kis_client()
    redis = await get_redis_client() if callable(get_redis_client) else get_redis_client()
    svc = MarketDataService(kis_client=kis, redis_client=redis)

    end = datetime.now()
    start = end - timedelta(days=days)

    # Try MarketDataService first
    try:
        chart = await svc.get_chart_data(
            symbol="KOSPI",
            interval="1d",
            start_date=start,
            end_date=end,
            use_cache=not force,
        )
        candles = getattr(chart, "candles", []) or []
        if candles:
            print(f"MarketDataService success: {len(candles)} candles")
            return candles
    except Exception as e:
        print(f"MarketDataService attempt failed: {e}")

    # Direct client attempts
    client = get_kis_client()
    for tr_id, div_code, iscd in TR_CANDIDATES:
        try:
            params = {
                "FID_COND_MRKT_DIV_CODE": div_code,
                "FID_INPUT_ISCD": iscd,
                "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",
            }
            resp = await client.get(
                "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                params=params,
                headers={"tr_id": tr_id},
            )
            out = resp.get("output2") or resp.get("output") or []
            if out:
                print(f"Direct success with {tr_id}/{div_code}/{iscd}: {len(out)} rows")
                # Convert to simple list of dicts for compatibility
                candles = []
                for item in out:
                    from datetime import datetime as dt
                    from decimal import Decimal
                    candles.append(type("C", (), {
                        "timestamp": dt.strptime(item.get("stck_bsop_date", ""), "%Y%m%d"),
                        "open": Decimal(item.get("stck_oprc", "0")),
                        "high": Decimal(item.get("stck_hgpr", "0")),
                        "low": Decimal(item.get("stck_lwpr", "0")),
                        "close": Decimal(item.get("stck_clpr", "0")),
                        "volume": int(item.get("acml_vol", "0")),
                    })())
                return candles
        except Exception as e:
            print(f"Direct {tr_id}/{div_code}/{iscd} failed: {str(e)[:70]}")

    print("No KOSPI data obtained. Using proxy will be necessary for now.")
    return []


async def backfill(days: int = 900, force: bool = True):
    async with get_async_session() as session:
        candles = await fetch_kospi_candles(days=days, force=force)

        if not candles:
            print("Backfill skipped (0 candles).")
            return

        inserted = 0
        for c in candles:
            await session.execute(
                text("""
                    INSERT INTO ohlcv_cache (symbol, "timestamp", open, high, low, close, volume, interval, created_at, updated_at)
                    VALUES ('KOSPI', :ts, :o, :h, :l, :c, :v, '1d', now(), now())
                    ON CONFLICT (symbol, "timestamp", interval) DO UPDATE
                    SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                        close=EXCLUDED.close, volume=EXCLUDED.volume, updated_at=now()
                """),
                {"ts": c.timestamp, "o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": c.volume}
            )
            inserted += 1
        await session.commit()

        print(f"Inserted/updated {inserted} KOSPI rows.")

        # Verify
        res = await session.execute(
            text("SELECT COUNT(*), MIN(\"timestamp\"), MAX(\"timestamp\") FROM ohlcv_cache WHERE symbol='KOSPI' AND interval='1d'")
        )
        print("KOSPI in DB now:", res.fetchone())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=900)
    parser.add_argument("--force", action="store_true", default=True)
    args = parser.parse_args()
    asyncio.run(backfill(days=args.days, force=args.force))
