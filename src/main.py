# -*- coding: utf-8 -*-
"""
KIS Trading API Service - Main Application

FastAPI 애플리케이션 진입점
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.settings.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    애플리케이션 생명주기 관리

    시작 시: 데이터베이스 연결, Redis 연결, KIS API 토큰 발급
    종료 시: 리소스 정리
    """
    from src.adapters.cache.redis_client import get_redis_client
    from src.adapters.database.connection import close_db, engine
    from src.adapters.external.kis_api.auth import get_kis_auth

    # Startup
    print("=" * 60)
    print(f"🚀 Starting {settings.app_name} v{settings.app_version}")
    print("=" * 60)
    print(f"📍 Environment: {settings.env}")
    print(f"💰 Trading Mode: {'Paper Trading (모의투자)' if settings.is_paper_trading else 'Real Trading (실전투자)'}")
    print(f"🔗 KIS API URL: {settings.kis_base_url}")
    print(f"🗄️  Database: {settings.database_url.split('@')[1]}")  # Hide credentials
    print(f"📦 Redis: {settings.redis_url}")
    print("=" * 60)

    # 1. Database 연결 확인
    try:
        from sqlalchemy import text
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        print("✅ Database connection established")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        raise

    # 2. Redis 연결 초기화
    try:
        redis_client = await get_redis_client()
        is_connected = await redis_client.ping()
        if is_connected:
            print("✅ Redis connection established")
        else:
            print("❌ Redis connection failed")
            raise Exception("Redis ping failed")
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        raise

    # 3. KIS API 토큰 발급 (자동 갱신 활성화 시)
    token_refresh_task = None
    try:
        if settings.auto_reauth:
            from src.application.common.background_tasks import get_token_refresh_task

            kis_auth = get_kis_auth()
            token = await kis_auth.get_access_token()
            print(f"✅ KIS API token issued (expires in {kis_auth.token_info.remaining_seconds}s)")

            # 토큰 자동 갱신 백그라운드 태스크 시작
            token_refresh_task = get_token_refresh_task()
            await token_refresh_task.start()
        else:
            print("⏭️  KIS API auto authentication is disabled")
    except Exception as e:
        print(f"⚠️  KIS API token issue failed (will retry on first request): {e}")

    # 4. 전략 실행 엔진 시작 (레거시 볼린저 밴드)
    strategy_engine = None
    try:
        from src.application.domain.strategy.engine import get_strategy_engine

        strategy_engine = get_strategy_engine()
        await strategy_engine.start()
    except Exception as e:
        print(f"⚠️  Strategy engine start failed: {e}")

    # 5. 골든크로스 전략 스케줄러 시작
    gc_scheduler = None
    try:
        from src.application.domain.strategy.scheduler import get_strategy_scheduler

        gc_scheduler = get_strategy_scheduler()
        await gc_scheduler.start()
        print("✅ Golden Cross strategy scheduler started")
    except Exception as e:
        print(f"⚠️  Golden Cross scheduler start failed: {e}")

    print("=" * 60)
    print("🎉 Application startup complete!")
    print("=" * 60)

    yield

    # Shutdown
    print("=" * 60)
    print(f"🛑 Shutting down {settings.app_name}")
    print("=" * 60)

    # 백그라운드 태스크 중지
    try:
        if gc_scheduler:
            await gc_scheduler.stop()
        print("✅ Golden Cross scheduler stopped")
    except Exception as e:
        print(f"⚠️  Golden Cross scheduler stop error: {e}")

    try:
        if strategy_engine:
            await strategy_engine.stop()
    except Exception as e:
        print(f"⚠️  Strategy engine stop error: {e}")

    try:
        if token_refresh_task:
            await token_refresh_task.stop()
    except Exception as e:
        print(f"⚠️  Token refresh task stop error: {e}")

    # Database 연결 종료
    try:
        await close_db()
        print("✅ Database connection closed")
    except Exception as e:
        print(f"⚠️  Database close error: {e}")

    # Redis 연결 종료
    try:
        if redis_client:
            await redis_client.disconnect()
        print("✅ Redis connection closed")
    except Exception as e:
        print(f"⚠️  Redis close error: {e}")

    print("=" * 60)
    print("👋 Goodbye!")
    print("=" * 60)


# FastAPI 애플리케이션 생성
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="한국투자증권 Open API 기반 자동매매 서비스",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url="/openapi.json" if not settings.is_production else None,
    lifespan=lifespan,
)

# CORS 미들웨어 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)


# ==================== Root Endpoint ====================


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    """루트 엔드포인트 - 헬스체크"""
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.env,
        "trading_mode": "paper" if settings.is_paper_trading else "real",
        "status": "running",
    }


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """헬스체크 엔드포인트"""
    # TODO: Database, Redis 연결 상태 확인
    return {
        "status": "healthy",
        "database": "connected",  # TODO: 실제 DB 상태 확인
        "redis": "connected",  # TODO: 실제 Redis 상태 확인
        "kis_api": "connected",  # TODO: KIS API 토큰 상태 확인
    }


# ==================== Error Handlers ====================


@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception) -> JSONResponse:
    """전역 예외 핸들러"""
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "detail": str(exc) if settings.debug else "An unexpected error occurred",
        },
    )


# ==================== Router 등록 ====================

from src.application.interface.api.account_router import router as account_router
from src.application.interface.api.auth_router import router as auth_router
from src.application.interface.api.backtest_router import router as backtest_router
from src.application.interface.api.market_data_router import router as market_data_router
from src.application.interface.api.order_router import router as order_router
from src.application.interface.api.strategy_router import router as strategy_router
from src.application.interface.api.websocket_router import router as websocket_router
from src.application.interface.page.admin_page import router as admin_page_router

app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(market_data_router, prefix="/api/v1/market", tags=["MarketData"])
app.include_router(account_router, prefix="/api/v1/accounts", tags=["Account"])
app.include_router(order_router, prefix="/api/v1/orders", tags=["Order"])
app.include_router(strategy_router, prefix="/api/v1/strategies", tags=["Strategy"])
app.include_router(backtest_router)
app.include_router(websocket_router, prefix="/ws", tags=["WebSocket"])
app.include_router(admin_page_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.uvicorn_reload,
        workers=settings.uvicorn_workers,
        log_level=settings.log_level.lower(),
    )
