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
    # ATR 기반 동적 손절/트레일링
    use_atr_stop_loss: bool = Field(default=False, description="ATR 기반 손절 사용 여부")
    atr_stop_loss_multiplier: float = Field(
        default=2.0, description="ATR 손절 배수 (예: 2.0 = 진입가 - 2*ATR에서 손절)", ge=0.5, le=5.0
    )
    use_atr_trailing_stop: bool = Field(default=False, description="ATR 기반 트레일링 스톱 사용 여부")
    atr_trailing_multiplier: float = Field(
        default=2.0, description="ATR 트레일링 배수 (예: 2.0 = 최고가 - 2*ATR에서 청산)", ge=0.5, le=5.0
    )
    atr_period: int = Field(default=14, description="ATR 계산 기간", ge=5, le=50)


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

    short_period: int = Field(default=55, description="단기 MA 기간", ge=5, le=120)
    long_period: int = Field(default=165, description="장기 MA 기간", ge=60, le=400)


class StochasticConfig(BaseDTO):
    """Stochastic 설정"""

    k_period: int = Field(default=14, description="%K 기간", ge=5, le=30)
    d_period: int = Field(default=3, description="%D 기간", ge=2, le=10)
    oversold_threshold: float = Field(default=25.0, description="과매도 기준", ge=10, le=40)
    recovery_threshold: float = Field(default=20.0, description="회복 기준", ge=10, le=40)
    strong_recovery_threshold: float = Field(default=30.0, description="강한 회복 기준", ge=20, le=50)

    # OPTIMAL_BUY 조건용 (보수적 완화)
    deep_oversold_threshold: float = Field(
        default=30.0,
        description="깊은 과매도 기준 (OPTIMAL_BUY용, 기존 25에서 완화)",
        ge=15,
        le=40,
    )
    require_momentum_turn: bool = Field(
        default=False,
        description="K>D 조건 필수 여부 (False면 조건 무시)",
    )


class DynamicSellThresholdConfig(BaseDTO):
    """수익률 기반 동적 매도 임계값 설정"""

    # 고수익 구간 (수익률 >= 20%)
    high_profit_threshold: float = Field(default=0.20, description="고수익 기준")
    high_profit_stoch: float = Field(default=60.0, description="고수익 시 Stoch 임계값")
    high_profit_rsi: float = Field(default=65.0, description="고수익 시 RSI 임계값")

    # 중수익 구간 (수익률 10~20%)
    mid_profit_threshold: float = Field(default=0.10, description="중수익 기준")
    mid_profit_stoch: float = Field(default=65.0, description="중수익 시 Stoch 임계값")
    mid_profit_rsi: float = Field(default=68.0, description="중수익 시 RSI 임계값")

    # 기본 구간 (수익률 0~10%)
    default_stoch: float = Field(default=70.0, description="기본 Stoch 임계값")
    default_rsi: float = Field(default=70.0, description="기본 RSI 임계값")

    # 손실 구간 (수익률 < 0%)
    loss_stoch: float = Field(default=75.0, description="손실 시 Stoch 임계값")
    loss_rsi: float = Field(default=75.0, description="손실 시 RSI 임계값")

    # 긴급 손절 (수익률 <= -7%)
    emergency_stop_ratio: float = Field(default=-0.07, description="긴급 손절 기준")


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

    # 동적 매도 임계값 설정
    dynamic_sell: DynamicSellThresholdConfig = Field(
        default_factory=DynamicSellThresholdConfig,
        description="수익률 기반 동적 매도 임계값",
    )


class MAGapConfig(BaseDTO):
    """MA 갭 설정 (OPTIMAL_BUY 조건)"""

    min_gap_ratio: float = Field(
        default=0.0,
        description="최소 MA 갭 비율 (%)",
        ge=-5.0,
        le=10.0,
    )
    max_gap_ratio: float = Field(
        default=8.0,
        description="최대 MA 갭 비율 (%, 기존 5에서 완화)",
        ge=5.0,
        le=20.0,
    )


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
    max_stocks: int = Field(default=250, description="최대 종목 수", ge=10, le=500)


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

    # MA 갭 설정 (OPTIMAL_BUY 조건)
    ma_gap_config: MAGapConfig = Field(default_factory=MAGapConfig)

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


