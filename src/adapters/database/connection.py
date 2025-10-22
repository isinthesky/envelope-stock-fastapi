# -*- coding: utf-8 -*-
"""
Database Connection - SQLAlchemy Async Engine 및 Session 관리
"""

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.settings.config import settings


# ==================== Base Model ====================


class Base(DeclarativeBase):
    """SQLAlchemy Base Model"""

    pass


# ==================== Engine 및 SessionMaker ====================


def create_engine() -> AsyncEngine:
    """
    비동기 SQLAlchemy Engine 생성

    Returns:
        AsyncEngine: 비동기 데이터베이스 엔진
    """
    return create_async_engine(
        settings.database_url,
        echo=settings.database_echo,
        pool_pre_ping=True,  # 연결 상태 체크
        pool_size=10,  # 커넥션 풀 크기
        max_overflow=20,  # 최대 overflow 연결 수
        pool_recycle=3600,  # 1시간마다 연결 재활용
    )


# 전역 Engine 및 SessionMaker
engine: AsyncEngine = create_engine()
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # commit 후 객체 expire 방지
    autoflush=False,  # 자동 flush 비활성화
    autocommit=False,  # 자동 commit 비활성화
)


# ==================== Session Dependency ====================


async def get_db() -> AsyncIterator[AsyncSession]:
    """
    FastAPI Dependency로 사용할 Database Session

    Yields:
        AsyncSession: 비동기 데이터베이스 세션
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """
    백그라운드 태스크에서 사용할 Database Session

    Yields:
        AsyncSession: 비동기 데이터베이스 세션
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ==================== Database 생명주기 ====================


async def init_db() -> None:
    """
    데이터베이스 초기화 (테이블 생성)

    Note:
        운영 환경에서는 Alembic 마이그레이션 사용 권장
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """데이터베이스 연결 종료"""
    await engine.dispose()
