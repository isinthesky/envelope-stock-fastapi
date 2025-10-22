# -*- coding: utf-8 -*-
"""
Account Domain DTO - 계좌 관련 데이터 전송 객체
"""

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from src.application.common.dto import BaseDTO


# ==================== Request DTOs ====================


class AccountBalanceRequestDTO(BaseDTO):
    """
    계좌 잔고 조회 요청 DTO

    Attributes:
        account_no: 계좌번호
    """

    account_no: str | None = Field(default=None, description="계좌번호 (없으면 기본 계좌)")


class PositionListRequestDTO(BaseDTO):
    """
    포지션 목록 조회 요청 DTO

    Attributes:
        account_no: 계좌번호
    """

    account_no: str | None = Field(default=None, description="계좌번호")


# ==================== Response DTOs ====================


class AccountBalanceResponseDTO(BaseDTO):
    """
    계좌 잔고 응답 DTO

    Attributes:
        account_no: 계좌번호
        total_balance: 총 평가금액
        cash_balance: 예수금
        stock_balance: 주식 평가금액
        available_amount: 출금 가능 금액
        total_profit_loss: 총 손익
        total_profit_loss_rate: 총 손익률
        position_count: 보유 종목 수
        timestamp: 조회 시각
    """

    account_no: str = Field(description="계좌번호")
    total_balance: Decimal = Field(description="총 평가금액")
    cash_balance: Decimal = Field(description="예수금")
    stock_balance: Decimal = Field(description="주식 평가금액")
    available_amount: Decimal = Field(description="출금 가능 금액")
    total_profit_loss: Decimal = Field(description="총 손익")
    total_profit_loss_rate: Decimal = Field(description="총 손익률 (%)")
    position_count: int = Field(description="보유 종목 수")
    timestamp: datetime = Field(description="조회 시각")


class PositionResponseDTO(BaseDTO):
    """
    포지션 응답 DTO

    Attributes:
        symbol: 종목코드
        symbol_name: 종목명
        quantity: 보유 수량
        available_quantity: 매도 가능 수량
        avg_purchase_price: 평균 매입가
        current_price: 현재가
        purchase_amount: 매입 금액
        evaluated_amount: 평가 금액
        profit_loss: 평가 손익
        profit_loss_rate: 평가 손익률
    """

    symbol: str = Field(description="종목코드")
    symbol_name: str = Field(description="종목명")
    quantity: int = Field(description="보유 수량")
    available_quantity: int = Field(description="매도 가능 수량")
    avg_purchase_price: Decimal = Field(description="평균 매입가")
    current_price: Decimal = Field(description="현재가")
    purchase_amount: Decimal = Field(description="매입 금액")
    evaluated_amount: Decimal = Field(description="평가 금액")
    profit_loss: Decimal = Field(description="평가 손익")
    profit_loss_rate: Decimal = Field(description="평가 손익률 (%)")


class PositionListResponseDTO(BaseDTO):
    """
    포지션 목록 응답 DTO

    Attributes:
        account_no: 계좌번호
        positions: 포지션 목록
        total_count: 총 종목 수
        total_purchase_amount: 총 매입 금액
        total_evaluated_amount: 총 평가 금액
        total_profit_loss: 총 평가 손익
    """

    account_no: str = Field(description="계좌번호")
    positions: list[PositionResponseDTO] = Field(description="포지션 목록")
    total_count: int = Field(description="총 종목 수")
    total_purchase_amount: Decimal = Field(description="총 매입 금액")
    total_evaluated_amount: Decimal = Field(description="총 평가 금액")
    total_profit_loss: Decimal = Field(description="총 평가 손익")
