# -*- coding: utf-8 -*-
"""
Backtest Domain DTO - 백테스팅 관련 데이터 전송 객체
"""

from datetime import datetime
from decimal import Decimal

from pydantic import Field, field_validator

from src.application.common.dto import BaseDTO
from src.application.domain.strategy.dto import StrategyConfigDTO


# ==================== Request DTOs ====================


class BacktestConfigDTO(BaseDTO):
    """
    백테스팅 설정 DTO

    Attributes:
        initial_capital: 초기 자본
        commission_rate: 수수료율 (예: 0.00015 = 0.015%)
        tax_rate: 증권거래세율 (예: 0.0023 = 0.23%)
        slippage_rate: 슬리피지율 (예: 0.0005 = 0.05%)
        use_commission: 수수료 사용 여부
        use_tax: 세금 사용 여부
        use_slippage: 슬리피지 사용 여부
    """

    initial_capital: Decimal = Field(
        default=Decimal("10_000_000"),
        description="초기 자본",
        ge=Decimal("100_000")
    )
    commission_rate: float = Field(
        default=0.00015,
        description="수수료율 (0.00015 = 0.015%)",
        ge=0.0,
        le=0.01
    )
    tax_rate: float = Field(
        default=0.0023,
        description="증권거래세율 (0.0023 = 0.23%)",
        ge=0.0,
        le=0.01
    )
    slippage_rate: float = Field(
        default=0.0005,
        description="슬리피지율 (0.0005 = 0.05%)",
        ge=0.0,
        le=0.01
    )
    use_commission: bool = Field(default=True, description="수수료 사용 여부")
    use_tax: bool = Field(default=True, description="세금 사용 여부")
    use_slippage: bool = Field(default=True, description="슬리피지 사용 여부")


class BacktestRequestDTO(BaseDTO):
    """
    백테스팅 요청 DTO

    Attributes:
        symbol: 종목코드
        start_date: 시작일
        end_date: 종료일
        strategy_config: 전략 설정
        backtest_config: 백테스팅 설정
    """

    symbol: str = Field(description="종목코드", min_length=6, max_length=20)
    start_date: datetime = Field(description="시작일")
    end_date: datetime = Field(description="종료일")
    strategy_config: StrategyConfigDTO = Field(
        default_factory=StrategyConfigDTO,
        description="전략 설정"
    )
    backtest_config: BacktestConfigDTO = Field(
        default_factory=BacktestConfigDTO,
        description="백테스팅 설정"
    )

    @field_validator("end_date")
    @classmethod
    def validate_dates(cls, v: datetime, info) -> datetime:
        """날짜 검증"""
        start_date = info.data.get("start_date")
        if start_date and v <= start_date:
            raise ValueError("end_date must be after start_date")
        return v


class MultiSymbolBacktestRequestDTO(BaseDTO):
    """
    다중 종목 백테스팅 요청 DTO

    Attributes:
        symbols: 종목코드 리스트
        start_date: 시작일
        end_date: 종료일
        strategy_config: 전략 설정
        backtest_config: 백테스팅 설정
    """

    symbols: list[str] = Field(description="종목코드 리스트", min_length=1)
    start_date: datetime = Field(description="시작일")
    end_date: datetime = Field(description="종료일")
    strategy_config: StrategyConfigDTO = Field(
        default_factory=StrategyConfigDTO,
        description="전략 설정"
    )
    backtest_config: BacktestConfigDTO = Field(
        default_factory=BacktestConfigDTO,
        description="백테스팅 설정"
    )


# ==================== Trade DTOs ====================


