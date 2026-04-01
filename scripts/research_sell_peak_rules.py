# -*- coding: utf-8 -*-
"""
저장된 리스크/가격 데이터로 매도 피크 규칙 리서치
"""

import argparse
import asyncio
import json

from src.adapters.database.connection import close_db, get_async_session
from src.application.domain.strategy.sell_rule_research_service import (
    SellPeakRuleResearchService,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="매도 피크 규칙 리서치")
    parser.add_argument("--symbols", type=str, default="", help="쉼표 구분 종목코드 목록")
    parser.add_argument("--start-date", type=str, default=None, help="시작일 YYYYMMDD")
    parser.add_argument("--end-date", type=str, default=None, help="종료일 YYYYMMDD")
    args = parser.parse_args()

    symbols = [symbol.strip() for symbol in args.symbols.split(",") if symbol.strip()] or None

    try:
        async with get_async_session() as session:
            service = SellPeakRuleResearchService(session)
            result = await service.research_top_signal_rules(
                symbols=symbols,
                start_date=args.start_date,
                end_date=args.end_date,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
