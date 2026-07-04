# -*- coding: utf-8 -*-
"""
KIS Strategy & Alert Server - Main Application

FastAPI 애플리케이션 진입점
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    from src.adapters.external.kis_api.auth import format_token_expires_in, get_kis_auth
    from src.adapters.external.kis_api.client import get_kis_client

    # Startup
    print("=" * 60)
    print(f"🚀 Starting {settings.app_name} v{settings.app_version}")
    print("=" * 60)
    print(f"📍 Environment: {settings.env}")
    print(
        f"💰 Trading Mode: {'Paper Trading (모의투자)' if settings.is_paper_trading else 'Real Trading (실전투자)'}"
    )
    print(f"🔗 KIS API URL: {settings.kis_base_url}")
    print(f"🗄️  Database: {settings.database_url.split('@')[1]}")  # Hide credentials
    redis_display = (
        settings.redis_url.split("@")[-1] if "@" in settings.redis_url else settings.redis_url
    )
    print(f"📦 Redis: {redis_display}")
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
            await kis_auth.get_access_token()
            expires_in = format_token_expires_in(kis_auth.token_info)
            print(f"✅ KIS API token issued (expires in {expires_in})")

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

    # 6. Telegram 알림 스케줄러 시작
    notification_scheduler = None
    try:
        from src.application.domain.strategy.notification_scheduler import (
            get_notification_scheduler,
        )

        notification_scheduler = get_notification_scheduler()
        await notification_scheduler.start()
        if settings.telegram_enabled:
            print(
                "✅ Telegram notification scheduler started "
                "(Data: 09:20/11:20/12:20/14:20, Alert: 09:30/11:30/12:30/14:30)"
            )
        else:
            print("⏭️  Telegram notification is disabled")
    except Exception as e:
        print(f"⚠️  Notification scheduler start failed: {e}")

    # 7. OHLCV 캐시 스케줄러 시작
    ohlcv_scheduler = None
    try:
        from src.application.domain.ohlcv.scheduler import get_ohlcv_scheduler

        ohlcv_scheduler = get_ohlcv_scheduler()
        await ohlcv_scheduler.start()
        print("✅ OHLCV cache scheduler started (cleanup: 02:00, update: 16:30)")
    except Exception as e:
        print(f"⚠️  OHLCV cache scheduler start failed: {e}")

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
        if ohlcv_scheduler:
            await ohlcv_scheduler.stop()
        print("✅ OHLCV cache scheduler stopped")
    except Exception as e:
        print(f"⚠️  OHLCV cache scheduler stop error: {e}")

    try:
        if notification_scheduler:
            await notification_scheduler.stop()
        print("✅ Notification scheduler stopped")
    except Exception as e:
        print(f"⚠️  Notification scheduler stop error: {e}")

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

    # KIS API httpx.AsyncClient 리소스 정리
    try:
        kis_auth = get_kis_auth()
        await kis_auth.aclose()
        kis_client = get_kis_client()
        await kis_client.aclose()
        print("✅ KIS API connections closed")
    except Exception as e:
        print(f"⚠️  KIS API close error: {e}")

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
    description="한국투자증권 Open API 기반 전략 실행 및 알림 서비스",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

# Static files (CSS)
from pathlib import Path

from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent.parent
app.mount(
    "/static/styles", StaticFiles(directory=str(BASE_DIR / "static" / "styles")), name="styles"
)
app.mount("/static/js", StaticFiles(directory=str(BASE_DIR / "static" / "js")), name="js")

# CORS 미들웨어 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

# 접근 로깅 미들웨어 추가 (/page/ 경로 외부 접근 기록)
from src.application.common.middleware import AccessLoggingMiddleware

app.add_middleware(AccessLoggingMiddleware)


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
    """헬스체크 엔드포인트 - 실제 인프라 연결 상태 확인"""
    from src.adapters.cache.redis_client import get_redis_client
    from src.adapters.database.connection import get_async_session

    status_result: dict[str, str] = {"status": "healthy"}

    # DB 상태 확인
    try:
        async with get_async_session() as session:
            await session.execute(__import__("sqlalchemy").text("SELECT 1"))
        status_result["database"] = "connected"
    except Exception:
        status_result["database"] = "disconnected"
        status_result["status"] = "degraded"

    # Redis 상태 확인
    try:
        redis_client = await get_redis_client()
        await redis_client.ping()
        status_result["redis"] = "connected"
    except Exception:
        status_result["redis"] = "disconnected"
        status_result["status"] = "degraded"

    # KIS API 토큰 상태 확인
    try:
        from src.adapters.external.kis_api.auth import get_kis_auth

        kis_auth = get_kis_auth()
        has_token = kis_auth.token_info is not None and kis_auth.token_info.is_valid
        status_result["kis_api"] = "authenticated" if has_token else "unauthenticated"
    except Exception:
        status_result["kis_api"] = "unavailable"

    return status_result


# ==================== Error Handlers ====================

from src.settings.exception_handlers import register_exception_handlers

register_exception_handlers(app)


# ==================== Router 등록 ====================

from src.application.common.dependencies import verify_admin_access
from src.application.interface.api.access_log_router import router as access_log_router
from src.application.interface.api.account_router import router as account_router
from src.application.interface.api.auth_router import router as auth_router
from src.application.interface.api.backtest_router import router as backtest_router
from src.application.interface.api.market_data_router import router as market_data_router
from src.application.interface.api.ops_router import router as ops_router

from src.application.interface.api.order_router import router as order_router
from src.application.interface.api.recommendation_router import router as recommendation_router
from src.application.interface.api.screener_router import router as screener_router
from src.application.interface.api.strategy_router import admin_router as strategy_admin_router
from src.application.interface.api.strategy_router import router as strategy_router
from src.application.interface.api.websocket_router import router as websocket_router
from src.application.interface.page import mypage_routers, public_page_routers

app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(market_data_router, prefix="/api/v1/market", tags=["MarketData"])
app.include_router(account_router, prefix="/api/v1/accounts", tags=["Account"])
app.include_router(order_router, prefix="/api/v1/orders", tags=["Order"])
app.include_router(ops_router)
app.include_router(strategy_router, prefix="/api/v1/strategies", tags=["Strategy"])

# 전략 생성/수정/삭제 같은 관리자 전용 라우트는 기본 비활성(완전 비노출)
if settings.enable_admin_strategy_routes:
    app.include_router(
        strategy_admin_router,
        prefix="/api/v1/strategies",
        tags=["Strategy(Admin)"],
    )

app.include_router(screener_router)  # 내부 prefix: /api/v1/screener
app.include_router(recommendation_router)  # 내부 prefix: /api/v1/recommendations
app.include_router(backtest_router)  # 내부 prefix: /api/v1/backtest
app.include_router(access_log_router)  # 내부 prefix: /api/v1/access-logs
app.include_router(websocket_router, prefix="/ws", tags=["WebSocket"])

# /mypage/* admin pages are IP-gated at include time so individual page routers stay simple/testable.
for page_router in mypage_routers:
    app.include_router(page_router, dependencies=[Depends(verify_admin_access)])

for page_router in public_page_routers:
    app.include_router(page_router)


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
