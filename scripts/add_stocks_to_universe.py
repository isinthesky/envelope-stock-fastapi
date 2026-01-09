# -*- coding: utf-8 -*-
"""
Add Stocks to Universe - 시가총액 상위 종목 추가

stock_universe 테이블에 시가총액 상위 종목을 추가합니다.
기존 20개에 30개를 추가하여 총 50개로 확장합니다.
"""

import asyncio
from datetime import datetime
from decimal import Decimal

from src.adapters.database.connection import get_db


# 추가할 종목 목록 (시가총액 상위 50 기준, 기존 20개 제외)
ADDITIONAL_STOCKS = [
    # KOSPI 대형주
    {"symbol": "000270", "name": "기아", "market": "KOSPI", "market_cap": Decimal("35_000_000_000_000")},
    {"symbol": "055550", "name": "신한지주", "market": "KOSPI", "market_cap": Decimal("22_000_000_000_000")},
    {"symbol": "003670", "name": "포스코퓨처엠", "market": "KOSPI", "market_cap": Decimal("15_000_000_000_000")},
    {"symbol": "086790", "name": "하나금융지주", "market": "KOSPI", "market_cap": Decimal("14_000_000_000_000")},
    {"symbol": "034020", "name": "두산에너빌리티", "market": "KOSPI", "market_cap": Decimal("13_000_000_000_000")},
    {"symbol": "096770", "name": "SK이노베이션", "market": "KOSPI", "market_cap": Decimal("12_000_000_000_000")},
    {"symbol": "032830", "name": "삼성생명", "market": "KOSPI", "market_cap": Decimal("11_500_000_000_000")},
    {"symbol": "009150", "name": "삼성전기", "market": "KOSPI", "market_cap": Decimal("11_000_000_000_000")},
    {"symbol": "010130", "name": "고려아연", "market": "KOSPI", "market_cap": Decimal("10_500_000_000_000")},
    {"symbol": "028260", "name": "삼성물산", "market": "KOSPI", "market_cap": Decimal("10_000_000_000_000")},
    {"symbol": "018260", "name": "삼성에스디에스", "market": "KOSPI", "market_cap": Decimal("9_500_000_000_000")},
    {"symbol": "003490", "name": "대한항공", "market": "KOSPI", "market_cap": Decimal("9_000_000_000_000")},
    {"symbol": "011200", "name": "HMM", "market": "KOSPI", "market_cap": Decimal("8_500_000_000_000")},
    {"symbol": "010950", "name": "S-Oil", "market": "KOSPI", "market_cap": Decimal("8_000_000_000_000")},
    {"symbol": "000810", "name": "삼성화재", "market": "KOSPI", "market_cap": Decimal("7_500_000_000_000")},
    {"symbol": "015760", "name": "한국전력", "market": "KOSPI", "market_cap": Decimal("7_000_000_000_000")},
    {"symbol": "011170", "name": "롯데케미칼", "market": "KOSPI", "market_cap": Decimal("6_500_000_000_000")},
    {"symbol": "033780", "name": "KT&G", "market": "KOSPI", "market_cap": Decimal("6_000_000_000_000")},
    {"symbol": "030200", "name": "KT", "market": "KOSPI", "market_cap": Decimal("5_500_000_000_000")},
    {"symbol": "032640", "name": "LG유플러스", "market": "KOSPI", "market_cap": Decimal("5_000_000_000_000")},

    # KOSDAQ 대형주
    {"symbol": "373220", "name": "LG에너지솔루션", "market": "KOSPI", "market_cap": Decimal("85_000_000_000_000")},
    {"symbol": "207940", "name": "삼성바이오로직스", "market": "KOSPI", "market_cap": Decimal("55_000_000_000_000")},
    {"symbol": "352820", "name": "하이브", "market": "KOSPI", "market_cap": Decimal("8_000_000_000_000")},
    {"symbol": "259960", "name": "크래프톤", "market": "KOSPI", "market_cap": Decimal("15_000_000_000_000")},
    {"symbol": "036570", "name": "엔씨소프트", "market": "KOSPI", "market_cap": Decimal("7_000_000_000_000")},

    # 인기 성장주
    {"symbol": "003550", "name": "LG", "market": "KOSPI", "market_cap": Decimal("13_000_000_000_000")},
    {"symbol": "066570", "name": "LG전자", "market": "KOSPI", "market_cap": Decimal("14_000_000_000_000")},
    {"symbol": "034730", "name": "SK", "market": "KOSPI", "market_cap": Decimal("12_000_000_000_000")},
    {"symbol": "017670", "name": "SK텔레콤", "market": "KOSPI", "market_cap": Decimal("11_000_000_000_000")},
    {"symbol": "024110", "name": "기업은행", "market": "KOSPI", "market_cap": Decimal("8_000_000_000_000")},
]


async def add_stocks():
    """종목 추가 실행"""
    print("=" * 80)
    print("📈 Stock Universe 종목 추가")
    print("=" * 80)

    db_gen = get_db()
    session = await db_gen.__anext__()

    try:
        from sqlalchemy import text

        # 현재 상태 확인
        result = await session.execute(text("SELECT COUNT(*) FROM stock_universe"))
        before_count = result.scalar()
        print(f"\n현재 종목 수: {before_count}개")

        # 종목 추가
        added = 0
        skipped = 0

        for stock in ADDITIONAL_STOCKS:
            # 중복 체크
            result = await session.execute(
                text("SELECT symbol FROM stock_universe WHERE symbol = :symbol"),
                {"symbol": stock["symbol"]}
            )
            if result.scalar():
                print(f"  ⏭️ {stock['symbol']} {stock['name']} - 이미 존재")
                skipped += 1
                continue

            # 종목 추가
            await session.execute(
                text("""
                    INSERT INTO stock_universe (
                        symbol, name, market, market_cap,
                        is_active, is_tradable, is_excluded,
                        passed_market_cap, passed_volume,
                        created_at, updated_at
                    ) VALUES (
                        :symbol, :name, :market, :market_cap,
                        true, true, false,
                        true, true,
                        :now, :now
                    )
                """),
                {
                    "symbol": stock["symbol"],
                    "name": stock["name"],
                    "market": stock["market"],
                    "market_cap": stock["market_cap"],
                    "now": datetime.now(),
                }
            )

            cap_trillion = float(stock["market_cap"]) / 1_000_000_000_000
            print(f"  ✅ {stock['symbol']} {stock['name']} ({cap_trillion:.1f}조) 추가")
            added += 1

        await session.commit()

        # 최종 상태 확인
        result = await session.execute(text("SELECT COUNT(*) FROM stock_universe"))
        after_count = result.scalar()

        print("\n" + "=" * 80)
        print(f"📊 결과 요약")
        print(f"  - 추가됨: {added}개")
        print(f"  - 스킵됨: {skipped}개")
        print(f"  - 총 종목 수: {before_count}개 → {after_count}개")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ 오류: {e}")
        import traceback
        traceback.print_exc()
        await session.rollback()
    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(add_stocks())
