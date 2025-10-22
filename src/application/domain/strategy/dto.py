# -*- coding: utf-8 -*-
"""
Strategy Domain DTO - 전략 관련 데이터 전송 객체
"""

from datetime import datetime

from pydantic import Field, field_validator

from src.application.common.dto import BaseDTO


# ==================== Request DTOs ====================


class BollingerBandConfig(BaseDTO):
    """볼린저 밴드 설정"""

    period: int = Field(default=20, description="이동평균 기간", ge=5, le=200)
    std_multiplier: float = Field(default=2.0, description="표준편차 배수", ge=1.0, le=4.0)


class EnvelopeConfig(BaseDTO):
    """Envelope 설정"""

    period: int = Field(default=20, description="이동평균 기간", ge=5, le=200)
    percentage: float = Field(default=2.0, description="채널 폭 비율 (%)", ge=0.5, le=10.0)


class PositionConfig(BaseDTO):
    """포지션 관리 설정"""

    allocation_ratio: float = Field(
        default=0.1, description="자산 배분 비율 (0.1 = 10%)", ge=0.01, le=1.0
    )
    max_position_count: int = Field(default=5, description="최대 포지션 수", ge=1, le=20)


class RiskManagementConfig(BaseDTO):
    """리스크 관리 설정"""

    use_stop_loss: bool = Field(default=False, description="손절 사용 여부")
    stop_loss_ratio: float | None = Field(
        default=None, description="손절 비율 (예: -0.03 = -3%)", ge=-0.2, le=0.0
    )
    use_take_profit: bool = Field(default=False, description="익절 사용 여부")
    take_profit_ratio: float | None = Field(
        default=None, description="익절 비율 (예: 0.05 = +5%)", ge=0.0, le=1.0
    )
    use_trailing_stop: bool = Field(default=False, description="Trailing Stop 사용 여부")
    trailing_stop_ratio: float | None = Field(
        default=None, description="Trailing Stop 비율", ge=0.01, le=0.2
    )
    use_reverse_signal_exit: bool = Field(
        default=True, description="반대 시그널 발생 시 청산"
    )


class StrategyConfigDTO(BaseDTO):
    """전략 설정 (JSON 저장용)"""

    bollinger_band: BollingerBandConfig = Field(default_factory=BollingerBandConfig)
    envelope: EnvelopeConfig = Field(default_factory=EnvelopeConfig)
    position: PositionConfig = Field(default_factory=PositionConfig)
    risk_management: RiskManagementConfig = Field(default_factory=RiskManagementConfig)
    check_interval: int = Field(
        default=60, description="체크 주기 (초)", ge=10, le=3600
    )


class StrategyCreateRequestDTO(BaseDTO):
    """전략 생성 요청 DTO"""

    name: str = Field(description="전략명", min_length=1, max_length=100)
    description: str | None = Field(default=None, description="전략 설명")
    strategy_type: str = Field(
        default="mean_reversion", description="전략 유형", pattern="^(momentum|mean_reversion|breakout|grid|custom)$"
    )
    account_no: str | None = Field(default=None, description="계좌번호")
    symbols: list[str] = Field(description="대상 종목 리스트", min_length=1)
    config: StrategyConfigDTO = Field(default_factory=StrategyConfigDTO)

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("At least one symbol is required")
        # 종목 코드 중복 제거
        return list(set(s.strip() for s in v if s.strip()))


class StrategyUpdateRequestDTO(BaseDTO):
    """전략 수정 요청 DTO"""

    name: str | None = Field(default=None, description="전략명", min_length=1, max_length=100)
    description: str | None = Field(default=None, description="전략 설명")
    symbols: list[str] | None = Field(default=None, description="대상 종목 리스트")
    config: StrategyConfigDTO | None = Field(default=None, description="전략 설정")
    status: str | None = Field(
        default=None, description="전략 상태", pattern="^(active|paused|stopped|completed)$"
    )


# ==================== Response DTOs ====================


class StrategyDetailResponseDTO(BaseDTO):
    """전략 상세 정보 응답 DTO"""

    id: int = Field(description="전략 ID")
    name: str = Field(description="전략명")
    description: str | None = Field(description="전략 설명")
    strategy_type: str = Field(description="전략 유형")
    account_no: str = Field(description="계좌번호")
    symbols: list[str] = Field(description="대상 종목 리스트")
    status: str = Field(description="전략 상태")
    config: StrategyConfigDTO = Field(description="전략 설정")
    total_executions: int = Field(description="총 실행 횟수")
    successful_executions: int = Field(description="성공 실행 횟수")
    failed_executions: int = Field(description="실패 실행 횟수")
    success_rate: float = Field(description="성공률 (%)")
    last_executed_at: datetime | None = Field(description="마지막 실행 시각")
    started_at: datetime | None = Field(description="시작 시각")
    stopped_at: datetime | None = Field(description="중지 시각")
    created_at: datetime = Field(description="생성 시각")
    updated_at: datetime = Field(description="수정 시각")


class StrategyListResponseDTO(BaseDTO):
    """전략 목록 응답 DTO"""

    strategies: list[StrategyDetailResponseDTO] = Field(description="전략 목록")
    total_count: int = Field(description="전체 전략 수")
