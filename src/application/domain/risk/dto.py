# -*- coding: utf-8 -*-
"""Risk/SafetyGuard DTOs

기존 코드에서 사용되던 SafetyGuard 관련 DTO만 분리.
(뉴스 기반 단타 기능 제거 목적)
"""

from pydantic import Field

from src.application.common.dto import BaseDTO


class PositionSizingConfigDTO(BaseDTO):
    """포지션 사이징 설정 DTO"""

    max_position_ratio: float = Field(
        default=0.08, description="종목당 최대 비중 (8%)", ge=0.05, le=0.5
    )
    max_concurrent_positions: int = Field(
        default=3, description="동시 보유 최대 종목 수", ge=1, le=10
    )
    max_daily_investment_ratio: float = Field(
        default=0.5, description="일일 최대 투자 비중 (50%)", ge=0.1, le=1.0
    )

    # 변동성 기반 사이징
    use_volatility_sizing: bool = Field(
        default=False, description="변동성 기반 포지션 사이징 사용"
    )
    per_trade_risk_ratio: float = Field(
        default=0.02, description="거래당 계좌 리스크 비율 (2%)", ge=0.005, le=0.05
    )


class RiskLimitConfigDTO(BaseDTO):
    """리스크 한도 설정 DTO"""

    daily_loss_limit_ratio: float = Field(
        default=-0.04, description="일일 손실 한도 (-4%)", ge=-0.1, le=0.0
    )
    weekly_loss_limit_ratio: float = Field(
        default=-0.07, description="주간 손실 한도 (-7%)", ge=-0.2, le=0.0
    )
    monthly_loss_limit_ratio: float = Field(
        default=-0.15, description="월간 손실 한도 (-15%)", ge=-0.3, le=0.0
    )

    max_daily_trades: int = Field(default=3, description="일일 최대 거래 횟수", ge=1, le=10)
    max_consecutive_losses: int = Field(
        default=3, description="연속 손실 허용 횟수", ge=1, le=10
    )
    cooldown_after_loss_minutes: int = Field(
        default=30, description="손절 후 쿨다운 시간 (분)", ge=0, le=120
    )

    market_crash_threshold: float = Field(
        default=-0.02, description="시장 급락 임계 (코스피 -2%)", ge=-0.1, le=0.0
    )


class SafetyGuardConfigDTO(BaseDTO):
    """안전장치 설정 DTO"""

    position_sizing: PositionSizingConfigDTO = Field(default_factory=PositionSizingConfigDTO)
    risk_limits: RiskLimitConfigDTO = Field(default_factory=RiskLimitConfigDTO)

    enable_daily_loss_guard: bool = Field(default=True, description="일일 손실 한도 가드")
    enable_trade_count_guard: bool = Field(default=True, description="거래 횟수 가드")
    enable_consecutive_loss_guard: bool = Field(default=True, description="연속 손실 가드")
    enable_market_crash_guard: bool = Field(default=True, description="시장 급락 가드")
