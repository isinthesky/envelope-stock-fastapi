# -*- coding: utf-8 -*-
"""
KIS API Exceptions - KIS API 예외 클래스
"""

from typing import Any


class KISAPIError(Exception):
    """KIS API 기본 예외"""

    def __init__(
        self, message: str, error_code: str | None = None, response_data: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.response_data = response_data or {}

    def __str__(self) -> str:
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message


class KISAuthError(KISAPIError):
    """인증 실패 예외"""

    pass


class KISRateLimitError(KISAPIError):
    """Rate Limit 초과 예외"""

    pass


class KISOrderError(KISAPIError):
    """주문 실패 예외"""

    pass


class KISMarketDataError(KISAPIError):
    """시세 조회 실패 예외"""

    pass


class KISWebSocketError(Exception):
    """WebSocket 관련 예외"""

    pass
