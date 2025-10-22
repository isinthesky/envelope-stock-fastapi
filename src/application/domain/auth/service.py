# -*- coding: utf-8 -*-
"""
Auth Service - 인증 및 토큰 관리 서비스
"""

from datetime import datetime

from src.adapters.external.kis_api.auth import KISAuth
from src.application.common.exceptions import AuthenticationError, InvalidTokenError
from src.application.domain.auth.dto import (
    TokenResponseDTO,
    TokenStatusDTO,
    WebSocketAuthResponseDTO,
)
from src.settings.config import settings


class AuthService:
    """
    인증 서비스

    KIS API 인증 및 토큰 관리
    """

    def __init__(self, kis_auth: KISAuth) -> None:
        """
        Args:
            kis_auth: KIS 인증 관리 인스턴스
        """
        self.kis_auth = kis_auth

    # ==================== 토큰 관리 ====================

    async def get_access_token(self, force_refresh: bool = False) -> TokenResponseDTO:
        """
        액세스 토큰 발급/조회

        Args:
            force_refresh: 강제 갱신 여부

        Returns:
            TokenResponseDTO: 토큰 정보

        Raises:
            AuthenticationError: 토큰 발급 실패
        """
        try:
            token = await self.kis_auth.get_access_token(force_refresh=force_refresh)
            token_info = self.kis_auth.token_info

            if token_info is None:
                raise AuthenticationError("Failed to get token info")

            return TokenResponseDTO(
                access_token=token,
                token_type="Bearer",
                expires_at=token_info.expires_at,
                environment=settings.trading_environment,
            )
        except Exception as e:
            raise AuthenticationError(f"Failed to get access token: {e}")

    async def refresh_token(self) -> TokenResponseDTO:
        """
        토큰 갱신

        Returns:
            TokenResponseDTO: 갱신된 토큰 정보

        Raises:
            AuthenticationError: 토큰 갱신 실패
        """
        try:
            token_info = await self.kis_auth.refresh_token()

            return TokenResponseDTO(
                access_token=token_info.access_token,
                token_type="Bearer",
                expires_at=token_info.expires_at,
                environment=settings.trading_environment,
            )
        except Exception as e:
            raise AuthenticationError(f"Failed to refresh token: {e}")

    async def get_token_status(self) -> TokenStatusDTO:
        """
        토큰 상태 조회

        Returns:
            TokenStatusDTO: 토큰 상태

        Raises:
            InvalidTokenError: 토큰이 없는 경우
        """
        token_info = self.kis_auth.token_info

        if token_info is None:
            raise InvalidTokenError()

        remaining_seconds = int((token_info.expires_at - datetime.now()).total_seconds())

        return TokenStatusDTO(
            is_valid=token_info.is_valid,
            expires_at=token_info.expires_at,
            remaining_seconds=max(0, remaining_seconds),
            environment=settings.trading_environment,
        )

    # ==================== WebSocket 인증 ====================

    async def get_websocket_approval_key(self) -> WebSocketAuthResponseDTO:
        """
        WebSocket 승인 키 발급

        Returns:
            WebSocketAuthResponseDTO: WebSocket 인증 정보

        Raises:
            AuthenticationError: 승인 키 발급 실패
        """
        try:
            approval_key = await self.kis_auth.get_approval_key()

            return WebSocketAuthResponseDTO(
                approval_key=approval_key, environment=settings.trading_environment
            )
        except Exception as e:
            raise AuthenticationError(f"Failed to get WebSocket approval key: {e}")

    # ==================== 환경 관리 ====================

    def get_current_environment(self) -> str:
        """
        현재 거래 환경 조회

        Returns:
            str: 거래 환경 (prod/vps)
        """
        return settings.trading_environment

    def is_paper_trading(self) -> bool:
        """
        모의투자 여부 확인

        Returns:
            bool: 모의투자 여부
        """
        return settings.is_paper_trading

    # ==================== 헬스체크 ====================

    async def health_check(self) -> dict[str, str]:
        """
        인증 서비스 헬스체크

        Returns:
            dict[str, str]: 상태 정보
        """
        try:
            token_info = self.kis_auth.token_info
            is_valid = token_info.is_valid if token_info else False

            return {
                "status": "healthy" if is_valid else "unhealthy",
                "token_valid": str(is_valid),
                "environment": settings.trading_environment,
            }
        except Exception:
            return {
                "status": "unhealthy",
                "token_valid": "false",
                "environment": settings.trading_environment,
            }
