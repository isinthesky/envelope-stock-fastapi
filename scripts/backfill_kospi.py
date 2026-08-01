#!/usr/bin/env python3
"""KOSPI 종합지수(0001) 일봉을 KIS 지수 API로 받아 ohlcv_cache(symbol='KOSPI')에 적재.

수정: 기존 스크립트는 stock 엔드포인트/TR/필드를 써서 항상 실패했다.
올바른 지수 계약: path=inquire-daily-indexchartprice, TR=FHKUP03500100,
FID_COND_MRKT_DIV_CODE='U', FID_INPUT_ISCD='0001', 필드=bstp_nmix_*.

Run: ./.venv/bin/python scripts/backfill_kospi.py --days 760
"""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.adapters.database.connection import AsyncSessionLocal
from src.adapters.database.repositories.ohlcv_repository import OHLCVRepository
from src.adapters.external.kis_api.client import get_kis_client
from src.application.domain.market_data.dto import CandleDTO

INDEX_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice"
INDEX_TR = "FHKUP03500100"
MAX_DAYS = 60  # KIS 지수 엔드포인트는 50행 캡 → 60일(~42거래일)로 truncation 방지


async def _fetch_chunk(client, iscd: str, start: datetime, end: datetime) -> list[CandleDTO]:
    params = {
        "FID_COND_MRKT_DIV_CODE": "U",
        "FID_INPUT_ISCD": iscd,
        "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
        "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
        "FID_PERIOD_DIV_CODE": "D",
    }
    resp = await client.get(INDEX_PATH, params=params, headers={"tr_id": INDEX_TR})
    out = resp.get("output2") or []
    candles = []
    for it in out:
        ds = it.get("stck_bsop_date")
        if not ds:  # KIS 빈 패딩 행 스킵
            continue
        close = Decimal(it.get("bstp_nmix_prpr", "0"))
        # 지수 OHLC가 불안정하면 close로 대체(공포필터는 close만 사용)
        o = Decimal(it.get("bstp_nmix_oprc", "0")) or close
        h = Decimal(it.get("bstp_nmix_hgpr", "0")) or close
        low_ = Decimal(it.get("bstp_nmix_lwpr", "0")) or close
        candles.append(CandleDTO(
            # stock 경로(normalize_timestamp)와 동일하게 KST 거래일의 UTC 자정으로 저장
            # (naive로 저장하면 15:00 UTC로 밀려 date 정렬이 깨진다)
            timestamp=datetime.strptime(ds, "%Y%m%d").replace(tzinfo=timezone.utc),
            open=o, high=max(h, close), low=min(low_, close), close=close,
            volume=int(it.get("acml_vol", "0") or 0),
        ))
    return candles


async def run(days: int) -> None:
    client = get_kis_client()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    calls = max(1, (days + MAX_DAYS - 1) // MAX_DAYS)
    all_candles: dict[datetime, CandleDTO] = {}
    for i in range(calls):
        chunk_end = end - timedelta(days=i * MAX_DAYS)
        chunk_start = max(start, chunk_end - timedelta(days=MAX_DAYS))
        cs = await _fetch_chunk(client, "0001", chunk_start, chunk_end)
        for c in cs:
            all_candles[c.timestamp] = c
        print(f"  chunk {i+1}/{calls} [{chunk_start:%Y%m%d}-{chunk_end:%Y%m%d}] -> {len(cs)}", flush=True)

    candles = sorted(all_candles.values(), key=lambda c: c.timestamp)
    if not candles:
        print("No KOSPI data obtained.")
        return
    async with AsyncSessionLocal() as s:
        saved = await OHLCVRepository(s).save_candles_bulk("KOSPI", candles, interval="1d", source="kis")
        await s.commit()
    print(f"KOSPI saved={saved}  range {candles[0].timestamp.date()} ~ {candles[-1].timestamp.date()}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=760)
    a = ap.parse_args()
    asyncio.run(run(a.days))


if __name__ == "__main__":
    main()
