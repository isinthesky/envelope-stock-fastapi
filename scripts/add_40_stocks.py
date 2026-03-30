# -*- coding: utf-8 -*-
"""
성능 테스트용 - KOSPI 20개 + KOSDAQ 20개 종목 추가
"""

import asyncio
from datetime import datetime
from decimal import Decimal

from src.adapters.database.connection import get_db


# 코스피 20개 (대형주 위주)
KOSPI_STOCKS = [
    {"symbol": "005930", "name": "삼성전자", "market": "KOSPI", "market_cap": Decimal("400_000_000_000_000")},
    {"symbol": "000660", "name": "SK하이닉스", "market": "KOSPI", "market_cap": Decimal("120_000_000_000_000")},
    {"symbol": "373220", "name": "LG에너지솔루션", "market": "KOSPI", "market_cap": Decimal("85_000_000_000_000")},
    {"symbol": "005380", "name": "현대차", "market": "KOSPI", "market_cap": Decimal("50_000_000_000_000")},
    {"symbol": "000270", "name": "기아", "market": "KOSPI", "market_cap": Decimal("35_000_000_000_000")},
    {"symbol": "035420", "name": "NAVER", "market": "KOSPI", "market_cap": Decimal("33_000_000_000_000")},
    {"symbol": "035720", "name": "카카오", "market": "KOSPI", "market_cap": Decimal("20_000_000_000_000")},
    {"symbol": "055550", "name": "신한지주", "market": "KOSPI", "market_cap": Decimal("22_000_000_000_000")},
    {"symbol": "105560", "name": "KB금융", "market": "KOSPI", "market_cap": Decimal("25_000_000_000_000")},
    {"symbol": "005490", "name": "POSCO홀딩스", "market": "KOSPI", "market_cap": Decimal("20_000_000_000_000")},
    {"symbol": "051910", "name": "LG화학", "market": "KOSPI", "market_cap": Decimal("25_000_000_000_000")},
    {"symbol": "006400", "name": "삼성SDI", "market": "KOSPI", "market_cap": Decimal("22_000_000_000_000")},
    {"symbol": "068270", "name": "셀트리온", "market": "KOSPI", "market_cap": Decimal("18_000_000_000_000")},
    {"symbol": "012330", "name": "현대모비스", "market": "KOSPI", "market_cap": Decimal("18_000_000_000_000")},
    {"symbol": "066570", "name": "LG전자", "market": "KOSPI", "market_cap": Decimal("14_000_000_000_000")},
    {"symbol": "259960", "name": "크래프톤", "market": "KOSPI", "market_cap": Decimal("15_000_000_000_000")},
    {"symbol": "329180", "name": "HD현대중공업", "market": "KOSPI", "market_cap": Decimal("15_000_000_000_000")},
    {"symbol": "012450", "name": "한화에어로스페이스", "market": "KOSPI", "market_cap": Decimal("12_000_000_000_000")},
    {"symbol": "138040", "name": "메리츠금융지주", "market": "KOSPI", "market_cap": Decimal("10_000_000_000_000")},
    {"symbol": "047810", "name": "한국항공우주", "market": "KOSPI", "market_cap": Decimal("8_000_000_000_000")},
]

# 코스닥 20개 (대형주 위주)
KOSDAQ_STOCKS = [
    {"symbol": "247540", "name": "에코프로비엠", "market": "KOSDAQ", "market_cap": Decimal("15_000_000_000_000")},
    {"symbol": "086520", "name": "에코프로", "market": "KOSDAQ", "market_cap": Decimal("12_000_000_000_000")},
    {"symbol": "196170", "name": "알테오젠", "market": "KOSDAQ", "market_cap": Decimal("10_000_000_000_000")},
    {"symbol": "403870", "name": "HPSP", "market": "KOSDAQ", "market_cap": Decimal("5_000_000_000_000")},
    {"symbol": "058470", "name": "리노공업", "market": "KOSDAQ", "market_cap": Decimal("4_500_000_000_000")},
    {"symbol": "277810", "name": "레인보우로보틱스", "market": "KOSDAQ", "market_cap": Decimal("4_000_000_000_000")},
    {"symbol": "066970", "name": "엘앤에프", "market": "KOSDAQ", "market_cap": Decimal("4_000_000_000_000")},
    {"symbol": "035900", "name": "JYP Ent.", "market": "KOSDAQ", "market_cap": Decimal("3_500_000_000_000")},
    {"symbol": "357780", "name": "솔브레인", "market": "KOSDAQ", "market_cap": Decimal("3_000_000_000_000")},
    {"symbol": "263750", "name": "펄어비스", "market": "KOSDAQ", "market_cap": Decimal("3_000_000_000_000")},
    {"symbol": "028300", "name": "HLB", "market": "KOSDAQ", "market_cap": Decimal("3_000_000_000_000")},
    {"symbol": "039030", "name": "이오테크닉스", "market": "KOSDAQ", "market_cap": Decimal("3_000_000_000_000")},
    {"symbol": "293490", "name": "카카오게임즈", "market": "KOSDAQ", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "041510", "name": "에스엠", "market": "KOSDAQ", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "240810", "name": "원익IPS", "market": "KOSDAQ", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "140860", "name": "파크시스템스", "market": "KOSDAQ", "market_cap": Decimal("2_500_000_000_000")},
    {"symbol": "036930", "name": "주성엔지니어링", "market": "KOSDAQ", "market_cap": Decimal("2_000_000_000_000")},
    {"symbol": "145020", "name": "휴젤", "market": "KOSDAQ", "market_cap": Decimal("2_000_000_000_000")},
    {"symbol": "141080", "name": "레고켐바이오", "market": "KOSDAQ", "market_cap": Decimal("2_000_000_000_000")},
    {"symbol": "112040", "name": "위메이드", "market": "KOSDAQ", "market_cap": Decimal("2_000_000_000_000")},
]

ALL_STOCKS = KOSPI_STOCKS + KOSDAQ_STOCKS


async def add_stocks():
    """종목 추가 실행"""
    print("=" * 80)
    print("성능 테스트용 - KOSPI 20개 + KOSDAQ 20개 종목 추가")
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

        for stock in ALL_STOCKS:
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

        # 최종 상태 확인 (마켓별 카운트)
        result = await session.execute(text("""
            SELECT market, COUNT(*) as cnt
            FROM stock_universe
            GROUP BY market
        """))
        market_counts = {row[0]: row[1] for row in result.fetchall()}

        result = await session.execute(text("SELECT COUNT(*) FROM stock_universe"))
        after_count = result.scalar()

        print("\n" + "=" * 80)
        print("📊 결과 요약")
        print(f"  - 추가됨: {added}개")
        print(f"  - 스킵됨: {skipped}개")
        print(f"  - 총 종목 수: {before_count}개 → {after_count}개")
        for market, cnt in market_counts.items():
            print(f"  - {market}: {cnt}개")
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
