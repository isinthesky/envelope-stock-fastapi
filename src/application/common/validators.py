# -*- coding: utf-8 -*-
"""
Validators - 공통 검증 함수

입력 데이터 검증을 위한 재사용 가능한 함수
"""

import re
from datetime import datetime
from decimal import Decimal
from typing import Any


# ==================== 숫자 검증 ====================


def validate_positive(value: int | float | Decimal, field_name: str = "value") -> None:
    """
    양수 검증

    Args:
        value: 검증할 값
        field_name: 필드명

    Raises:
        ValueError: 양수가 아닌 경우
    """
    if value <= 0:
        raise ValueError(f"{field_name} must be positive, got {value}")


def validate_non_negative(
    value: int | float | Decimal, field_name: str = "value"
) -> None:
    """
    0 이상 검증

    Args:
        value: 검증할 값
        field_name: 필드명

    Raises:
        ValueError: 0 미만인 경우
    """
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative, got {value}")


def validate_range(
    value: int | float | Decimal,
    min_value: int | float | Decimal,
    max_value: int | float | Decimal,
    field_name: str = "value",
) -> None:
    """
    범위 검증

    Args:
        value: 검증할 값
        min_value: 최소값
        max_value: 최대값
        field_name: 필드명

    Raises:
        ValueError: 범위를 벗어난 경우
    """
    if not min_value <= value <= max_value:
        raise ValueError(
            f"{field_name} must be between {min_value} and {max_value}, got {value}"
        )


# ==================== 문자열 검증 ====================


def validate_not_empty(value: str, field_name: str = "value") -> None:
    """
    비어있지 않음 검증

    Args:
        value: 검증할 문자열
        field_name: 필드명

    Raises:
        ValueError: 빈 문자열인 경우
    """
    if not value or not value.strip():
        raise ValueError(f"{field_name} cannot be empty")


def validate_length(
    value: str, min_length: int = 0, max_length: int = 1000, field_name: str = "value"
) -> None:
    """
    문자열 길이 검증

    Args:
        value: 검증할 문자열
        min_length: 최소 길이
        max_length: 최대 길이
        field_name: 필드명

    Raises:
        ValueError: 길이가 범위를 벗어난 경우
    """
    length = len(value)
    if not min_length <= length <= max_length:
        raise ValueError(
            f"{field_name} length must be between {min_length} and {max_length}, "
            f"got {length}"
        )


def validate_pattern(value: str, pattern: str, field_name: str = "value") -> None:
    """
    정규식 패턴 검증

    Args:
        value: 검증할 문자열
        pattern: 정규식 패턴
        field_name: 필드명

    Raises:
        ValueError: 패턴에 맞지 않는 경우
    """
    if not re.match(pattern, value):
        raise ValueError(f"{field_name} does not match required pattern")


# ==================== 금융 데이터 검증 ====================


def validate_symbol(symbol: str) -> None:
    """
    종목코드 검증

    Args:
        symbol: 종목코드

    Raises:
        ValueError: 잘못된 종목코드
    """
    validate_not_empty(symbol, "symbol")
    validate_length(symbol, min_length=6, max_length=20, field_name="symbol")
    # 종목코드는 영숫자만 허용
    if not symbol.isalnum():
        raise ValueError("Symbol must contain only alphanumeric characters")


def validate_account_no(account_no: str) -> None:
    """
    계좌번호 검증

    Args:
        account_no: 계좌번호

    Raises:
        ValueError: 잘못된 계좌번호
    """
    validate_not_empty(account_no, "account_no")
    validate_length(account_no, min_length=8, max_length=20, field_name="account_no")


def validate_price(price: Decimal | float, field_name: str = "price") -> None:
    """
    가격 검증

    Args:
        price: 가격
        field_name: 필드명

    Raises:
        ValueError: 잘못된 가격
    """
    validate_positive(price, field_name)


def validate_quantity(quantity: int, field_name: str = "quantity") -> None:
    """
    수량 검증

    Args:
        quantity: 수량
        field_name: 필드명

    Raises:
        ValueError: 잘못된 수량
    """
    if not isinstance(quantity, int):
        raise ValueError(f"{field_name} must be an integer")
    validate_positive(quantity, field_name)


def validate_order_type(order_type: str) -> None:
    """
    주문 유형 검증

    Args:
        order_type: 주문 유형 (buy/sell)

    Raises:
        ValueError: 잘못된 주문 유형
    """
    valid_types = ["buy", "sell"]
    if order_type not in valid_types:
        raise ValueError(f"order_type must be one of {valid_types}, got {order_type}")


def validate_price_type(price_type: str) -> None:
    """
    가격 유형 검증

    Args:
        price_type: 가격 유형 (market/limit/stop)

    Raises:
        ValueError: 잘못된 가격 유형
    """
    valid_types = ["market", "limit", "stop"]
    if price_type not in valid_types:
        raise ValueError(f"price_type must be one of {valid_types}, got {price_type}")


# ==================== 날짜/시간 검증 ====================


def validate_date_range(
    start_date: datetime, end_date: datetime, field_name: str = "date"
) -> None:
    """
    날짜 범위 검증

    Args:
        start_date: 시작일
        end_date: 종료일
        field_name: 필드명

    Raises:
        ValueError: 시작일이 종료일보다 늦은 경우
    """
    if start_date > end_date:
        raise ValueError(f"{field_name}: start_date must be before end_date")


def validate_future_date(date: datetime, field_name: str = "date") -> None:
    """
    미래 날짜 검증

    Args:
        date: 날짜
        field_name: 필드명

    Raises:
        ValueError: 과거 날짜인 경우
    """
    if date < datetime.now():
        raise ValueError(f"{field_name} must be a future date")


def validate_past_date(date: datetime, field_name: str = "date") -> None:
    """
    과거 날짜 검증

    Args:
        date: 날짜
        field_name: 필드명

    Raises:
        ValueError: 미래 날짜인 경우
    """
    if date > datetime.now():
        raise ValueError(f"{field_name} must be a past date")


# ==================== 리스트 검증 ====================


def validate_list_not_empty(value: list[Any], field_name: str = "list") -> None:
    """
    리스트 비어있지 않음 검증

    Args:
        value: 검증할 리스트
        field_name: 필드명

    Raises:
        ValueError: 빈 리스트인 경우
    """
    if not value:
        raise ValueError(f"{field_name} cannot be empty")


def validate_list_length(
    value: list[Any], min_length: int = 0, max_length: int = 100, field_name: str = "list"
) -> None:
    """
    리스트 길이 검증

    Args:
        value: 검증할 리스트
        min_length: 최소 길이
        max_length: 최대 길이
        field_name: 필드명

    Raises:
        ValueError: 길이가 범위를 벗어난 경우
    """
    length = len(value)
    if not min_length <= length <= max_length:
        raise ValueError(
            f"{field_name} length must be between {min_length} and {max_length}, "
            f"got {length}"
        )


# ==================== 조합 검증 ====================


def validate_order_data(
    symbol: str,
    order_type: str,
    price_type: str,
    price: Decimal,
    quantity: int,
) -> None:
    """
    주문 데이터 통합 검증

    Args:
        symbol: 종목코드
        order_type: 주문 유형
        price_type: 가격 유형
        price: 가격
        quantity: 수량

    Raises:
        ValueError: 검증 실패
    """
    validate_symbol(symbol)
    validate_order_type(order_type)
    validate_price_type(price_type)
    validate_price(price)
    validate_quantity(quantity)
