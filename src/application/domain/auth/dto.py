# -*- coding: utf-8 -*-
"""
Auth Domain DTO - 인증 관련 데이터 전송 객체
"""

from datetime import datetime

from pydantic import Field

from src.application.common.dto import BaseDTO


# ==================== Request DTOs ====================


class TokenRequestDTO(BaseDTO):
    """
    토큰 발급 요청 DTO

    Attributes:
        environment: 거래 환경 (prod: 실전, vps: 모의)
    """

    environment: str = Field(
        default="vps", pattern="^(prod|vps)$", description="거래 환경 (prod/vps)"
    )


class TokenRefreshRequestDTO(BaseDTO):
    """
    토큰 갱신 요청 DTO

    Attributes:
        force: 강제 갱신 여부
    """

    force: bool = Field(default=False, description="강제 갱신 여부")


class WebSocketAuthRequestDTO(BaseDTO):
    """
    WebSocket 인증 요청 DTO

    Attributes:
        environment: 거래 환경
    """

    environment: str = Field(
        default="vps", pattern="^(prod|vps)$", description="거래 환경 (prod/vps)"
    )


# ==================== Response DTOs ====================


class TokenResponseDTO(BaseDTO):
    """
    토큰 응답 DTO

    Attributes:
        access_token: 액세스 토큰
        token_type: 토큰 타입 (Bearer)
        expires_at: 만료 시각
        environment: 거래 환경
    """

    access_token: str = Field(description="액세스 토큰")
    token_type: str = Field(default="Bearer", description="토큰 타입")
    expires_at: datetime = Field(description="만료 시각")
    environment: str = Field(description="거래 환경 (prod/vps)")


class WebSocketAuthResponseDTO(BaseDTO):
    """
    WebSocket 인증 응답 DTO

    Attributes:
        approval_key: WebSocket 승인 키
        environment: 거래 환경
    """

    approval_key: str = Field(description="WebSocket 승인 키")
    environment: str = Field(description="거래 환경 (prod/vps)")


class TokenStatusDTO(BaseDTO):
    """
    토큰 상태 DTO

    Attributes:
        is_valid: 유효 여부
        expires_at: 만료 시각
        remaining_seconds: 남은 시간 (초)
        environment: 거래 환경
    """

    is_valid: bool = Field(description="유효 여부")
    expires_at: datetime = Field(description="만료 시각")
    remaining_seconds: int = Field(description="남은 시간 (초)")
    environment: str = Field(description="거래 환경 (prod/vps)")