class StrategyListResponseDTO(BaseDTO):
    """전략 목록 응답 DTO"""

    strategies: list[StrategyDetailResponseDTO] = Field(description="전략 목록")
    total_count: int = Field(description="전체 전략 수")


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


# ==================== Golden Cross Scan DTOs ====================


class GoldenCrossScanItemDTO(BaseDTO):
    """골든크로스 스캔 결과 항목 DTO"""

    symbol: str = Field(description="종목코드")
    name: str = Field(description="종목명")
    market: str = Field(description="시장 구분")
    current_price: Decimal = Field(description="현재가")

    # 이동평균 (실시간 스캔용: MA55/MA165)
    ma_short: Decimal = Field(description="단기 MA (55일)")
    ma_long: Decimal = Field(description="장기 MA (165일)")
    ma_gap_ratio: float = Field(description="MA 갭 비율 ((MA55-MA165)/MA165*100)")

    # Stochastic
    stoch_k: float = Field(description="Stochastic %K")
    stoch_d: float = Field(description="Stochastic %D")

    # 상태
    is_gc_active: bool = Field(description="골든크로스 활성 여부 (MA55 > MA165)")
    gc_state: str = Field(
        description="골든크로스 상태 (NOT_GC, GC_ACTIVE, WAITING_FOR_PULLBACK, BUY_INTEREST, READY_TO_BUY, OPTIMAL_BUY)"
    )

    # 추가 정보
    market_cap: Decimal | None = Field(default=None, description="시가총액")
    screening_score: Decimal | None = Field(default=None, description="스크리닝 점수")

    # 재무 필터 (2차 필터) - DART API에서 조회
    financial_filter_status: str | None = Field(
        default=None,
        description="재무 필터 상태 (PASS, FAIL, TURNAROUND, PENDING, ERROR)"
    )
    revenue_yoy: float | None = Field(default=None, description="매출 YoY 증가율 (%)")
    operating_margin: float | None = Field(default=None, description="영업이익률 (%)")
    is_consecutive_profit: bool | None = Field(default=None, description="2년 연속 흑자 여부")
    is_turnaround: bool | None = Field(default=None, description="적자→흑자 전환 여부")


class GoldenCrossScanListDTO(BaseDTO):
    """골든크로스 스캔 결과 목록 DTO"""

    stocks: list[GoldenCrossScanItemDTO] = Field(description="스캔 결과 목록")
    total_scanned: int = Field(description="스캔한 전체 종목 수")
    gc_active_count: int = Field(description="골든크로스 활성 종목 수")
    pullback_waiting_count: int = Field(description="눌림목 대기 종목 수")
    buy_interest_count: int = Field(default=0, description="매수 관심 종목 수")
    ready_to_buy_count: int = Field(description="매수 준비 종목 수")
    optimal_buy_count: int = Field(default=0, description="매수 적기 종목 수")
    scan_time: datetime = Field(description="스캔 시각")
    errors: list[str] = Field(default_factory=list, description="오류 메시지")

    # 재무 필터 통계
    financial_pass_count: int = Field(default=0, description="재무 필터 통과 종목 수")
    financial_fail_count: int = Field(default=0, description="재무 필터 미통과 종목 수 (조건 불충족)")
    financial_error_count: int = Field(default=0, description="재무 필터 오류 종목 수 (조회 실패/데이터 없음)")
    turnaround_count: int = Field(default=0, description="턴어라운드(적자→흑자) 종목 수")
    financial_pending_count: int = Field(default=0, description="재무 필터 미조회 종목 수")


# ==================== MA5 Breakout Strategy DTOs ====================


class MA5BreakoutScanItemDTO(BaseDTO):
    """MA5 돌파 스캔 결과 항목 DTO"""

    symbol: str = Field(description="종목코드")
    name: str | None = Field(default=None, description="종목명")
    market: str | None = Field(default=None, description="시장 구분")
    current_price: float = Field(description="현재가")

    # 이동평균
    ma5: float = Field(description="5일 이동평균")
    ma300: float = Field(description="300일 이동평균")
    upper_band: float = Field(description="300일선 0.7% 상단")

    # 상태
    ma5_state: str = Field(
        description="MA5 상태 (BREAKOUT: 돌파, ABOVE: 상단 위, BELOW: 상단 아래)"
    )
    gap_ratio: float = Field(description="MA5와 상단 괴리율 ((MA5-상단)/상단*100)")

    # 거래량
    volume_ratio: float | None = Field(default=None, description="거래량 비율 (현재/20일평균)")


