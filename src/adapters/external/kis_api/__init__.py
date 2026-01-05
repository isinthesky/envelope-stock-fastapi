"""
KIS API Adapter - 한국투자증권 Open API 클라이언트
"""

from src.adapters.external.kis_api.auth import KISAuth, TokenInfo, get_kis_auth
from src.adapters.external.kis_api.client import KISAPIClient, get_kis_client
from src.adapters.external.kis_api.exceptions import (
    KISAPIError,
    KISAuthError,
    KISMarketDataError,
    KISOrderError,
    KISRateLimitError,
    KISWebSocketError,
)

__all__ = [
    # Auth
    "KISAuth",
    "TokenInfo",
    "get_kis_auth",
    # Client
    "KISAPIClient",
    "get_kis_client",
    # Exceptions
    "KISAPIError",
    "KISAuthError",
    "KISRateLimitError",
    "KISOrderError",
    "KISMarketDataError",
    "KISWebSocketError",
]
