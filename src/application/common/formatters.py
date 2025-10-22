# -*- coding: utf-8 -*-
"""
Formatters - 데이터 포맷팅 유틸리티

데이터 변환 및 포맷팅 함수
"""

from datetime import datetime
from decimal import Decimal


# ==================== 숫자 포맷팅 ====================


def format_price(price: Decimal | float, decimal_places: int = 2) -> str:
    """
    가격 포맷팅 (천 단위 구분)

    Args:
        price: 가격
        decimal_places: 소수점 자리수

    Returns:
        str: 포맷된 가격 (예: "1,234,567.89")
    """
    return f"{price:,.{decimal_places}f}"


def format_percentage(value: float | Decimal, decimal_places: int = 2) -> str:
    """
    퍼센트 포맷팅

    Args:
        value: 값
        decimal_places: 소수점 자리수

    Returns:
        str: 포맷된 퍼센트 (예: "12.34%")
    """
    return f"{value:.{decimal_places}f}%"


def format_change_rate(current: Decimal | float, previous: Decimal | float) -> str:
    """
    변화율 계산 및 포맷팅

    Args:
        current: 현재 값
        previous: 이전 값

    Returns:
        str: 변화율 (예: "+12.34%")
    """
    if previous == 0:
        return "0.00%"

    change_rate = ((current - previous) / previous) * 100
    sign = "+" if change_rate > 0 else ""
    return f"{sign}{change_rate:.2f}%"


def format_large_number(value: int | float) -> str:
    """
    큰 숫자 포맷팅 (억, 만 단위)

    Args:
        value: 숫자

    Returns:
        str: 포맷된 숫자 (예: "1억 2,345만원")
    """
    if value >= 100_000_000:  # 1억 이상
        eok = value // 100_000_000
        remainder = value % 100_000_000
        if remainder >= 10_000:
            man = remainder // 10_000
            return f"{eok:,}억 {man:,}만원"
        return f"{eok:,}억원"
    elif value >= 10_000:  # 1만 이상
        man = value // 10_000
        return f"{man:,}만원"
    else:
        return f"{value:,}원"


# ==================== 날짜/시간 포맷팅 ====================


def format_datetime(dt: datetime, format_string: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    날짜/시간 포맷팅

    Args:
        dt: 날짜/시간
        format_string: 포맷 문자열

    Returns:
        str: 포맷된 날짜/시간
    """
    return dt.strftime(format_string)


def format_date(dt: datetime) -> str:
    """
    날짜 포맷팅 (YYYY-MM-DD)

    Args:
        dt: 날짜

    Returns:
        str: 포맷된 날짜
    """
    return dt.strftime("%Y-%m-%d")


def format_time(dt: datetime) -> str:
    """
    시간 포맷팅 (HH:MM:SS)

    Args:
        dt: 시간

    Returns:
        str: 포맷된 시간
    """
    return dt.strftime("%H:%M:%S")


def format_korean_datetime(dt: datetime) -> str:
    """
    한국어 날짜/시간 포맷팅

    Args:
        dt: 날짜/시간

    Returns:
        str: 포맷된 날짜/시간 (예: "2024년 10월 7일 15시 30분")
    """
    return dt.strftime("%Y년 %m월 %d일 %H시 %M분")


def format_relative_time(dt: datetime) -> str:
    """
    상대 시간 포맷팅 (몇 분 전, 몇 시간 전)

    Args:
        dt: 날짜/시간

    Returns:
        str: 상대 시간 (예: "3분 전", "2시간 전")
    """
    now = datetime.now()
    diff = now - dt

    seconds = diff.total_seconds()
    if seconds < 60:
        return "방금 전"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes}분 전"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours}시간 전"
    else:
        days = int(seconds / 86400)
        return f"{days}일 전"


# ==================== 문자열 포맷팅 ====================


def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """
    문자열 자르기

    Args:
        text: 문자열
        max_length: 최대 길이
        suffix: 접미사

    Returns:
        str: 자른 문자열
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def mask_string(text: str, start: int = 0, end: int | None = None, mask_char: str = "*") -> str:
    """
    문자열 마스킹

    Args:
        text: 문자열
        start: 시작 위치
        end: 종료 위치
        mask_char: 마스킹 문자

    Returns:
        str: 마스킹된 문자열
    """
    if end is None:
        end = len(text)

    masked = list(text)
    for i in range(start, min(end, len(text))):
        masked[i] = mask_char
    return "".join(masked)


def format_account_no(account_no: str) -> str:
    """
    계좌번호 포맷팅 (마스킹)

    Args:
        account_no: 계좌번호

    Returns:
        str: 포맷된 계좌번호 (예: "1234****")
    """
    if len(account_no) <= 4:
        return mask_string(account_no, 0, len(account_no))
    return account_no[:4] + "*" * (len(account_no) - 4)


# ==================== 금융 데이터 포맷팅 ====================


def format_order_status(status: str) -> str:
    """
    주문 상태 한글 변환

    Args:
        status: 주문 상태 (영문)

    Returns:
        str: 주문 상태 (한글)
    """
    status_map = {
        "pending": "대기",
        "submitted": "제출",
        "partially_filled": "부분체결",
        "filled": "체결완료",
        "canceled": "취소",
        "rejected": "거부",
        "failed": "실패",
    }
    return status_map.get(status, status)


def format_order_type(order_type: str) -> str:
    """
    주문 유형 한글 변환

    Args:
        order_type: 주문 유형 (영문)

    Returns:
        str: 주문 유형 (한글)
    """
    type_map = {"buy": "매수", "sell": "매도"}
    return type_map.get(order_type, order_type)


def format_price_type(price_type: str) -> str:
    """
    가격 유형 한글 변환

    Args:
        price_type: 가격 유형 (영문)

    Returns:
        str: 가격 유형 (한글)
    """
    type_map = {"market": "시장가", "limit": "지정가", "stop": "조건부지정가"}
    return type_map.get(price_type, price_type)


def format_profit_loss(
    profit_loss: Decimal | float, show_sign: bool = True
) -> str:
    """
    손익 포맷팅

    Args:
        profit_loss: 손익
        show_sign: 부호 표시 여부

    Returns:
        str: 포맷된 손익 (예: "+1,234,567원", "-123,456원")
    """
    formatted = format_large_number(abs(profit_loss))
    if show_sign:
        sign = "+" if profit_loss > 0 else "-" if profit_loss < 0 else ""
        return f"{sign}{formatted}"
    return formatted


# ==================== JSON 포맷팅 ====================


def format_json_compact(data: dict) -> str:
    """
    JSON 압축 포맷팅

    Args:
        data: 딕셔너리

    Returns:
        str: 압축된 JSON 문자열
    """
    import json

    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def format_json_pretty(data: dict) -> str:
    """
    JSON 예쁜 포맷팅

    Args:
        data: 딕셔너리

    Returns:
        str: 예쁘게 포맷된 JSON 문자열
    """
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)
