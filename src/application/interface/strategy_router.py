# -*- coding: utf-8 -*-
"""
Strategy Router - 전략 관리 API 엔드포인트
"""

from fastapi import APIRouter, status

from src.application.common.dependencies import DatabaseSession
from src.application.common.dto import ResponseDTO
from src.application.domain.strategy.dto import (
    StrategyCreateRequestDTO,
    StrategyDetailResponseDTO,
    StrategyListResponseDTO,
    StrategyUpdateRequestDTO,
)
from src.application.domain.strategy.service import StrategyService

router = APIRouter()


@router.post(
    "",
    response_model=ResponseDTO[StrategyDetailResponseDTO],
    status_code=status.HTTP_201_CREATED,
    summary="전략 생성",
    description="새로운 자동매매 전략 생성",
)
async def create_strategy(
    request: StrategyCreateRequestDTO,
    session: DatabaseSession,
) -> ResponseDTO[StrategyDetailResponseDTO]:
    """전략 생성"""
    service = StrategyService(session)
    strategy_data = await service.create_strategy(session, request)
    return ResponseDTO.success_response(strategy_data, "Strategy created successfully")


@router.get(
    "/{strategy_id}",
    response_model=ResponseDTO[StrategyDetailResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="전략 상세 조회",
    description="전략 ID로 상세 정보 조회",
)
async def get_strategy(
    strategy_id: int,
    session: DatabaseSession,
) -> ResponseDTO[StrategyDetailResponseDTO]:
    """전략 상세 조회"""
    service = StrategyService(session)
    strategy_data = await service.get_strategy(strategy_id)
    return ResponseDTO.success_response(strategy_data, "Strategy retrieved successfully")


@router.get(
    "",
    response_model=ResponseDTO[StrategyListResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="전략 목록 조회",
    description="계좌별 전략 목록 조회",
)
async def get_strategy_list(
    account_no: str | None = None,
    status_filter: str | None = None,
    session: DatabaseSession = None,
) -> ResponseDTO[StrategyListResponseDTO]:
    """전략 목록 조회"""
    service = StrategyService(session)
    strategy_list = await service.get_strategy_list(account_no, status_filter)
    return ResponseDTO.success_response(strategy_list, "Strategy list retrieved successfully")


@router.patch(
    "/{strategy_id}",
    response_model=ResponseDTO[StrategyDetailResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="전략 수정",
    description="전략 정보 수정",
)
async def update_strategy(
    strategy_id: int,
    request: StrategyUpdateRequestDTO,
    session: DatabaseSession,
) -> ResponseDTO[StrategyDetailResponseDTO]:
    """전략 수정"""
    service = StrategyService(session)
    strategy_data = await service.update_strategy(session, strategy_id, request)
    return ResponseDTO.success_response(strategy_data, "Strategy updated successfully")


@router.delete(
    "/{strategy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="전략 삭제",
    description="전략 삭제 (Soft Delete)",
)
async def delete_strategy(
    strategy_id: int,
    session: DatabaseSession,
) -> None:
    """전략 삭제"""
    service = StrategyService(session)
    await service.delete_strategy(session, strategy_id)


# ==================== 전략 상태 관리 ====================


@router.post(
    "/{strategy_id}/start",
    response_model=ResponseDTO[StrategyDetailResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="전략 시작",
    description="전략 활성화 (자동매매 시작)",
)
async def start_strategy(
    strategy_id: int,
    session: DatabaseSession,
) -> ResponseDTO[StrategyDetailResponseDTO]:
    """전략 시작"""
    service = StrategyService(session)
    strategy_data = await service.start_strategy(session, strategy_id)
    return ResponseDTO.success_response(strategy_data, "Strategy started successfully")


@router.post(
    "/{strategy_id}/pause",
    response_model=ResponseDTO[StrategyDetailResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="전략 일시정지",
    description="전략 일시정지 (자동매매 일시 중단)",
)
async def pause_strategy(
    strategy_id: int,
    session: DatabaseSession,
) -> ResponseDTO[StrategyDetailResponseDTO]:
    """전략 일시정지"""
    service = StrategyService(session)
    strategy_data = await service.pause_strategy(session, strategy_id)
    return ResponseDTO.success_response(strategy_data, "Strategy paused successfully")


@router.post(
    "/{strategy_id}/stop",
    response_model=ResponseDTO[StrategyDetailResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="전략 중지",
    description="전략 완전 중지 (자동매매 종료)",
)
async def stop_strategy(
    strategy_id: int,
    session: DatabaseSession,
) -> ResponseDTO[StrategyDetailResponseDTO]:
    """전략 중지"""
    service = StrategyService(session)
    strategy_data = await service.stop_strategy(session, strategy_id)
    return ResponseDTO.success_response(strategy_data, "Strategy stopped successfully")
