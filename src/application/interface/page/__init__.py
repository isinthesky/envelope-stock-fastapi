# -*- coding: utf-8 -*-
"""
Page Router Package - 도메인별 관리 페이지
"""
from src.application.interface.page.main_page_router import router as main_page_router
from src.application.interface.page.auth_page_router import router as auth_page_router
from src.application.interface.page.account_page_router import router as account_page_router
from src.application.interface.page.market_data_page_router import (
    router as market_data_page_router,
)
from src.application.interface.page.order_page_router import router as order_page_router
from src.application.interface.page.strategy_page_router import (
    router as strategy_page_router,
)
from src.application.interface.page.backtest_page_router import (
    router as backtest_page_router,
)
from src.application.interface.page.websocket_page_router import (
    router as websocket_page_router,
)
from src.application.interface.page.sell_strategy_page_router import (
    router as sell_strategy_page_router,
)

# 모든 페이지 라우터 리스트
page_routers = [
    main_page_router,
    auth_page_router,
    account_page_router,
    market_data_page_router,
    order_page_router,
    strategy_page_router,
    sell_strategy_page_router,
    backtest_page_router,
    websocket_page_router,
]

__all__ = [
    "main_page_router",
    "auth_page_router",
    "account_page_router",
    "market_data_page_router",
    "order_page_router",
    "strategy_page_router",
    "sell_strategy_page_router",
    "backtest_page_router",
    "websocket_page_router",
    "page_routers",
]

