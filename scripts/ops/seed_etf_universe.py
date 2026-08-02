#!/usr/bin/env python3
"""ETF 유니버스 원타임 시드.

ETF_UNIVERSE_ENABLED=true 상태에서 refresh_universe를 1회 실행해
stock_universe를 개별주 전량 비활성화 + 지정 ETF(market=ETF)만으로 재구성한다.
이후 스캔/추천 파이프라인은 ETF-only를 반환한다.

Run: ./.venv/bin/python scripts/seed_etf_universe.py
"""
import asyncio

from src.adapters.database.connection import AsyncSessionLocal
from src.adapters.database.repositories.stock_universe_repository import (
    StockUniverseRepository,
)
from src.application.domain.strategy.strategy_service import StrategyService
from src.settings.config import settings


async def run() -> None:
    if not settings.etf_universe_enabled:
        raise SystemExit(
            "ETF_UNIVERSE_ENABLED=false 입니다. .env에서 true로 켠 뒤 실행하세요."
        )

    service = StrategyService()
    async with AsyncSessionLocal() as session:
        result = await service.refresh_universe(session)
        print("refresh_universe:", result)

        repo = StockUniverseRepository(session)
        etf = await repo.get_scan_stocks(market=None, include_etf=True, limit=1000)
        etf_only = [s for s in etf if s.market == "ETF"]
        non_etf = [s for s in etf if s.market != "ETF"]
        print(f"활성 스캔 대상: 총 {len(etf)} | ETF {len(etf_only)} | 개별주 {len(non_etf)}")
        for s in etf_only[:10]:
            print(f"  {s.symbol} {s.name} cap={s.market_cap}")
        if non_etf:
            print("⚠️ 개별주가 남아있음:", [s.symbol for s in non_etf][:10])


if __name__ == "__main__":
    asyncio.run(run())
