# -*- coding: utf-8 -*-
"""
Account Router - 계좌 관리 API 엔드포인트
"""

from fastapi import APIRouter, Query, status

from src.application.common.dependencies import KISClientDep, RedisDep
from src.application.common.dto import ResponseDTO
from src.application.domain.account.dto import (
    AccountBalanceResponseDTO,
    PositionListResponseDTO,
)
from src.application.domain.account.service import AccountService

router = APIRouter()


@router.get(
    "/balance",
    response_model=ResponseDTO[AccountBalanceResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="계좌 잔고 조회",
    description="계좌의 잔고 및 평가 정보 조회 (캐시 30초)",
)
async def get_account_balance(
    account_no: str | None = Query(default=None, description="계좌번호 (없으면 기본 계좌)"),
    use_cache: bool = Query(default=True, description="캐시 사용 여부"),
    kis_client: KISClientDep = None,
    redis: RedisDep = None,
) -> ResponseDTO[AccountBalanceResponseDTO]:
    """계좌 잔고 조회"""
    service = AccountService(kis_client, redis)
    balance_data = await service.get_account_balance(account_no, use_cache=use_cache)
    return ResponseDTO.success_response(balance_data, "Account balance retrieved successfully")


@router.get(
    "/positions",
    response_model=ResponseDTO[PositionListResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="포지션 목록 조회",
    description="보유 종목의 포지션 정보 조회",
)
async def get_position_list(
    account_no: str | None = Query(default=None, description="계좌번호"),
    kis_client: KISClientDep = None,
    redis: RedisDep = None,
) -> ResponseDTO[PositionListResponseDTO]:
    """포지션 목록 조회"""
    service = AccountService(kis_client, redis)
    position_data = await service.get_position_list(account_no)
    return ResponseDTO.success_response(position_data, "Position list retrieved successfully")
