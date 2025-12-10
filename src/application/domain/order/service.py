# -*- coding: utf-8 -*-
"""
Order Service - 주문 처리 서비스
"""

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.order import OrderModel, OrderStatus, OrderType, PriceType
from src.adapters.database.repositories.order_repository import OrderRepository
from src.adapters.external.kis_api.client import KISAPIClient
from src.adapters.external.kis_api.exceptions import KISAPIError, KISRateLimitError
from src.application.common.decorators import transaction
from src.application.common.exceptions import OrderError
from src.application.domain.order.dto import (
    OrderCancelRequestDTO,
    OrderCreateRequestDTO,
    OrderCreateResponseDTO,
    OrderListResponseDTO,
    OrderStatusResponseDTO,
)
from src.settings.config import settings


class OrderService:
    """
    주문 서비스

    주문 생성, 취소, 조회 및 관리
    """

    def __init__(
        self, kis_client: KISAPIClient, session: AsyncSession | None = None
    ) -> None:
        self.kis_client = kis_client
        self.session = session
        if session:
            self.order_repo = OrderRepository(session)
        self._order_lock = asyncio.Lock()
        self._last_order_at: float | None = None
        self._last_order_at_by_symbol: dict[str, float] = {}
        self._amend_counts: dict[str, int] = {}

    # ==================== 주문 생성 ====================

    @transaction
    async def create_order(
        self, session: AsyncSession, request: OrderCreateRequestDTO
    ) -> OrderCreateResponseDTO:
        """
        주문 생성

        Args:
            session: Database Session
            request: 주문 요청

        Returns:
            OrderCreateResponseDTO: 주문 결과
        """
        account_no = request.account_no or settings.current_kis_account_no

        try:
            await self._enforce_order_pacing(request.symbol)

            # KIS API 주문 요청
            path = "/uapi/domestic-stock/v1/trading/order-cash"

            # 주문 구분 코드 매핑
            ord_dvsn_map = {
                ("buy", "market"): "01",    # 시장가 매수
                ("buy", "limit"): "00",     # 지정가 매수
                ("sell", "market"): "01",   # 시장가 매도
                ("sell", "limit"): "00",    # 지정가 매도
            }
            ord_dvsn = ord_dvsn_map.get((request.order_type, request.price_type), "00")

            payload = {
                "CANO": account_no,
                "ACNT_PRDT_CD": settings.kis_product_code,
                "PDNO": request.symbol,
                "ORD_DVSN": ord_dvsn,
                "ORD_QTY": str(request.quantity),
                "ORD_UNPR": str(int(request.price)),
            }

            # TR ID 매핑 (실전/모의, 매수/매도)
            tr_id_map = {
                (False, "buy"): "TTTC0802U",   # 실전 매수
                (False, "sell"): "TTTC0801U",  # 실전 매도
                (True, "buy"): "VTTC0802U",    # 모의 매수
                (True, "sell"): "VTTC0801U",   # 모의 매도
            }
            tr_id = tr_id_map.get((settings.is_paper_trading, request.order_type))

            headers = {"tr_id": tr_id}

            response = await self._post_with_retry(path, payload, headers)
            output = response.get("output", {})

            # 주문 저장
            order_repo = OrderRepository(session)
            order = await order_repo.create(
                order_id=output.get("KRX_FWDG_ORD_ORGNO", "") + output.get("ODNO", ""),
                account_no=account_no,
                symbol=request.symbol,
                order_type=request.order_type,
                price_type=request.price_type,
                order_price=request.price,
                order_quantity=request.quantity,
                status=OrderStatus.SUBMITTED.value,
                order_time=datetime.now(),
            )

            return OrderCreateResponseDTO(
                order_id=order.order_id,
                order_no=output.get("ODNO", ""),
                symbol=request.symbol,
                order_type=request.order_type,
                price=request.price,
                quantity=request.quantity,
                status=order.status,
                message=response.get("msg1", "Success"),
                order_time=order.order_time,
            )

        except Exception as e:
            raise OrderError(f"Failed to create order: {e}")

    # ==================== 주문 취소 ====================

    @transaction
    async def cancel_order(
        self, session: AsyncSession, request: OrderCancelRequestDTO
    ) -> OrderStatusResponseDTO:
        """
        주문 취소

        Args:
            session: Database Session
            request: 주문 취소 요청

        Returns:
            OrderStatusResponseDTO: 취소 후 주문 상태
        """
        order_repo = OrderRepository(session)
        order = await order_repo.get_by_order_id(request.order_id)

        if not order:
            raise OrderError(f"Order not found: {request.order_id}")

        if order.status in [OrderStatus.FILLED.value, OrderStatus.CANCELED.value]:
            raise OrderError(f"Cannot cancel order with status: {order.status}")

        try:
            self._enforce_amend_limit(order.order_id)
            await self._enforce_order_pacing(order.symbol)

            # KIS API 주문 취소 요청
            path = "/uapi/domestic-stock/v1/trading/order-cancel"

            # 원주문번호 추출 (order_id 형식: "{ORG_NO}{ODNO}")
            org_no = order.order_id[:5] if len(order.order_id) >= 10 else ""
            odno = request.order_no or order.order_id[5:] if len(order.order_id) >= 10 else ""

            # 주문 구분 코드 매핑
            ord_dvsn_map = {
                ("buy", "market"): "01",
                ("buy", "limit"): "00",
                ("sell", "market"): "01",
                ("sell", "limit"): "00",
            }
            ord_dvsn = ord_dvsn_map.get((order.order_type, order.price_type), "00")

            payload = {
                "CANO": order.account_no,
                "ACNT_PRDT_CD": settings.kis_product_code,
                "KRX_FWDG_ORD_ORGNO": org_no,
                "ORGN_ODNO": odno,
                "ORD_DVSN": ord_dvsn,
                "RVSE_CNCL_DVSN_CD": "02",  # 02: 취소
                "ORD_QTY": str(request.quantity or order.remaining_quantity),
                "ORD_UNPR": "0",  # 취소 시 가격은 0
            }

            # TR ID 매핑
            tr_id = "VTTC0803U" if settings.is_paper_trading else "TTTC0803U"
            headers = {"tr_id": tr_id}

            response = await self._post_with_retry(path, payload, headers)

            # 주문 상태 업데이트
            await order_repo.update(
                order.id,
                status=OrderStatus.CANCELED.value,
                status_message=response.get("msg1", "Canceled"),
            )

            # 업데이트된 주문 정보 조회
            updated_order = await order_repo.get_by_order_id(request.order_id)
            if not updated_order:
                raise OrderError("Failed to retrieve updated order")

            return OrderStatusResponseDTO(
                order_id=updated_order.order_id,
                order_no=odno,
                symbol=updated_order.symbol,
                status=updated_order.status,
                order_quantity=updated_order.order_quantity,
                filled_quantity=updated_order.filled_quantity,
                remaining_quantity=updated_order.remaining_quantity,
                filled_avg_price=updated_order.filled_avg_price,
                order_time=updated_order.order_time,
                filled_time=updated_order.filled_time,
            )

        except Exception as e:
            raise OrderError(f"Failed to cancel order: {e}")

    # ==================== 주문 정정 ====================

    @transaction
    async def modify_order(
        self,
        session: AsyncSession,
        order_id: str,
        new_price: Decimal | None = None,
        new_quantity: int | None = None,
    ) -> OrderStatusResponseDTO:
        """
        주문 정정 (가격 또는 수량 변경)

        Args:
            session: Database Session
            order_id: 주문 ID
            new_price: 변경할 가격
            new_quantity: 변경할 수량

        Returns:
            OrderStatusResponseDTO: 정정 후 주문 상태
        """
        if not new_price and not new_quantity:
            raise OrderError("At least one of new_price or new_quantity must be provided")

        order_repo = OrderRepository(session)
        order = await order_repo.get_by_order_id(order_id)

        if not order:
            raise OrderError(f"Order not found: {order_id}")

        if order.status not in [OrderStatus.SUBMITTED.value, OrderStatus.PENDING.value]:
            raise OrderError(f"Cannot modify order with status: {order.status}")

        try:
            self._enforce_amend_limit(order.order_id)
            await self._enforce_order_pacing(order.symbol)

            # KIS API 주문 정정 요청
            path = "/uapi/domestic-stock/v1/trading/order-rvsecncl"

            # 원주문번호 추출
            org_no = order.order_id[:5] if len(order.order_id) >= 10 else ""
            odno = order.order_id[5:] if len(order.order_id) >= 10 else ""

            # 주문 구분 코드 매핑
            ord_dvsn_map = {
                ("buy", "market"): "01",
                ("buy", "limit"): "00",
                ("sell", "market"): "01",
                ("sell", "limit"): "00",
            }
            ord_dvsn = ord_dvsn_map.get((order.order_type, order.price_type), "00")

            payload = {
                "CANO": order.account_no,
                "ACNT_PRDT_CD": settings.kis_product_code,
                "KRX_FWDG_ORD_ORGNO": org_no,
                "ORGN_ODNO": odno,
                "ORD_DVSN": ord_dvsn,
                "RVSE_CNCL_DVSN_CD": "01",  # 01: 정정
                "ORD_QTY": str(new_quantity or order.order_quantity),
                "ORD_UNPR": str(int(new_price or order.order_price)),
            }

            # TR ID 매핑
            tr_id = "VTTC0803U" if settings.is_paper_trading else "TTTC0803U"
            headers = {"tr_id": tr_id}

            response = await self._post_with_retry(path, payload, headers)

            # 주문 정보 업데이트
            update_data = {"status_message": response.get("msg1", "Modified")}
            if new_price:
                update_data["order_price"] = new_price
            if new_quantity:
                update_data["order_quantity"] = new_quantity

            await order_repo.update(order.id, **update_data)

            # 업데이트된 주문 정보 조회
            updated_order = await order_repo.get_by_order_id(order_id)
            if not updated_order:
                raise OrderError("Failed to retrieve updated order")

            return OrderStatusResponseDTO(
                order_id=updated_order.order_id,
                order_no=odno,
                symbol=updated_order.symbol,
                status=updated_order.status,
                order_quantity=updated_order.order_quantity,
                filled_quantity=updated_order.filled_quantity,
                remaining_quantity=updated_order.remaining_quantity,
                filled_avg_price=updated_order.filled_avg_price,
                order_time=updated_order.order_time,
                filled_time=updated_order.filled_time,
            )

        except Exception as e:
            raise OrderError(f"Failed to modify order: {e}")

    # ==================== 체결 확인 및 상태 업데이트 ====================

    @transaction
    async def update_order_status(
        self, session: AsyncSession, order_id: str
    ) -> OrderStatusResponseDTO:
        """
        KIS API로부터 주문 체결 상태 조회 및 DB 업데이트

        Args:
            session: Database Session
            order_id: 주문 ID

        Returns:
            OrderStatusResponseDTO: 업데이트된 주문 상태
        """
        order_repo = OrderRepository(session)
        order = await order_repo.get_by_order_id(order_id)

        if not order:
            raise OrderError(f"Order not found: {order_id}")

        try:
            # KIS API 당일 체결 조회
            path = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"

            payload = {
                "CANO": order.account_no,
                "ACNT_PRDT_CD": settings.kis_product_code,
                "INQR_STRT_DT": order.order_time.strftime("%Y%m%d"),
                "INQR_END_DT": datetime.now().strftime("%Y%m%d"),
                "SLL_BUY_DVSN_CD": "00",  # 00: 전체
                "INQR_DVSN": "00",  # 00: 역순
                "PDNO": order.symbol,
                "CCLD_DVSN": "00",  # 00: 전체
                "ORD_GNO_BRNO": "",
                "ODNO": order.order_id[5:] if len(order.order_id) >= 10 else order.order_id,
                "INQR_DVSN_3": "00",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            }

            # TR ID 매핑
            tr_id = "VTTC8001R" if settings.is_paper_trading else "TTTC8001R"
            headers = {"tr_id": tr_id}

            response = await self.kis_client.post(path, json=payload, headers=headers)
            output = response.get("output1", [])

            # 해당 주문 찾기
            order_data = None
            for item in output:
                if item.get("odno") == order.order_id[5:]:
                    order_data = item
                    break

            if not order_data:
                # 체결 정보가 없으면 현재 상태 유지
                return OrderStatusResponseDTO(
                    order_id=order.order_id,
                    order_no=order.order_id[5:] if len(order.order_id) >= 10 else "",
                    symbol=order.symbol,
                    status=order.status,
                    order_quantity=order.order_quantity,
                    filled_quantity=order.filled_quantity,
                    remaining_quantity=order.remaining_quantity,
                    filled_avg_price=order.filled_avg_price,
                    order_time=order.order_time,
                    filled_time=order.filled_time,
                )

            # 체결 정보 파싱
            filled_qty = int(order_data.get("tot_ccld_qty", 0))
            filled_avg_price = Decimal(order_data.get("avg_prvs", 0))
            order_qty = int(order_data.get("ord_qty", order.order_quantity))

            # 상태 결정
            if filled_qty == 0:
                new_status = OrderStatus.SUBMITTED.value
            elif filled_qty < order_qty:
                new_status = OrderStatus.PARTIALLY_FILLED.value
            else:
                new_status = OrderStatus.FILLED.value

            # DB 업데이트
            update_data = {
                "filled_quantity": filled_qty,
                "filled_avg_price": filled_avg_price,
                "status": new_status,
            }
            if new_status == OrderStatus.FILLED.value and not order.filled_time:
                update_data["filled_time"] = datetime.now()

            await order_repo.update(order.id, **update_data)

            # 업데이트된 주문 정보 조회
            updated_order = await order_repo.get_by_order_id(order_id)
            if not updated_order:
                raise OrderError("Failed to retrieve updated order")

            return OrderStatusResponseDTO(
                order_id=updated_order.order_id,
                order_no=order.order_id[5:] if len(order.order_id) >= 10 else "",
                symbol=updated_order.symbol,
                status=updated_order.status,
                order_quantity=updated_order.order_quantity,
                filled_quantity=updated_order.filled_quantity,
                remaining_quantity=updated_order.remaining_quantity,
                filled_avg_price=updated_order.filled_avg_price,
                order_time=updated_order.order_time,
                filled_time=updated_order.filled_time,
            )

        except Exception as e:
            raise OrderError(f"Failed to update order status: {e}")

    # ==================== 주문 조회 ====================

    async def get_order_status(self, order_id: str) -> OrderStatusResponseDTO:
        """
        주문 상태 조회

        Args:
            order_id: 주문 ID

        Returns:
            OrderStatusResponseDTO: 주문 상태
        """
        if not self.session:
            raise OrderError("Database session not provided")

        order_repo = OrderRepository(self.session)
        order = await order_repo.get_by_order_id(order_id)

        if not order:
            raise OrderError(f"Order not found: {order_id}")

        return OrderStatusResponseDTO(
            order_id=order.order_id,
            order_no=order.order_id.split("-")[-1] if "-" in order.order_id else "",
            symbol=order.symbol,
            status=order.status,
            order_quantity=order.order_quantity,
            filled_quantity=order.filled_quantity,
            remaining_quantity=order.remaining_quantity,
            filled_avg_price=order.filled_avg_price,
            order_time=order.order_time,
            filled_time=order.filled_time,
        )

    # ==================== 내부 유틸리티 ====================

    async def _enforce_order_pacing(self, symbol: str) -> None:
        """주문 요청 간 최소 간격을 보장한다."""
        loop = asyncio.get_event_loop()
        min_gap = settings.order_min_interval_ms / 1000.0
        same_symbol_gap = settings.order_same_symbol_interval_ms / 1000.0

        while True:
            async with self._order_lock:
                now = loop.time()
                wait_global = (
                    (self._last_order_at + min_gap - now)
                    if self._last_order_at is not None
                    else 0
                )
                last_symbol_at = self._last_order_at_by_symbol.get(symbol)
                wait_symbol = (
                    (last_symbol_at + same_symbol_gap - now)
                    if last_symbol_at is not None
                    else 0
                )

                wait_for = max(wait_global, wait_symbol, 0)
                if wait_for <= 0:
                    self._last_order_at = now
                    self._last_order_at_by_symbol[symbol] = now
                    return

            await asyncio.sleep(wait_for)

    def _enforce_amend_limit(self, order_id: str) -> None:
        """정정/취소 시도 횟수를 제한한다."""
        count = self._amend_counts.get(order_id, 0) + 1
        if count > settings.order_max_amendments_per_order:
            raise OrderError("Amendment/cancel limit exceeded for this order")
        self._amend_counts[order_id] = count

    async def _post_with_retry(
        self, path: str, payload: dict[str, str], headers: dict[str, str]
    ) -> dict[str, Any]:
        """
        주문/정정/취소 요청용 POST 래퍼 (타임아웃 단축 + 1회 재시도)
        """
        try:
            return await self.kis_client.post(
                path,
                json=payload,
                headers=headers,
                timeout=settings.order_response_timeout,
            )
        except Exception as e:
            if not self._is_retryable_order_error(e):
                raise
            await asyncio.sleep(settings.order_retry_delay_seconds)
            return await self.kis_client.post(
                path,
                json=payload,
                headers=headers,
                timeout=settings.order_response_timeout,
            )

    def _is_retryable_order_error(self, error: Exception) -> bool:
        """주문 재시도 대상 오류인지 판정한다."""
        if isinstance(error, (asyncio.TimeoutError, httpx.TimeoutException, KISRateLimitError)):
            return True
        if isinstance(error, KISAPIError) and error.error_code:
            if error.error_code.isdigit() and int(error.error_code) >= 500:
                return True
            if error.error_code == "429":
                return True
        return False

    async def get_order_list(
        self, account_no: str | None = None, status: str | None = None
    ) -> OrderListResponseDTO:
        """
        주문 목록 조회

        Args:
            account_no: 계좌번호
            status: 주문 상태 필터

        Returns:
            OrderListResponseDTO: 주문 목록
        """
        if not self.session:
            raise OrderError("Database session not provided")

        account_no = account_no or settings.current_kis_account_no
        order_repo = OrderRepository(self.session)

        if status:
            orders = await order_repo.get_by_status(OrderStatus(status))
        else:
            orders = await order_repo.get_by_account(account_no)

        order_list = [
            OrderStatusResponseDTO(
                order_id=o.order_id,
                order_no=o.order_id.split("-")[-1] if "-" in o.order_id else "",
                symbol=o.symbol,
                status=o.status,
                order_quantity=o.order_quantity,
                filled_quantity=o.filled_quantity,
                remaining_quantity=o.remaining_quantity,
                filled_avg_price=o.filled_avg_price,
                order_time=o.order_time,
                filled_time=o.filled_time,
            )
            for o in orders
        ]

        return OrderListResponseDTO(orders=order_list, total_count=len(order_list))
