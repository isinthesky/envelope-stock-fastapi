# -*- coding: utf-8 -*-
"""
매도 리스크 데이터 2년 백필 스크립트
"""

import argparse
import asyncio
import json

from src.adapters.database.connection import close_db, get_async_session
from src.application.domain.strategy.sell_risk_backfill_service import (
    SellRiskBackfillService,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="시장 신용/개인 수급 DB 백필")
    parser.add_argument("--years", type=int, default=2, help="백필 연수 (기본값: 2)")
    parser.add_argument("--symbols", type=str, default="", help="쉼표 구분 종목코드 목록")
    parser.add_argument("--end-date", type=str, default=None, help="종료일 YYYYMMDD")
    args = parser.parse_args()

    symbols = [symbol.strip() for symbol in args.symbols.split(",") if symbol.strip()] or None

    try:
        async with get_async_session() as session:
            service = SellRiskBackfillService(session=session)
            result = await service.backfill_all(
                symbols=symbols,
                years=args.years,
                end_date=args.end_date,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
