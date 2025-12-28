# -*- coding: utf-8 -*-
"""
Strategy Domain DTO - 전략 관련 데이터 전송 객체
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import Field, field_validator

from src.application.common.dto import BaseDTO


# ==================== Strategy Type Enum ====================


class StrategyTypeEnum(str, Enum):
    """전략 유형"""

    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    GRID = "grid"
    GOLDEN_CROSS = "golden_cross"  # 골든크로스 전략
    CUSTOM = "custom"


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


class BaseStrategyConfig(BaseDTO):
    """기본 전략 설정"""
    pass


class BollingerStrategyConfigDTO(BaseStrategyConfig):
    """볼린저 밴드/엔벨로프 전략 설정 (기존 StrategyConfigDTO)"""

    strategy_type: Literal["mean_reversion"] = Field(default="mean_reversion", description="전략 유형")
    bollinger_band: BollingerBandConfig = Field(default_factory=BollingerBandConfig)
    envelope: EnvelopeConfig = Field(default_factory=EnvelopeConfig)
    position: PositionConfig = Field(default_factory=PositionConfig)
    risk_management: RiskManagementConfig = Field(default_factory=RiskManagementConfig)
    check_interval: int = Field(
        default=60, description="체크 주기 (초)", ge=10, le=3600
    )


# ==================== Golden Cross Strategy DTOs ====================


class GoldenCrossMAConfig(BaseDTO):
    """골든크로스 이동평균 설정"""

    short_period: int = Field(default=60, description="단기 MA 기간", ge=5, le=120)
    long_period: int = Field(default=200, description="장기 MA 기간", ge=60, le=400)


class StochasticConfig(BaseDTO):
    """Stochastic 설정"""

    k_period: int = Field(default=14, description="%K 기간", ge=5, le=30)
    d_period: int = Field(default=3, description="%D 기간", ge=2, le=10)
    oversold_threshold: float = Field(default=25.0, description="과매도 기준", ge=10, le=40)
    recovery_threshold: float = Field(default=20.0, description="회복 기준", ge=10, le=40)
    strong_recovery_threshold: float = Field(default=30.0, description="강한 회복 기준", ge=20, le=50)


class GoldenCrossRiskConfig(BaseDTO):
    """골든크로스 리스크 관리 설정"""

    # 손절/익절
    use_stop_loss: bool = Field(default=True, description="손절 사용 여부")
    stop_loss_ratio: float = Field(default=-0.07, description="손절 비율", ge=-0.20, le=0.0)
    use_take_profit: bool = Field(default=True, description="익절 사용 여부")
    take_profit_ratio: float = Field(default=0.20, description="익절 비율", ge=0.05, le=0.50)

    # 트레일링 스탑
    use_trailing_stop: bool = Field(default=True, description="트레일링 스탑 사용")
    trailing_stop_activation: float = Field(default=0.15, description="활성화 수익률", ge=0.05, le=0.30)
    trailing_stop_distance: float = Field(default=0.07, description="트레일링 거리", ge=0.03, le=0.15)

    # 보유 기간
    max_hold_days: int = Field(default=60, description="최대 보유 기간 (일)", ge=10, le=180)


class StockScreenerConfigDTO(BaseDTO):
    """종목 스크리너 설정"""

    # 시가총액 필터
    min_market_cap: int = Field(
        default=100_000_000_000,
        description="최소 시가총액 (원)",
        ge=10_000_000_000,
    )
    max_market_cap: int = Field(
        default=30_000_000_000_000,
        description="최대 시가총액 (원)",
        le=100_000_000_000_000,
    )

    # 거래량 필터
    min_avg_volume: int = Field(
        default=100_000,
        description="최소 평균 거래량 (주)",
        ge=10_000,
    )

    # 가격대 필터
    min_price: int = Field(default=1_000, description="최소 주가 (원)", ge=100)
    max_price: int = Field(default=500_000, description="최대 주가 (원)", le=10_000_000)

    # 제외 섹터
    excluded_sectors: list[str] = Field(
        default_factory=list, description="제외 섹터 목록"
    )

    # 최대 종목 수
    max_stocks: int = Field(default=50, description="최대 종목 수", ge=10, le=200)


class GoldenCrossConfigDTO(BaseStrategyConfig):
    """골든크로스 전략 전체 설정"""

    strategy_type: Literal["golden_cross"] = Field(default="golden_cross", description="전략 유형")

    # 이동평균 설정
    ma_config: GoldenCrossMAConfig = Field(default_factory=GoldenCrossMAConfig)

    # Stochastic 설정
    stochastic_config: StochasticConfig = Field(default_factory=StochasticConfig)

    # 리스크 관리 설정
    risk_config: GoldenCrossRiskConfig = Field(default_factory=GoldenCrossRiskConfig)

    # 종목 스크리너 설정
    screener_config: StockScreenerConfigDTO = Field(default_factory=StockScreenerConfigDTO)

    # 포지션 설정
    position: PositionConfig = Field(default_factory=PositionConfig)

    # OHLCV 데이터 기간 (MA 계산을 위해 최소 long_period + 50 필요)
    lookback_days: int = Field(default=250, description="데이터 조회 기간 (일)", ge=200, le=500)


# 다형성을 위한 Union 타입
StrategyConfigUnion = Annotated[
    Union[BollingerStrategyConfigDTO, GoldenCrossConfigDTO],
    Field(discriminator="strategy_type")
]

# 구버전 호환성을 위한 별칭
StrategyConfigDTO = BollingerStrategyConfigDTO


class StrategyCreateRequestDTO(BaseDTO):
    """전략 생성 요청 DTO"""

    name: str = Field(description="전략명", min_length=1, max_length=100)
    description: str | None = Field(default=None, description="전략 설명")
    strategy_type: str = Field(
        default="mean_reversion",
        description="전략 유형",
        pattern="^(momentum|mean_reversion|breakout|grid|golden_cross|custom)$",
    )
    account_no: str | None = Field(default=None, description="계좌번호")
    symbols: list[str] = Field(description="대상 종목 리스트", min_length=1)
    
    # 통합 설정 필드 (다형성 지원)
    config: StrategyConfigUnion | None = Field(
        default=None, description="전략 설정 (유형에 따라 자동 매핑)"
    )
    
    # 하위 호환성 유지 (Deprecated)
    golden_cross_config: GoldenCrossConfigDTO | None = Field(
        default=None, description="골든크로스 전략 설정 (Deprecated: config 사용 권장)"
    )

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
    
    # 통합 설정 필드
    config: StrategyConfigUnion | None = Field(
        default=None, description="전략 설정 (유형에 따라 자동 매핑)"
    )
    
    # 하위 호환성 유지
    golden_cross_config: GoldenCrossConfigDTO | None = Field(
        default=None, description="골든크로스 전략 설정 (Deprecated)"
    )
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
    
    # 통합 설정 필드
    config: StrategyConfigUnion | None = Field(
        default=None, description="전략 설정"
    )
    
    # 하위 호환성 유지
    golden_cross_config: GoldenCrossConfigDTO | None = Field(
        default=None, description="골든크로스 전략 설정 (Deprecated)"
    )
    
    total_executions: int = Field(description="총 실행 횟수")
    successful_executions: int = Field(description="성공 실행 횟수")
    failed_executions: int = Field(description="실패 실행 횟수")
    success_rate: float = Field(description="성공률 (%)")
    last_executed_at: datetime | None = Field(description="마지막 실행 시각")
    started_at: datetime | None = Field(description="시작 시각")
    stopped_at: datetime | None = Field(description="중지 시각")
    created_at: datetime = Field(description="생성 시각")
    updated_at: datetime = Field(description="수정 시각")

# ==================== Symbol State DTOs ====================


class SymbolStateDTO(BaseDTO):
    """종목별 상태 DTO"""

    strategy_id: int = Field(description="전략 ID")
    symbol: str = Field(description="종목코드")
    state: str = Field(description="현재 상태")

    gc_date: datetime | None = Field(default=None, description="골든크로스 발생일")
    pullback_date: datetime | None = Field(default=None, description="풀백 발생일")
    entry_date: datetime | None = Field(default=None, description="진입일")
    entry_price: Decimal | None = Field(default=None, description="진입가")
    quantity: int | None = Field(default=None, description="보유 수량")

    last_ma_short: Decimal | None = Field(default=None, description="최근 단기 MA")
    last_ma_long: Decimal | None = Field(default=None, description="최근 장기 MA")
    last_stoch_k: Decimal | None = Field(default=None, description="최근 Stochastic K")
    last_stoch_d: Decimal | None = Field(default=None, description="최근 Stochastic D")
    last_close: Decimal | None = Field(default=None, description="최근 종가")

    unrealized_pnl_ratio: float | None = Field(default=None, description="미실현 수익률")
    days_since_entry: int | None = Field(default=None, description="진입 후 경과일")

    last_checked_at: datetime | None = Field(default=None, description="마지막 체크 시각")
    created_at: datetime | None = Field(default=None, description="생성 시각")
    updated_at: datetime | None = Field(default=None, description="수정 시각")


class SymbolStateListDTO(BaseDTO):
    """종목 상태 목록 DTO"""

    states: list[SymbolStateDTO] = Field(description="종목 상태 목록")
    total_count: int = Field(description="전체 종목 수")
    state_counts: dict[str, int] = Field(description="상태별 종목 수")


# ==================== Signal DTOs ====================


class StrategySignalDTO(BaseDTO):
    """전략 시그널 DTO"""

    id: int = Field(description="시그널 ID")
    strategy_id: int = Field(description="전략 ID")
    symbol: str = Field(description="종목코드")
    signal_type: str = Field(description="시그널 유형 (buy/sell)")
    signal_status: str = Field(description="시그널 상태")
    signal_price: Decimal = Field(description="시그널 발생 가격")
    target_quantity: int | None = Field(default=None, description="목표 수량")

    executed_price: Decimal | None = Field(default=None, description="체결 가격")
    executed_quantity: int | None = Field(default=None, description="체결 수량")
    exit_reason: str | None = Field(default=None, description="청산 사유")
    realized_pnl: Decimal | None = Field(default=None, description="실현 손익")
    realized_pnl_ratio: Decimal | None = Field(default=None, description="실현 수익률")

    ma_short: Decimal | None = Field(default=None, description="단기 MA")
    ma_long: Decimal | None = Field(default=None, description="장기 MA")
    stoch_k: Decimal | None = Field(default=None, description="Stochastic K")
    stoch_d: Decimal | None = Field(default=None, description="Stochastic D")

    prev_state: str | None = Field(default=None, description="이전 상태")
    new_state: str | None = Field(default=None, description="새 상태")
    note: str | None = Field(default=None, description="비고")

    signal_at: datetime = Field(description="시그널 발생 시각")
    executed_at: datetime | None = Field(default=None, description="체결 시각")
    created_at: datetime | None = Field(default=None, description="생성 시각")


class SignalListDTO(BaseDTO):
    """시그널 목록 DTO"""

    signals: list[StrategySignalDTO] = Field(description="시그널 목록")
    total_count: int = Field(description="전체 시그널 수")


class SignalStatisticsDTO(BaseDTO):
    """시그널 통계 DTO"""

    total_signals: int = Field(description="전체 시그널 수")
    buy_signals: int = Field(description="매수 시그널 수")
    sell_signals: int = Field(description="매도 시그널 수")
    executed_signals: int = Field(description="체결 시그널 수")
    profitable_trades: int = Field(description="수익 거래 수")
    total_pnl: float = Field(description="총 실현 손익")
    win_rate: float = Field(description="승률 (%)")


# ==================== Stock Universe DTOs ====================


class StockUniverseItemDTO(BaseDTO):
    """종목 유니버스 항목 DTO"""

    symbol: str = Field(description="종목코드")
    name: str = Field(description="종목명")
    market: str = Field(description="시장 구분")
    sector: str | None = Field(default=None, description="섹터")
    market_cap: Decimal | None = Field(default=None, description="시가총액")
    avg_volume_20d: Decimal | None = Field(default=None, description="20일 평균 거래량")
    current_price: Decimal | None = Field(default=None, description="현재가")
    is_eligible: bool = Field(description="스크리닝 통과 여부")
    screening_score: Decimal | None = Field(default=None, description="스크리닝 점수")


class StockUniverseListDTO(BaseDTO):
    """종목 유니버스 목록 DTO"""

    stocks: list[StockUniverseItemDTO] = Field(description="종목 목록")
    total_count: int = Field(description="전체 종목 수")
    eligible_count: int = Field(description="스크리닝 통과 종목 수")


# ==================== Execute Request/Response DTOs ====================


class StrategyExecuteRequestDTO(BaseDTO):
    """전략 실행 요청 DTO"""

    dry_run: bool = Field(default=True, description="Dry Run 모드 (주문 생성 안함)")
    force: bool = Field(default=False, description="강제 실행 (락 무시)")


class StrategyExecuteResultDTO(BaseDTO):
    """전략 실행 결과 DTO"""

    strategy_id: int = Field(description="전략 ID")
    executed_at: datetime = Field(description="실행 시각")
    dry_run: bool = Field(description="Dry Run 여부")

    symbols_checked: int = Field(description="체크한 종목 수")
    buy_signals: int = Field(description="매수 시그널 수")
    sell_signals: int = Field(description="매도 시그널 수")
    orders_created: int = Field(description="생성된 주문 수")

    signals: list[StrategySignalDTO] = Field(description="발생한 시그널 목록")
    errors: list[str] = Field(default_factory=list, description="오류 메시지")
