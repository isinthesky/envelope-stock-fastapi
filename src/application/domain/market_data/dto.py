# -*- coding: utf-8 -*-
"""
MarketData Domain DTO - 시세 관련 데이터 전송 객체
"""

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from src.application.common.dto import BaseDTO


# ==================== Request DTOs ====================


class PriceRequestDTO(BaseDTO):
    """
    현재가 조회 요청 DTO

    Attributes:
        symbol: 종목코드
        market: 시장 구분 (domestic/overseas)
    """

    symbol: str = Field(description="종목코드", min_length=6, max_length=20)
    market: str = Field(default="domestic", pattern="^(domestic|overseas)$", description="시장 구분")


class OrderbookRequestDTO(BaseDTO):
    """
    호가 조회 요청 DTO

    Attributes:
        symbol: 종목코드
        market: 시장 구분
    """

    symbol: str = Field(description="종목코드", min_length=6, max_length=20)
    market: str = Field(default="domestic", pattern="^(domestic|overseas)$", description="시장 구분")


class ChartRequestDTO(BaseDTO):
    """
    차트 데이터 조회 요청 DTO

    Attributes:
        symbol: 종목코드
        interval: 시간 간격 (1m, 5m, 1h, 1d)
        start_date: 시작일
        end_date: 종료일
    """

    symbol: str = Field(description="종목코드", min_length=6, max_length=20)
    interval: str = Field(
        default="1d", pattern="^(1m|5m|15m|30m|1h|1d)$", description="시간 간격"
    )
    start_date: datetime | None = Field(default=None, description="시작일")
    end_date: datetime | None = Field(default=None, description="종료일")


# ==================== Response DTOs ====================


class PriceResponseDTO(BaseDTO):
    """
    현재가 응답 DTO

    Attributes:
        symbol: 종목코드
        symbol_name: 종목명
        current_price: 현재가
        open_price: 시가
        high_price: 고가
        low_price: 저가
        prev_close_price: 전일 종가
        change_amount: 전일 대비 금액
        change_rate: 전일 대비 등락률 (%)
        volume: 거래량
        timestamp: 시각
    """

    symbol: str = Field(description="종목코드")
    symbol_name: str | None = Field(default=None, description="종목명")
    current_price: Decimal = Field(description="현재가")
    open_price: Decimal = Field(description="시가")
    high_price: Decimal = Field(description="고가")
    low_price: Decimal = Field(description="저가")
    prev_close_price: Decimal = Field(description="전일 종가")
    change_amount: Decimal = Field(description="전일 대비 금액")
    change_rate: Decimal = Field(description="전일 대비 등락률 (%)")
    volume: int = Field(description="거래량")
    timestamp: datetime = Field(description="시각")


class OrderbookItemDTO(BaseDTO):
    """
    호가 아이템 DTO

    Attributes:
        price: 가격
        quantity: 수량
        orders: 주문 건수
    """

    price: Decimal = Field(description="가격")
    quantity: int = Field(description="수량")
    orders: int | None = Field(default=None, description="주문 건수")


class OrderbookResponseDTO(BaseDTO):
    """
    호가 응답 DTO

    Attributes:
        symbol: 종목코드
        symbol_name: 종목명
        ask_prices: 매도 호가 (10단계)
        bid_prices: 매수 호가 (10단계)
        total_ask_quantity: 총 매도 잔량
        total_bid_quantity: 총 매수 잔량
        timestamp: 시각
    """

    symbol: str = Field(description="종목코드")
    symbol_name: str | None = Field(default=None, description="종목명")
    ask_prices: list[OrderbookItemDTO] = Field(description="매도 호가 (10단계)")
    bid_prices: list[OrderbookItemDTO] = Field(description="매수 호가 (10단계)")
    total_ask_quantity: int = Field(description="총 매도 잔량")
    total_bid_quantity: int = Field(description="총 매수 잔량")
    timestamp: datetime = Field(description="시각")


class CandleDTO(BaseDTO):
    """
    캔들 데이터 DTO

    Attributes:
        timestamp: 시각
        open: 시가
        high: 고가
        low: 저가
        close: 종가
        volume: 거래량
    """

    timestamp: datetime = Field(description="시각")
    open: Decimal = Field(description="시가")
    high: Decimal = Field(description="고가")
    low: Decimal = Field(description="저가")
    close: Decimal = Field(description="종가")
    volume: int = Field(description="거래량")


class ChartResponseDTO(BaseDTO):
    """
    차트 데이터 응답 DTO

    Attributes:
        symbol: 종목코드
        symbol_name: 종목명
        interval: 시간 간격
        candles: 캔들 데이터 리스트
    """

    symbol: str = Field(description="종목코드")
    symbol_name: str | None = Field(default=None, description="종목명")
    interval: str = Field(description="시간 간격")
    candles: list[CandleDTO] = Field(description="캔들 데이터 리스트")


class MarketSummaryDTO(BaseDTO):
    """
    시장 요약 DTO

    Attributes:
        market: 시장명
        status: 상태 (open/close)
        total_volume: 총 거래량
        total_amount: 총 거래대금
        advance: 상승 종목 수
        decline: 하락 종목 수
        unchanged: 보합 종목 수
        timestamp: 시각
    """

    market: str = Field(description="시장명")
    status: str = Field(description="상태 (open/close)")
    total_volume: int = Field(description="총 거래량")
    total_amount: Decimal = Field(description="총 거래대금")
    advance: int = Field(description="상승 종목 수")
    decline: int = Field(description="하락 종목 수")
    unchanged: int = Field(description="보합 종목 수")
    timestamp: datetime = Field(description="시각")