class MA5BreakoutScanListDTO(BaseDTO):
    """MA5 돌파 스캔 결과 목록 DTO"""

    stocks: list[MA5BreakoutScanItemDTO] = Field(description="스캔 결과 목록")
    total_scanned: int = Field(description="스캔한 전체 종목 수")
    breakout_count: int = Field(default=0, description="돌파 종목 수")
    above_count: int = Field(default=0, description="상단 위 종목 수")
    below_count: int = Field(default=0, description="상단 아래 종목 수")
    scan_time: datetime = Field(description="스캔 시각")
    errors: list[str] = Field(default_factory=list, description="오류 메시지")


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


# ==================== Sell Signal Analysis DTOs ====================


class SellPhaseEnum(str, Enum):
    """매도 Phase 단계"""

    NONE = "NONE"           # 매도 조건 없음
    PHASE_1 = "PHASE_1"     # 수익 보호 (GC 유지 + 과열)
    PHASE_2 = "PHASE_2"     # 매도 준비 (MA 갭 축소 + 과열)
    PHASE_3 = "PHASE_3"     # 매도 고려 (데드크로스 + 과열)
    PHASE_4 = "PHASE_4"     # 매도 권장 (데드크로스 + 강한 과열)
    PHASE_5 = "PHASE_5"     # 강력 매도 (데드크로스 + 극단적 과열)


class SellStageEnum(str, Enum):
    """비중축소 단계 (기존 Phase와 별도 관리)

    기존 SellPhaseEnum은 알림/이모지/DB에서 사용 중이므로 유지.
    SellStageEnum은 비중축소 비율 결정에만 사용.
    """

    HOLD = "HOLD"             # 보유 유지 (0%)
    REDUCE_1 = "REDUCE_1"     # 1차 축소 (20~30%)
    REDUCE_2 = "REDUCE_2"     # 2차 축소 (30~40%)
    EXIT_ALL = "EXIT_ALL"     # 전량 청산 (100%)


# 비중축소 단계별 매도 비율 (min, max)
SELL_STAGE_RATIOS: dict[SellStageEnum, tuple[float, float]] = {
    SellStageEnum.HOLD: (0.0, 0.0),
    SellStageEnum.REDUCE_1: (0.20, 0.30),  # 20~30%
    SellStageEnum.REDUCE_2: (0.30, 0.40),  # 30~40%
    SellStageEnum.EXIT_ALL: (1.0, 1.0),    # 100%
}


# Phase → Stage 매핑 (하위호환)
PHASE_TO_STAGE_MAP: dict[SellPhaseEnum, SellStageEnum] = {
    SellPhaseEnum.NONE: SellStageEnum.HOLD,
    SellPhaseEnum.PHASE_1: SellStageEnum.HOLD,       # 수익 보호 → 아직 매도 안 함
    SellPhaseEnum.PHASE_2: SellStageEnum.REDUCE_1,   # 매도 준비 → 1차 축소
    SellPhaseEnum.PHASE_3: SellStageEnum.REDUCE_1,   # 매도 고려 → 1차 축소
    SellPhaseEnum.PHASE_4: SellStageEnum.REDUCE_2,   # 매도 권장 → 2차 축소
    SellPhaseEnum.PHASE_5: SellStageEnum.EXIT_ALL,   # 강력 매도 → 전량 청산
}


SELL_PHASE_INFO: dict[str, dict[str, str]] = {
    "NONE": {"name": "보유 유지", "action": "현 상태 유지"},
    "PHASE_1": {"name": "수익 보호", "action": "부분 익절 고려 (50%)"},
    "PHASE_2": {"name": "매도 준비", "action": "트레일링 스탑 활성화 권장"},
    "PHASE_3": {"name": "매도 고려", "action": "매도 타이밍 모색"},
    "PHASE_4": {"name": "매도 권장", "action": "즉시 매도 권장"},
    "PHASE_5": {"name": "강력 매도", "action": "최우선 매도"},
}


