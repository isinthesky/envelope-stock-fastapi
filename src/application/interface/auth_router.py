# -*- coding: utf-8 -*-
"""
Auth Router - 인증 API 엔드포인트
"""

from fastapi import APIRouter, status

from src.application.common.dependencies import KISAuthDep
from src.application.common.dto import ResponseDTO
from src.application.domain.auth.dto import (
    TokenRefreshRequestDTO,
    TokenResponseDTO,
    TokenStatusDTO,
    WebSocketAuthResponseDTO,
)
from src.application.domain.auth.service import AuthService

router = APIRouter()


@router.post(
    "/token",
    response_model=ResponseDTO[TokenResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="토큰 발급",
    description="KIS API 액세스 토큰 발급",
)
async def get_token(
    request: TokenRefreshRequestDTO, kis_auth: KISAuthDep
) -> ResponseDTO[TokenResponseDTO]:
    """액세스 토큰 발급"""
    service = AuthService(kis_auth)
    token_data = await service.get_access_token(force_refresh=request.force)
    return ResponseDTO.success_response(token_data, "Token issued successfully")


@router.post(
    "/token/refresh",
    response_model=ResponseDTO[TokenResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="토큰 갱신",
    description="액세스 토큰 갱신",
)
async def refresh_token(kis_auth: KISAuthDep) -> ResponseDTO[TokenResponseDTO]:
    """토큰 갱신"""
    service = AuthService(kis_auth)
    token_data = await service.refresh_token()
    return ResponseDTO.success_response(token_data, "Token refreshed successfully")


@router.get(
    "/token/status",
    response_model=ResponseDTO[TokenStatusDTO],
    status_code=status.HTTP_200_OK,
    summary="토큰 상태 조회",
    description="현재 토큰의 유효성 및 만료 시간 조회",
)
async def get_token_status(kis_auth: KISAuthDep) -> ResponseDTO[TokenStatusDTO]:
    """토큰 상태 조회"""
    service = AuthService(kis_auth)
    status_data = await service.get_token_status()
    return ResponseDTO.success_response(status_data, "Token status retrieved successfully")


@router.post(
    "/websocket/approval",
    response_model=ResponseDTO[WebSocketAuthResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="WebSocket 승인 키 발급",
    description="실시간 시세 WebSocket 연결용 승인 키 발급",
)
async def get_websocket_approval(
    kis_auth: KISAuthDep,
) -> ResponseDTO[WebSocketAuthResponseDTO]:
    """WebSocket 승인 키 발급"""
    service = AuthService(kis_auth)
    approval_data = await service.get_websocket_approval_key()
    return ResponseDTO.success_response(
        approval_data, "WebSocket approval key issued successfully"
    )


@router.get(
    "/environment",
    response_model=ResponseDTO[dict[str, str]],
    status_code=status.HTTP_200_OK,
    summary="거래 환경 조회",
    description="현재 거래 환경 (실전/모의) 조회",
)
async def get_environment(kis_auth: KISAuthDep) -> ResponseDTO[dict[str, str]]:
    """거래 환경 조회"""
    service = AuthService(kis_auth)
    env_data = {
        "environment": service.get_current_environment(),
        "is_paper_trading": str(service.is_paper_trading()),
    }
    return ResponseDTO.success_response(env_data, "Environment info retrieved successfully")
