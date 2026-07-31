# -*- coding: utf-8 -*-
"""Operations Router - 운영 대시보드/요약 API"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter

from src.adapters.external.websocket.kis_websocket import get_kis_websocket
from src.adapters.external.telegram import get_telegram_notifier
from src.application.common.dependencies import (
    AdminAccessDep,
    DatabaseSession,
    KISAuthDep,
    KISClientDep,
    RedisDep,
    StrategyServiceDep,
)
from src.application.common.dto import ResponseDTO
from src.application.domain.account.service import AccountService
from src.application.domain.auth.service import AuthService
from src.application.domain.order.service import OrderService
from src.application.domain.strategy.notification_scheduler import get_notification_scheduler
from src.application.domain.strategy.scheduler import get_strategy_scheduler
from src.settings.config import get_settings

router = APIRouter(prefix="/api/v1/ops", tags=["Operations"])


def _to_float(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _serialize_positions(positions: list[Any], limit: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "symbol": position.symbol,
            "name": position.symbol_name,
            "quantity": position.quantity,
            "profit_loss": _to_float(position.profit_loss),
            "profit_loss_rate": _to_float(position.profit_loss_rate),
        }
        for position in positions[:limit]
    ]


async def _build_health(account_service: AccountService) -> dict[str, str]:
    status = {
        "status": "healthy",
        "database": "connected",
        "redis": "connected",
        "kis_api": "connected",
    }
    try:
        await account_service.get_account_balance(use_cache=True)
        status["kis_api"] = "authenticated"
    except Exception:
        status["status"] = "degraded"
        status["kis_api"] = "error"
    return status


@router.get(
    "/notification-scheduler-status",
    response_model=ResponseDTO[dict[str, Any]],
    summary="알림 스케줄러 상태 조회",
)
async def notification_scheduler_status(
    _: AdminAccessDep,
) -> ResponseDTO[dict[str, Any]]:
    scheduler = get_notification_scheduler()
    return ResponseDTO.success_response(
        scheduler.get_status(),
        "Notification scheduler status loaded",
    )


@router.get(
    "/summary",
    response_model=ResponseDTO[dict[str, Any]],
    summary="운영 요약 조회",
)
async def ops_summary(
    _: AdminAccessDep,
    kis_auth: KISAuthDep,
    kis_client: KISClientDep,
    redis_client: RedisDep,
    strategy_service: StrategyServiceDep,
    session: DatabaseSession,
) -> ResponseDTO[dict[str, Any]]:
    settings = get_settings()
    auth_service = AuthService(kis_auth)
    account_service = AccountService(kis_client, redis_client)
    order_service = OrderService(kis_client, session)
    strategy_scheduler = get_strategy_scheduler()
    notification_scheduler = get_notification_scheduler()
    websocket_client = get_kis_websocket()
    notifier = get_telegram_notifier()

    alerts: list[dict[str, str]] = []

    balance = await account_service.get_account_balance(use_cache=True)
    positions = await account_service.get_position_list()
    orders = await order_service.get_order_list()
    strategies = await strategy_service.get_strategy_list(limit=20, offset=0)
    cash_plan = await strategy_service.get_portfolio_cash_plan(target_cash_ratio=0.30)
    recommendation = await strategy_service.get_golden_cross_recommendations(
        gc_only=True,
        include_etf=True,
        top_n=5,
        top_industries_n=3,
    )
    sell_history = await strategy_service.list_analysis_history(
        "sell",
        is_active=True,
        limit=20,
        offset=0,
    )
    health = await _build_health(account_service)

    token_status: dict[str, Any]
    try:
        token = await auth_service.get_token_status()
        token_status = {
            "is_valid": token.is_valid,
            "expires_at": token.expires_at.isoformat(),
            "remaining_seconds": token.remaining_seconds,
            "environment": token.environment,
        }
        if token.remaining_seconds < 3600:
            alerts.append(
                {
                    "severity": "warning",
                    "title": "KIS token",
                    "message": "토큰 만료가 1시간 이내입니다.",
                }
            )
    except Exception as exc:
        token_status = {"is_valid": False, "error": str(exc)}
        alerts.append(
            {
                "severity": "critical",
                "title": "KIS token",
                "message": "토큰 상태를 확인할 수 없습니다.",
            }
        )

    strategy_status = strategy_scheduler.get_status()
    notification_status = notification_scheduler.get_status()

    pending_orders = sum(1 for item in orders.orders if item.remaining_quantity > 0)
    negative_positions = sum(1 for item in positions.positions if item.profit_loss < 0)
    active_strategies = [
        item for item in strategies.strategies if item.status.upper() in {"ACTIVE", "RUNNING"}
    ]

    if not notification_status.get("telegram_enabled"):
        alerts.append(
            {
                "severity": "warning",
                "title": "Telegram",
                "message": "Telegram 알림이 비활성화되어 있습니다.",
            }
        )
    if not notification_status.get("is_running"):
        alerts.append(
            {
                "severity": "critical",
                "title": "Notification scheduler",
                "message": "알림 스케줄러가 실행 중이 아닙니다.",
            }
        )
    if not strategy_status.get("is_running"):
        alerts.append(
            {
                "severity": "critical",
                "title": "Strategy scheduler",
                "message": "전략 스케줄러가 실행 중이 아닙니다.",
            }
        )
    if notification_status.get("sell_notification_available") is False:
        alerts.append(
            {
                "severity": "warning",
                "title": "Sell notification",
                "message": "매도 정보 Telegram 메시지 스케줄러가 제거되었습니다. (SELL_NOTIFICATION_ENABLED=false)",
            }
        )
    if pending_orders:
        alerts.append(
            {
                "severity": "info",
                "title": "Pending orders",
                "message": f"미체결 주문 {pending_orders}건이 있습니다.",
            }
        )
    if (
        cash_plan.current_cash_ratio is not None
        and cash_plan.target_cash_ratio > cash_plan.current_cash_ratio
    ):
        alerts.append(
            {
                "severity": "warning",
                "title": "Cash buffer",
                "message": "목표 현금 비중이 현재 현금 비중보다 높습니다.",
            }
        )

    data = {
        "generated_at": datetime.now().isoformat(),
        "service": {
            "name": settings.app_name,
            "version": settings.app_version,
            "env": settings.env,
            "trading_environment": settings.trading_environment,
            "is_paper_trading": settings.is_paper_trading,
            "dashboard_refresh_interval": settings.dashboard_refresh_interval,
        },
        "health": health,
        "token": token_status,
        "schedulers": {
            "strategy": strategy_status,
            "notification": notification_status,
        },
        "websocket": {
            "connected": bool(getattr(websocket_client, "is_running", False)),
            "subscribed_count": len(getattr(websocket_client, "subscriptions", {})),
        },
        "telegram": {
            "enabled": bool(getattr(notifier, "enabled", False)),
            "chat_configured": bool(settings.telegram_chat_id),
        },
        "account": {
            "account_no": balance.account_no,
            "total_balance": _to_float(balance.total_balance),
            "cash_balance": _to_float(balance.cash_balance),
            "available_amount": _to_float(balance.available_amount),
            "total_profit_loss": _to_float(balance.total_profit_loss),
            "total_profit_loss_rate": _to_float(balance.total_profit_loss_rate),
            "position_count": positions.total_count,
            "negative_position_count": negative_positions,
        },
        "positions": {
            "total_count": positions.total_count,
            "top": _serialize_positions(positions.positions),
        },
        "orders": {
            "total_count": orders.total_count,
            "pending_count": pending_orders,
            "recent": [
                {
                    "symbol": order.symbol,
                    "status": order.status,
                    "remaining_quantity": order.remaining_quantity,
                    "filled_quantity": order.filled_quantity,
                    "order_time": order.order_time.isoformat(),
                }
                for order in orders.orders[:5]
            ],
        },
        "strategies": {
            "total_count": strategies.total_count,
            "active_count": len(active_strategies),
            "items": [
                {
                    "strategy_id": item.strategy_id,
                    "name": item.name,
                    "status": item.status,
                    "symbols": item.symbols[:5],
                    "last_executed_at": item.last_executed_at.isoformat()
                    if item.last_executed_at
                    else None,
                    "success_rate": item.success_rate,
                }
                for item in strategies.strategies[:5]
            ],
        },
        "buy_recommendations": {
            "buy_candidate_count": recommendation.buy_candidate_count,
            "top_stocks": [
                {
                    "symbol": stock.symbol,
                    "name": stock.name,
                    "market": stock.market,
                    "current_price": _to_float(stock.current_price),
                    "screening_score": _to_float(stock.screening_score),
                }
                for stock in recommendation.top_stocks
            ],
            "top_industries": [
                industry.model_dump(mode="json") for industry in recommendation.top_industries
            ],
            "errors": recommendation.errors,
            "scan_time": recommendation.scan_time.isoformat(),
        },
        "sell_watchlist": {
            "active_tracking_count": sell_history.total_count,
            "items": [
                {
                    "symbol": item.symbol,
                    "name": item.name,
                    "final_stage": getattr(
                        getattr(item, "final_stage", None) or item.sell_stage,
                        "value",
                        getattr(item, "final_stage", None) or item.sell_stage,
                    ),
                    "sell_stage": getattr(item.sell_stage, "value", item.sell_stage),
                    "entry_price": _to_float(item.entry_price),
                    "current_price": _to_float(item.current_price),
                    "is_active": item.is_active,
                }
                for item in sell_history.items[:5]
            ],
        },
        "cash_plan": cash_plan.model_dump(mode="json"),
        "alerts": alerts,
    }
    return ResponseDTO.success_response(data, "Operations summary loaded")