SELL_STAGE_INFO: dict[str, dict[str, str]] = {
    "HOLD": {"name": "보유 유지", "action": "현 상태 유지", "ratio": "0%"},
    "REDUCE_1": {"name": "1차 비중 축소", "action": "20~30% 매도 고려", "ratio": "20~30%"},
    "REDUCE_2": {"name": "2차 비중 축소", "action": "30~40% 매도 권장", "ratio": "30~40%"},
    "EXIT_ALL": {"name": "전량 청산", "action": "즉시 전량 매도", "ratio": "100%"},
}


class SellSignalAnalysisDTO(BaseDTO):
    """매도 시그널 분석 결과 DTO"""

    symbol: str = Field(description="종목코드")
    name: str | None = Field(default=None, description="종목명")
    current_price: Decimal = Field(description="현재가")
    analyzed_at: datetime = Field(description="분석 시각")

    # 이동평균 지표
    ma_short: Decimal = Field(description="단기 MA (55일)")
    ma_long: Decimal = Field(description="장기 MA (165일)")
    ma_gap_ratio: float = Field(description="MA 갭 비율 (%)")
    is_death_cross: bool = Field(description="데드크로스 여부 (MA55 < MA165)")
    is_gc_active: bool = Field(default=False, description="골든크로스 활성 여부 (MA55 > MA165)")

    # Stochastic 지표
    stoch_k: float = Field(description="Stochastic %K")
    stoch_d: float = Field(description="Stochastic %D")
    is_stoch_overbought: bool = Field(description="Stochastic 과매수 (K > 70)")

    # RSI 지표
    rsi: float = Field(description="RSI (14일)")
    is_rsi_overbought: bool = Field(description="RSI 과매수 (RSI > 70)")

    # 매도 시그널 (Phase 기반)
    sell_phase: str = Field(default="NONE", description="매도 Phase (NONE~PHASE_5)")
    sell_phase_name: str = Field(default="보유 유지", description="Phase 이름")
    sell_phase_action: str = Field(default="현 상태 유지", description="Phase 권장 행동")
    sell_reasons: list[str] = Field(default_factory=list, description="매도 근거")

    # 수익률 관련 (entry_price 제공 시)
    entry_price: Decimal | None = Field(default=None, description="진입가")
    profit_ratio: float | None = Field(default=None, description="현재 수익률")
    dynamic_stoch_threshold: float | None = Field(default=None, description="적용된 Stoch 임계값")
    dynamic_rsi_threshold: float | None = Field(default=None, description="적용된 RSI 임계값")

    # 손절/익절 상태
    is_stop_loss_triggered: bool = Field(default=False, description="손절 라인 도달 여부")
    is_take_profit_triggered: bool = Field(default=False, description="익절 목표 도달 여부")

    # 트레일링 스탑 관련
    highest_price: Decimal | None = Field(default=None, description="포지션 최고가")
    drawdown_from_high: float | None = Field(default=None, description="고점 대비 하락률")
    trailing_stop_activated: bool = Field(default=False, description="트레일링 스탑 활성화 여부")

    # === 비중축소 관련 신규 필드 ===
    sell_stage: str = Field(
        default="HOLD",
        description="비중축소 단계 (HOLD, REDUCE_1, REDUCE_2, EXIT_ALL)",
        pattern="^(HOLD|REDUCE_1|REDUCE_2|EXIT_ALL)$",
    )
    sell_stage_name: str = Field(default="보유 유지", description="비중축소 단계 이름")
    sell_ratio_min: float = Field(default=0.0, description="최소 매도 비율 (0.0~1.0)")
    sell_ratio_max: float = Field(default=0.0, description="최대 매도 비율 (0.0~1.0)")
    sell_quantity_suggested: int | None = Field(default=None, description="권장 매도 수량")
    holding_quantity: int | None = Field(default=None, description="현재 보유 수량")
    sold_ratio: float = Field(default=0.0, description="기 매도 비율 (상태 추적용)")
    sell_stage_reasons: list[str] = Field(default_factory=list, description="비중축소 판단 근거")

    # === 거래량 관련 신규 필드 ===
    current_volume: int | None = Field(default=None, description="현재 거래량")
    prev_volume: int | None = Field(default=None, description="전일 거래량")
    volume_ma_20: float | None = Field(default=None, description="거래량 20일 평균")
    volume_ratio: float | None = Field(default=None, description="거래량 비율 (현재/평균)")
    is_volume_spike: bool = Field(default=False, description="거래량 급증 여부 (>= 1.3x)")
    price_drop_ratio: float | None = Field(default=None, description="가격 하락률")
    is_volume_sell_signal: bool = Field(default=False, description="거래량+하락 매도 신호")
    volume_sell_reasons: list[str] = Field(default_factory=list, description="거래량 매도 신호 근거")

    # === ADX 관련 신규 필드 ===
    adx: float | None = Field(default=None, description="ADX 값 (0~100, 추세 강도)")
    plus_di: float | None = Field(default=None, description="+DI 값 (상승 방향 강도)")
    minus_di: float | None = Field(default=None, description="-DI 값 (하락 방향 강도)")
    is_strong_uptrend: bool = Field(default=False, description="강한 상승 추세 여부 (ADX>25 & +DI>-DI)")
    is_strong_downtrend: bool = Field(default=False, description="강한 하락 추세 여부 (ADX>25 & -DI>+DI)")
    overbought_sell_blocked: bool = Field(default=False, description="과매수 매도 차단 여부 (강한 상승 추세)")

    # 추가 정보
    candle_count: int = Field(default=0, description="분석에 사용된 캔들 수")