class TradeDTO(BaseDTO):
    """
    거래 내역 DTO

    Attributes:
        trade_id: 거래 ID
        symbol: 종목코드
        trade_type: 거래 유형 (buy/sell)
        entry_date: 진입일
        entry_price: 진입 가격
        exit_date: 청산일
        exit_price: 청산 가격
        quantity: 수량
        commission: 수수료
        tax: 세금
        profit: 손익 (금액)
        profit_rate: 손익률 (%)
        holding_days: 보유 기간 (일)
        exit_reason: 청산 이유 (signal/stop_loss/take_profit/trailing_stop)
    """

    trade_id: int = Field(description="거래 ID")
    symbol: str = Field(description="종목코드")
    trade_type: str = Field(description="거래 유형", pattern="^(buy|sell)$")
    entry_date: datetime = Field(description="진입일")
    entry_price: Decimal = Field(description="진입 가격")
    exit_date: datetime | None = Field(default=None, description="청산일")
    exit_price: Decimal | None = Field(default=None, description="청산 가격")
    quantity: int = Field(description="수량")
    commission: Decimal = Field(default=Decimal("0"), description="수수료")
    tax: Decimal = Field(default=Decimal("0"), description="세금")
    profit: Decimal | None = Field(default=None, description="손익 (금액)")
    profit_rate: float | None = Field(default=None, description="손익률 (%)")
    holding_days: int | None = Field(default=None, description="보유 기간 (일)")
    exit_reason: str | None = Field(
        default=None,
        description="청산 이유",
        pattern="^(signal|stop_loss|take_profit|trailing_stop)$"
    )


class PositionDTO(BaseDTO):
    """
    포지션 정보 DTO

    Attributes:
        symbol: 종목코드
        quantity: 수량
        entry_price: 평균 매수가
        entry_date: 진입일
        current_price: 현재가
        unrealized_profit: 평가 손익
        unrealized_profit_rate: 평가 손익률 (%)
    """

    symbol: str = Field(description="종목코드")
    quantity: int = Field(description="수량")
    entry_price: Decimal = Field(description="평균 매수가")
    entry_date: datetime = Field(description="진입일")
    current_price: Decimal = Field(description="현재가")
    unrealized_profit: Decimal = Field(description="평가 손익")
    unrealized_profit_rate: float = Field(description="평가 손익률 (%)")


class DailyStatsDTO(BaseDTO):
    """
    일별 통계 DTO

    Attributes:
        date: 날짜
        equity: 총 자산
        cash: 현금
        position_value: 포지션 가치
        daily_return: 일일 수익률 (%)
        cumulative_return: 누적 수익률 (%)
        drawdown: 낙폭 (%)
    """

    date: datetime = Field(description="날짜")
    equity: Decimal = Field(description="총 자산")
    cash: Decimal = Field(description="현금")
    position_value: Decimal = Field(description="포지션 가치")
    daily_return: float = Field(description="일일 수익률 (%)")
    cumulative_return: float = Field(description="누적 수익률 (%)")
    drawdown: float = Field(description="낙폭 (%)")


# ==================== Result DTOs ====================


