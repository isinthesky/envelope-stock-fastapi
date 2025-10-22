# -*- coding: utf-8 -*-
"""
Order Domain DTO - 주문 관련 데이터 전송 객체
"""

from datetime import datetime
from decimal import Decimal

from pydantic import Field, field_validator

from src.application.common.dto import BaseDTO


# ==================== Request DTOs ====================


class OrderCreateRequestDTO(BaseDTO):
    """
    주문 생성 요청 DTO

    Attributes:
        symbol: 종목코드
        order_type: 주문 유형 (buy/sell)
        price_type: 가격 유형 (market/limit)
        price: 주문 가격
        quantity: 주문 수량
        account_no: 계좌번호 (없으면 기본)
    """

    symbol: str = Field(description="종목코드", min_length=6, max_length=20)
    order_type: str = Field(description="주문 유형 (buy/sell)", pattern="^(buy|sell)$")
    price_type: str = Field(description="가격 유형 (market/limit)", pattern="^(market|limit)$")
    price: Decimal = Field(description="주문 가격", gt=0)
    quantity: int = Field(description="주문 수량", gt=0)
    account_no: str | None = Field(default=None, description="계좌번호")

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Quantity must be positive")
        return v


class OrderCancelRequestDTO(BaseDTO):
    """
    주문 취소 요청 DTO

    Attributes:
        order_id: 주문 ID
        order_no: 원주문번호
        quantity: 취소 수량 (전량 취소 시 생략)
    """

    order_id: str = Field(description="주문 ID")
    order_no: str | None = Field(default=None, description="원주문번호")
    quantity: int | None = Field(default=None, description="취소 수량", gt=0)


class OrderListRequestDTO(BaseDTO):
    """
    주문 목록 조회 요청 DTO

    Attributes:
        account_no: 계좌번호
        status: 주문 상태 필터
        start_date: 조회 시작일
        end_date: 조회 종료일
    """

    account_no: str | None = Field(default=None, description="계좌번호")
    status: str | None = Field(default=None, description="주문 상태 필터")
    start_date: datetime | None = Field(default=None, description="조회 시작일")
    end_date: datetime | None = Field(default=None, description="조회 종료일")


# ==================== Response DTOs ====================


class OrderCreateResponseDTO(BaseDTO):
    """
    주문 생성 응답 DTO

    Attributes:
        order_id: 주문 ID
        order_no: 주문번호
        symbol: 종목코드
        order_type: 주문 유형
        price: 주문 가격
        quantity: 주문 수량
        status: 주문 상태
        message: 응답 메시지
        order_time: 주문 시각
    """

    order_id: str = Field(description="주문 ID")
    order_no: str = Field(description="주문번호")
    symbol: str = Field(description="종목코드")
    order_type: str = Field(description="주문 유형")
    price: Decimal = Field(description="주문 가격")
    quantity: int = Field(description="주문 수량")
    status: str = Field(description="주문 상태")
    message: str = Field(description="응답 메시지")
    order_time: datetime = Field(description="주문 시각")


class OrderStatusResponseDTO(BaseDTO):
    """
    주문 상태 응답 DTO

    Attributes:
        order_id: 주문 ID
        order_no: 주문번호
        symbol: 종목코드
        status: 주문 상태
        order_quantity: 주문 수량
        filled_quantity: 체결 수량
        remaining_quantity: 미체결 수량
        filled_avg_price: 체결 평균가
        order_time: 주문 시각
        filled_time: 체결 시각
    """

    order_id: str = Field(description="주문 ID")
    order_no: str = Field(description="주문번호")
    symbol: str = Field(description="종목코드")
    status: str = Field(description="주문 상태")
    order_quantity: int = Field(description="주문 수량")
    filled_quantity: int = Field(description="체결 수량")
    remaining_quantity: int = Field(description="미체결 수량")
    filled_avg_price: Decimal = Field(description="체결 평균가")
    order_time: datetime = Field(description="주문 시각")
    filled_time: datetime | None = Field(default=None, description="체결 시각")


class OrderListResponseDTO(BaseDTO):
    """
    주문 목록 응답 DTO

    Attributes:
        orders: 주문 목록
        total_count: 전체 주문 수
    """

    orders: list[OrderStatusResponseDTO] = Field(description="주문 목록")
    total_count: int = Field(description="전체 주문 수")