class SellSignalRequestDTO(BaseDTO):
    """매도 시그널 분석 요청 DTO"""

    symbol: str = Field(description="종목코드")
    stoch_overbought: float = Field(default=70.0, ge=50.0, le=90.0, description="Stochastic 과매수 임계값")
    rsi_overbought: float = Field(default=70.0, ge=50.0, le=90.0, description="RSI 과매수 임계값")


# ==================== Analysis History DTOs ====================


class AnalysisHistoryDTO(BaseDTO):
    """분석 이력 DTO"""

    id: int = Field(description="ID")
    analysis_type: str = Field(description="분석 유형 (buy/sell)")
    symbol: str = Field(description="종목코드")
    name: str | None = Field(default=None, description="종목명")
    current_price: Decimal = Field(description="현재가")

    # 공통 지표
    ma_short: Decimal | None = Field(default=None, description="단기 MA (55일)")
    ma_long: Decimal | None = Field(default=None, description="장기 MA (165일)")
    ma_gap_ratio: float | None = Field(default=None, description="MA 갭 비율 (%)")
    stoch_k: float | None = Field(default=None, description="Stochastic K")
    stoch_d: float | None = Field(default=None, description="Stochastic D")

    # 매수 분석용 (골든크로스)
    gc_state: str | None = Field(default=None, description="골든크로스 상태")
    is_gc_active: bool | None = Field(default=None, description="골든크로스 활성 여부")

    # 매도 분석용
    rsi: float | None = Field(default=None, description="RSI (14일)")
    is_death_cross: bool | None = Field(default=None, description="데드크로스 여부")
    is_stoch_overbought: bool | None = Field(default=None, description="Stochastic 과매수 여부")
    is_rsi_overbought: bool | None = Field(default=None, description="RSI 과매수 여부")
    sell_phase: str | None = Field(default=None, description="매도 Phase (NONE~PHASE_5)")
    sell_phase_name: str | None = Field(default=None, description="Phase 이름")
    sell_phase_action: str | None = Field(default=None, description="Phase 권장 행동")
    sell_reasons: list[str] | None = Field(default=None, description="매도 근거")

    # 비중축소 분석용 (신규)
    sell_stage: str | None = Field(default=None, description="비중축소 단계 (HOLD, REDUCE_1, REDUCE_2, EXIT_ALL)")
    sell_stage_name: str | None = Field(default=None, description="비중축소 단계 이름")
    sell_ratio_min: float | None = Field(default=None, description="최소 매도 비율")
    sell_ratio_max: float | None = Field(default=None, description="최대 매도 비율")

    # 거래량 분석용 (신규)
    volume_ratio: float | None = Field(default=None, description="거래량 비율 (현재/평균)")
    is_volume_spike: bool | None = Field(default=None, description="거래량 급증 여부")
    is_volume_sell_signal: bool | None = Field(default=None, description="거래량+하락 매도 신호")

    # ADX 분석용 (신규)
    adx: float | None = Field(default=None, description="ADX 값")
    plus_di: float | None = Field(default=None, description="+DI 값")
    minus_di: float | None = Field(default=None, description="-DI 값")
    is_strong_uptrend: bool | None = Field(default=None, description="강한 상승 추세 여부")
    overbought_sell_blocked: bool | None = Field(default=None, description="과매수 매도 차단 여부")

    # 메타데이터
    analyzed_at: datetime = Field(description="분석 시각")
    entry_price: Decimal | None = Field(default=None, description="진입가 (수익률 계산용)")
    note: str | None = Field(default=None, description="사용자 메모")
    is_active: bool = Field(description="활성 추적 여부")
    candle_count: int | None = Field(default=None, description="분석에 사용된 캔들 수")
    created_at: datetime | None = Field(default=None, description="생성 시각")
    updated_at: datetime | None = Field(default=None, description="수정 시각")