class BacktestResultDTO(BaseDTO):
    """
    백테스팅 결과 DTO

    Attributes:
        # 기본 정보
        symbol: 종목코드
        start_date: 시작일
        end_date: 종료일
        initial_capital: 초기 자본
        final_capital: 최종 자본

        # 수익 지표
        total_return: 총 수익률 (%)
        annualized_return: 연환산 수익률 (%)
        cagr: 복리 연평균 성장률 (%)

        # 리스크 지표
        mdd: 최대 낙폭 (%)
        volatility: 연환산 변동성 (%)
        sharpe_ratio: Sharpe Ratio
        sortino_ratio: Sortino Ratio
        calmar_ratio: Calmar Ratio
        var_95: VaR 95% (%)

        # 거래 통계
        total_trades: 총 거래 횟수
        winning_trades: 이익 거래 수
        losing_trades: 손실 거래 수
        win_rate: 승률 (%)
        profit_factor: Profit Factor
        avg_win: 평균 수익 (%)
        avg_loss: 평균 손실 (%)
        avg_win_loss_ratio: 평균 손익비
        avg_holding_days: 평균 보유 기간 (일)
        max_consecutive_wins: 최대 연승
        max_consecutive_losses: 최대 연패

        # 벤치마크 비교 (선택)
        benchmark_return: 벤치마크 수익률 (%)
        alpha: Alpha (%)
        beta: Beta
        tracking_error: Tracking Error (%)
        information_ratio: Information Ratio

        # 상세 데이터
        trades: 거래 내역 리스트
        daily_stats: 일별 통계 리스트
    """

    # 기본 정보
    symbol: str = Field(description="종목코드")
    start_date: datetime = Field(description="시작일")
    end_date: datetime = Field(description="종료일")
    initial_capital: Decimal = Field(description="초기 자본")
    final_capital: Decimal = Field(description="최종 자본")

    # 수익 지표
    total_return: float = Field(description="총 수익률 (%)")
    annualized_return: float = Field(description="연환산 수익률 (%)")
    cagr: float = Field(description="복리 연평균 성장률 (%)")

    # 리스크 지표
    mdd: float = Field(description="최대 낙폭 (%)")
    volatility: float = Field(description="연환산 변동성 (%)")
    sharpe_ratio: float = Field(description="Sharpe Ratio")
    sortino_ratio: float = Field(description="Sortino Ratio")
    calmar_ratio: float = Field(description="Calmar Ratio")
    var_95: float = Field(description="VaR 95% (%)")

    # 거래 통계
    total_trades: int = Field(description="총 거래 횟수")
    winning_trades: int = Field(description="이익 거래 수")
    losing_trades: int = Field(description="손실 거래 수")
    win_rate: float = Field(description="승률 (%)")
    profit_factor: float = Field(description="Profit Factor")
    avg_win: float = Field(description="평균 수익 (%)")
    avg_loss: float = Field(description="평균 손실 (%)")
    avg_win_loss_ratio: float = Field(description="평균 손익비")
    avg_holding_days: float = Field(description="평균 보유 기간 (일)")
    max_consecutive_wins: int = Field(description="최대 연승")
    max_consecutive_losses: int = Field(description="최대 연패")

    # 벤치마크 비교 (선택)
    benchmark_return: float | None = Field(default=None, description="벤치마크 수익률 (%)")
    alpha: float | None = Field(default=None, description="Alpha (%)")
    beta: float | None = Field(default=None, description="Beta")
    tracking_error: float | None = Field(default=None, description="Tracking Error (%)")
    information_ratio: float | None = Field(default=None, description="Information Ratio")

    # 상세 데이터
    trades: list[TradeDTO] = Field(default_factory=list, description="거래 내역 리스트")
    daily_stats: list[DailyStatsDTO] = Field(default_factory=list, description="일별 통계 리스트")


class BacktestSummaryDTO(BaseDTO):
    """
    백테스팅 요약 DTO (리스트 조회용)

    Attributes:
        id: 백테스팅 ID
        symbol: 종목코드
        start_date: 시작일
        end_date: 종료일
        total_return: 총 수익률 (%)
        mdd: 최대 낙폭 (%)
        sharpe_ratio: Sharpe Ratio
        total_trades: 총 거래 횟수
        win_rate: 승률 (%)
        created_at: 생성 시각
    """

    id: int = Field(description="백테스팅 ID")
    symbol: str = Field(description="종목코드")
    start_date: datetime = Field(description="시작일")
    end_date: datetime = Field(description="종료일")
    total_return: float = Field(description="총 수익률 (%)")
    mdd: float = Field(description="최대 낙폭 (%)")
    sharpe_ratio: float = Field(description="Sharpe Ratio")
    total_trades: int = Field(description="총 거래 횟수")
    win_rate: float = Field(description="승률 (%)")
    created_at: datetime = Field(description="생성 시각")


class MultiSymbolBacktestResultDTO(BaseDTO):
    """
    다중 종목 백테스팅 결과 DTO

    Attributes:
        results: 종목별 백테스팅 결과
        total_count: 전체 종목 수
        success_count: 성공 종목 수
        failed_count: 실패 종목 수
    """

    results: dict[str, BacktestResultDTO] = Field(description="종목별 백테스팅 결과")
    total_count: int = Field(description="전체 종목 수")
    success_count: int = Field(description="성공 종목 수")
    failed_count: int = Field(description="실패 종목 수")
