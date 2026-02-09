# -*- coding: utf-8 -*-
"""Page Router Package - 도메인별 관리 페이지

- /mypage/* : 관리자 페이지 (nav bar 포함)
- /page/ : 공개용 Buy 전략 페이지 (nav bar 없음)
"""

from src.application.interface.page.access_logs_page_router import (
    router as access_logs_page_router,
)
from src.application.interface.page.account_page_router import (
    router as account_page_router,
)
from src.application.interface.page.auth_page_router import router as auth_page_router
from src.application.interface.page.backtest_page_router import (
    router as backtest_page_router,
)
from src.application.interface.page.main_page_router import router as main_page_router
from src.application.interface.page.market_data_page_router import (
    router as market_data_page_router,
)
from src.application.interface.page.ohlcv_page_router import router as ohlcv_page_router
from src.application.interface.page.order_page_router import router as order_page_router
from src.application.interface.page.public_strategy_page_router import (
    router as public_strategy_page_router,
)
from src.application.interface.page.sell_strategy_page_router import (
    router as sell_strategy_page_router,
)
from src.application.interface.page.strategy_edit_page_router import (
    router as strategy_edit_page_router,
)
from src.application.interface.page.strategy_manage_page_router import (
    router as strategy_manage_page_router,
)
from src.application.interface.page.strategy_operate_page_router import (
    router as strategy_operate_page_router,
)
from src.application.interface.page.strategy_page_router import router as strategy_page_router
from src.application.interface.page.strategy_signals_page_router import (
    router as strategy_signals_page_router,
)
from src.application.interface.page.strategy_symbol_states_page_router import (
    router as strategy_symbol_states_page_router,
)
from src.application.interface.page.websocket_page_router import (
    router as websocket_page_router,
)

# /mypage/* 관리자 페이지 라우터 (nav bar 포함)
mypage_routers = [
    main_page_router,
    auth_page_router,
    account_page_router,
    market_data_page_router,
    order_page_router,
    strategy_page_router,
    strategy_manage_page_router,
    strategy_operate_page_router,
    strategy_edit_page_router,
    strategy_symbol_states_page_router,
    strategy_signals_page_router,
    sell_strategy_page_router,
    backtest_page_router,
    websocket_page_router,
    ohlcv_page_router,
    access_logs_page_router,
]

# /page/ 공개용 페이지 라우터 (nav bar 없음)
public_page_routers = [
    public_strategy_page_router,
]

# 전체 페이지 라우터 리스트 (하위 호환성)
page_routers = mypage_routers + public_page_routers

__all__ = [
    "main_page_router",
    "auth_page_router",
    "account_page_router",
    "market_data_page_router",
    "order_page_router",
    "strategy_page_router",
    "strategy_manage_page_router",
    "strategy_operate_page_router",
    "strategy_edit_page_router",
    "strategy_symbol_states_page_router",
    "strategy_signals_page_router",
    "sell_strategy_page_router",
    "backtest_page_router",
    "websocket_page_router",
    "ohlcv_page_router",
    "access_logs_page_router",
    "public_strategy_page_router",
    "mypage_routers",
    "public_page_routers",
    "page_routers",
]