class AnalysisHistoryListDTO(BaseDTO):
    """분석 이력 목록 DTO"""

    items: list[AnalysisHistoryDTO] = Field(description="분석 이력 목록")
    total_count: int = Field(description="전체 개수")


class AnalysisHistoryCreateDTO(BaseDTO):
    """분석 이력 생성 요청 DTO"""

    analysis_type: str = Field(description="분석 유형 (buy/sell)")
    symbol: str = Field(description="종목코드")
    name: str | None = Field(default=None, description="종목명")
    current_price: Decimal = Field(description="현재가")

    # 공통 지표
    ma_short: Decimal | None = Field(default=None, description="단기 MA")
    ma_long: Decimal | None = Field(default=None, description="장기 MA")
    ma_gap_ratio: float | None = Field(default=None, description="MA 갭 비율")
    stoch_k: float | None = Field(default=None, description="Stochastic K")
    stoch_d: float | None = Field(default=None, description="Stochastic D")

    # 매수 분석용
    gc_state: str | None = Field(default=None, description="골든크로스 상태")
    is_gc_active: bool | None = Field(default=None, description="골든크로스 활성 여부")

    # 매도 분석용
    rsi: float | None = Field(default=None, description="RSI")
    is_death_cross: bool | None = Field(default=None, description="데드크로스 여부")
    is_stoch_overbought: bool | None = Field(default=None, description="Stochastic 과매수 여부")
    is_rsi_overbought: bool | None = Field(default=None, description="RSI 과매수 여부")
    sell_phase: str | None = Field(default=None, description="매도 Phase (NONE~PHASE_5)")
    sell_reasons: list[str] = Field(default_factory=list, description="매도 근거")

    # 비중축소 분석용 (신규)
    sell_stage: str | None = Field(default=None, description="비중축소 단계")
    sell_ratio_min: float | None = Field(default=None, description="최소 매도 비율")
    sell_ratio_max: float | None = Field(default=None, description="최대 매도 비율")

    # 거래량 분석용 (신규)
    volume_ratio: float | None = Field(default=None, description="거래량 비율")
    is_volume_spike: bool | None = Field(default=None, description="거래량 급증 여부")
    is_volume_sell_signal: bool | None = Field(default=None, description="거래량+하락 매도 신호")

    # ADX 분석용 (신규)
    adx: float | None = Field(default=None, description="ADX 값")
    plus_di: float | None = Field(default=None, description="+DI 값")
    minus_di: float | None = Field(default=None, description="-DI 값")
    is_strong_uptrend: bool | None = Field(default=None, description="강한 상승 추세 여부")
    overbought_sell_blocked: bool | None = Field(default=None, description="과매수 매도 차단 여부")

    # 메타데이터 (analyzed_at은 서버에서 자동 설정)
    entry_price: Decimal | None = Field(default=None, description="진입가 (수익률 계산용)")
    note: str | None = Field(default=None, description="사용자 메모")
    is_active: bool = Field(default=True, description="활성 추적 여부")
    candle_count: int | None = Field(default=None, description="분석에 사용된 캔들 수")


class AnalysisHistoryUpdateDTO(BaseDTO):
    """분석 이력 업데이트 요청 DTO"""

    entry_price: Decimal | None = Field(default=None, description="진입가 (수익률 계산용)")
    note: str | None = Field(default=None, description="사용자 메모")


class AnalysisHistoryRefreshResultDTO(BaseDTO):
    """분석 이력 갱신 결과 DTO"""

    updated_count: int = Field(description="갱신된 항목 수")
    items: list[AnalysisHistoryDTO] = Field(description="갱신된 분석 이력 목록")
    errors: list[str] = Field(default_factory=list, description="오류 메시지")
