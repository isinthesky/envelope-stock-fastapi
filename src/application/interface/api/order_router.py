# -*- coding: utf-8 -*-
"""
Order Router - 주문 관리 API 엔드포인트
"""

from fastapi import APIRouter, Query, status

from src.application.common.dependencies import DatabaseSession, KISClientDep
from src.application.common.dto import ResponseDTO
from src.application.domain.order.dto import (
    OrderCancelRequestDTO,
    OrderCreateRequestDTO,
    OrderCreateResponseDTO,
    OrderListResponseDTO,
    OrderStatusResponseDTO,
)
from src.application.domain.order.service import OrderService

router = APIRouter()


@router.post(
    "",
    response_model=ResponseDTO[OrderCreateResponseDTO],
    status_code=status.HTTP_201_CREATED,
    summary="주문 생성",
    description="매수/매도 주문 생성",
)
async def create_order(
    request: OrderCreateRequestDTO,
    session: DatabaseSession,
    kis_client: KISClientDep,
) -> ResponseDTO[OrderCreateResponseDTO]:
    """주문 생성"""
    service = OrderService(kis_client, session)
    order_data = await service.create_order(session, request)
    return ResponseDTO.success_response(order_data, "Order created successfully")


@router.get(
    "/{order_id}",
    response_model=ResponseDTO[OrderStatusResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="주문 상태 조회",
    description="주문 ID로 주문 상태 조회",
)
async def get_order_status(
    order_id: str,
    session: DatabaseSession,
    kis_client: KISClientDep,
) -> ResponseDTO[OrderStatusResponseDTO]:
    """주문 상태 조회"""
    service = OrderService(kis_client, session)
    order_status = await service.get_order_status(order_id)
    return ResponseDTO.success_response(order_status, "Order status retrieved successfully")


@router.get(
    "",
    response_model=ResponseDTO[OrderListResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="주문 목록 조회",
    description="계좌별 주문 목록 조회",
)
async def get_order_list(
    account_no: str | None = Query(default=None, description="계좌번호"),
    status_filter: str | None = Query(default=None, description="주문 상태 필터"),
    session: DatabaseSession = None,
    kis_client: KISClientDep = None,
) -> ResponseDTO[OrderListResponseDTO]:
    """주문 목록 조회"""
    service = OrderService(kis_client, session)
    order_list = await service.get_order_list(account_no, status_filter)
    return ResponseDTO.success_response(order_list, "Order list retrieved successfully")


@router.post(
    "/{order_id}/cancel",
    response_model=ResponseDTO[OrderStatusResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="주문 취소",
    description="주문 ID로 주문 취소",
)
async def cancel_order(
    order_id: str,
    request: OrderCancelRequestDTO,
    session: DatabaseSession,
    kis_client: KISClientDep,
) -> ResponseDTO[OrderStatusResponseDTO]:
    """주문 취소"""
    service = OrderService(kis_client, session)
    # request의 order_id를 경로 파라미터로 설정
    request.order_id = order_id
    order_status = await service.cancel_order(session, request)
    return ResponseDTO.success_response(order_status, "Order canceled successfully")


@router.patch(
    "/{order_id}",
    response_model=ResponseDTO[OrderStatusResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="주문 정정",
    description="주문 가격 또는 수량 정정",
)
async def modify_order(
    order_id: str,
    new_price: float | None = Query(default=None, description="변경할 가격"),
    new_quantity: int | None = Query(default=None, description="변경할 수량"),
    session: DatabaseSession = None,
    kis_client: KISClientDep = None,
) -> ResponseDTO[OrderStatusResponseDTO]:
    """주문 정정"""
    from decimal import Decimal

    service = OrderService(kis_client, session)
    order_status = await service.modify_order(
        session, order_id, Decimal(str(new_price)) if new_price else None, new_quantity
    )
    return ResponseDTO.success_response(order_status, "Order modified successfully")


@router.post(
    "/{order_id}/refresh-status",
    response_model=ResponseDTO[OrderStatusResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="체결 상태 업데이트",
    description="KIS API로부터 주문 체결 상태 조회 및 DB 업데이트",
)
async def refresh_order_status(
    order_id: str,
    session: DatabaseSession,
    kis_client: KISClientDep,
) -> ResponseDTO[OrderStatusResponseDTO]:
    """체결 상태 업데이트"""
    service = OrderService(kis_client, session)
    order_status = await service.update_order_status(session, order_id)
    return ResponseDTO.success_response(order_status, "Order status refreshed successfully")
