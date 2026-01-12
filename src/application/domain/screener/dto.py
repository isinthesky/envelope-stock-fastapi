# -*- coding: utf-8 -*-
"""
Value Stock Screener DTO

가치주 스크리닝 조건 및 결과 DTO 정의
"""

from pydantic import Field

from src.application.common.dto import BaseDTO


class ValueScreenerCriteria(BaseDTO):
    """
    가치주 스크리닝 조건

    Attributes:
        max_market_cap: 시가총액 상한 (원), 기본 1조원
        min_retention_ratio: 유보율 최소값 (%), 기본 0
        min_quick_ratio: 당좌비율 최소값 (%), 기본 0
        max_debt_ratio: 부채비율 상한 (%), 기본 None (제한 없음)
    """

    max_market_cap: int = Field(
        default=1_000_000_000_000,
        description="시가총액 상한 (원)",
        examples=[1_000_000_000_000],
    )
    min_retention_ratio: float = Field(
        default=0,
        ge=0,
        description="유보율 최소값 (%)",
        examples=[500],
    )
    min_quick_ratio: float = Field(
        default=0,
        ge=0,
        description="당좌비율 최소값 (%)",
        examples=[100],
    )
    max_debt_ratio: float | None = Field(
        default=None,
        ge=0,
        description="부채비율 상한 (%)",
        examples=[100],
    )


class ValueStockItemDTO(BaseDTO):
    """
    가치주 스크리닝 결과 항목

    Attributes:
        symbol: 종목코드
        name: 종목명
        market_cap: 시가총액 (원)
        market_cap_display: 시가총액 표시용 (억 단위)
        retention_ratio: 유보율 (%)
        quick_ratio: 당좌비율 (%)
        debt_ratio: 부채비율 (%)
        roe: ROE (%)
        per: PER
        pbr: PBR
    """

    symbol: str = Field(description="종목코드")
    name: str = Field(description="종목명")
    market_cap: int = Field(description="시가총액 (원)")
    market_cap_display: str = Field(description="시가총액 표시용")
    retention_ratio: float | None = Field(default=None, description="유보율 (%)")
    quick_ratio: float | None = Field(default=None, description="당좌비율 (%)")
    debt_ratio: float | None = Field(default=None, description="부채비율 (%)")
    roe: float | None = Field(default=None, description="ROE (%)")
    per: float | None = Field(default=None, description="PER")
    pbr: float | None = Field(default=None, description="PBR")

    @classmethod
    def format_market_cap(cls, value: int) -> str:
        """시가총액을 억 단위 문자열로 변환"""
        if value >= 1_000_000_000_000:  # 1조 이상
            return f"{value / 1_000_000_000_000:.1f}조"
        elif value >= 100_000_000:  # 1억 이상
            return f"{value / 100_000_000:,.0f}억"
        else:
            return f"{value:,}원"


class ValueScreenerResultDTO(BaseDTO):
    """
    가치주 스크리닝 결과

    Attributes:
        items: 스크리닝 결과 목록
        total_count: 전체 종목 수
        filtered_count: 필터링된 종목 수
        criteria: 적용된 스크리닝 조건
    """

    items: list[ValueStockItemDTO] = Field(description="스크리닝 결과 목록")
    total_count: int = Field(description="스크리닝 대상 종목 수")
    filtered_count: int = Field(description="조건 통과 종목 수")
    criteria: ValueScreenerCriteria = Field(description="적용된 스크리닝 조건")
