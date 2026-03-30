# -*- coding: utf-8 -*-
"""
모든 종목 활성화 - stock_universe의 모든 종목을 eligible 상태로 만듦
"""

import asyncio

from src.adapters.database.connection import get_db


async def activate_all():
    """모든 종목 활성화"""
    print("=" * 80)
    print("📈 모든 종목 활성화")
    print("=" * 80)

    db_gen = get_db()
    session = await db_gen.__anext__()

    try:
        from sqlalchemy import text

        # 현재 상태 확인
        result = await session.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE is_active = true) as active,
                COUNT(*) FILTER (WHERE is_tradable = true) as tradable,
                COUNT(*) FILTER (WHERE passed_market_cap = true AND passed_volume = true
                                  AND is_active = true AND is_tradable = true
                                  AND (is_excluded = false OR is_excluded IS NULL)) as eligible
            FROM stock_universe
        """))
        row = result.fetchone()
        print(f"\n현재 상태:")
        print(f"  - 총 종목: {row[0]}개")
        print(f"  - Active: {row[1]}개")
        print(f"  - Tradable: {row[2]}개")
        print(f"  - Eligible: {row[3]}개")

        # 모든 종목 활성화
        result = await session.execute(text("""
            UPDATE stock_universe
            SET
                is_active = true,
                is_tradable = true,
                is_excluded = false,
                passed_market_cap = true,
                passed_volume = true,
                updated_at = NOW()
            WHERE is_active IS NULL OR is_active = false
               OR is_tradable IS NULL OR is_tradable = false
        """))
        updated = result.rowcount
        await session.commit()

        # 최종 상태 확인
        result = await session.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE is_active = true) as active,
                COUNT(*) FILTER (WHERE is_tradable = true) as tradable,
                COUNT(*) FILTER (WHERE passed_market_cap = true AND passed_volume = true
                                  AND is_active = true AND is_tradable = true
                                  AND (is_excluded = false OR is_excluded IS NULL)) as eligible,
                COUNT(*) FILTER (WHERE market = 'KOSPI') as kospi,
                COUNT(*) FILTER (WHERE market = 'KOSDAQ') as kosdaq
            FROM stock_universe
        """))
        row = result.fetchone()

        print(f"\n활성화 완료: {updated}개 종목 업데이트")
        print(f"\n최종 상태:")
        print(f"  - 총 종목: {row[0]}개")
        print(f"  - Active: {row[1]}개")
        print(f"  - Tradable: {row[2]}개")
        print(f"  - Eligible: {row[3]}개")
        print(f"  - KOSPI: {row[4]}개")
        print(f"  - KOSDAQ: {row[5]}개")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ 오류: {e}")
        import traceback
        traceback.print_exc()
        await session.rollback()
    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(activate_all())
