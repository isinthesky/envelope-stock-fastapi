# -*- coding: utf-8 -*-
"""
Database Tables Initialization Script

OHLCV 캐시 테이블 포함한 모든 DB 테이블을 초기화합니다.
"""

import asyncio

from src.adapters.database.connection import init_db, engine
from src.adapters.database.models import (
    OHLCVModel,
    OrderModel,
    AccountModel,
    PositionModel,
    StrategyModel,
)


async def main():
    """테이블 초기화 실행"""
    print("=" * 80)
    print("🗄️  Database Tables Initialization")
    print("=" * 80)

    try:
        # 모든 모델 임포트 확인
        models = [
            OHLCVModel,
            OrderModel,
            AccountModel,
            PositionModel,
            StrategyModel,
        ]
        print(f"\n📋 등록된 모델: {len(models)}개")
        for model in models:
            print(f"  - {model.__tablename__}")

        # 테이블 생성
        print(f"\n🔨 테이블 생성 중...")
        await init_db()
        print(f"✅ 테이블 생성 완료!")

        # 생성된 테이블 확인
        print(f"\n🔍 생성된 테이블 확인 중...")
        from sqlalchemy import text
        async with engine.begin() as conn:
            # PostgreSQL 테이블 목록 조회
            result = await conn.execute(
                text("""
                    SELECT tablename
                    FROM pg_catalog.pg_tables
                    WHERE schemaname = 'public'
                    ORDER BY tablename
                """)
            )
            tables = result.fetchall()

            if tables:
                print(f"✅ 총 {len(tables)}개 테이블 확인:")
                for table in tables:
                    print(f"  - {table[0]}")
            else:
                print("⚠️ 생성된 테이블이 없습니다.")

        print("\n" + "=" * 80)
        print("🎉 데이터베이스 초기화 완료!")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ 초기화 실패: {e}")
        raise
    finally:
        from src.adapters.database.connection import close_db
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
