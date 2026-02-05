# -*- coding: utf-8 -*-
"""Safety Guard - 리스크 관리 모듈

기존 코드에서 분리.
GoldenCross 전략에서 사용 중이어서 유지하되, 뉴스 기반 단타 기능은 제거.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum

from src.application.domain.risk.dto import (
    PositionSizingConfigDTO,
    RiskLimitConfigDTO,
    SafetyGuardConfigDTO,
)


class TradingBlockReason(str, Enum):
    """거래 차단 사유"""

    DAILY_LOSS_LIMIT = "daily_loss_limit"
    WEEKLY_LOSS_LIMIT = "weekly_loss_limit"
    MONTHLY_LOSS_LIMIT = "monthly_loss_limit"
    MAX_TRADES_REACHED = "max_trades_reached"
    CONSECUTIVE_LOSSES = "consecutive_losses"
    MARKET_CRASH = "market_crash"
    COOLDOWN_PERIOD = "cooldown_period"
    MAX_POSITIONS = "max_positions"
    MAX_DAILY_INVESTMENT = "max_daily_investment"


@dataclass
class TradingDayStats:
    """일별 거래 통계"""

    date: date
    trades: int = 0
    wins: int = 0
    losses: int = 0
    consecutive_losses: int = 0
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    total_invested: Decimal = Decimal("0")
    last_loss_time: datetime | None = None

    @property
    def total_pnl(self) -> Decimal:
        return self.realized_pnl + self.unrealized_pnl

    @property
    def is_loss_day(self) -> bool:
        return self.total_pnl < 0


@dataclass
class AccountState:
    """계좌 상태"""

    initial_capital: Decimal
    current_capital: Decimal
    cash: Decimal
    position_value: Decimal = Decimal("0")
    positions: dict[str, Decimal] = field(default_factory=dict)  # symbol -> 투자금액

    daily_stats: TradingDayStats | None = None

    weekly_pnl: Decimal = Decimal("0")
    monthly_pnl: Decimal = Decimal("0")

    market_change: float = 0.0

    @property
    def total_invested(self) -> Decimal:
        return sum(self.positions.values(), Decimal("0"))

    @property
    def position_count(self) -> int:
        return len(self.positions)

    @property
    def available_cash(self) -> Decimal:
        return self.cash

    @property
    def total_value(self) -> Decimal:
        return self.cash + self.position_value


class SafetyGuard:
    """안전장치"""

    def __init__(
        self,
        config: SafetyGuardConfigDTO | None = None,
        initial_capital: Decimal = Decimal("10_000_000"),
    ):
        self.config = config or SafetyGuardConfigDTO()
        self.initial_capital = initial_capital

        self.account = AccountState(
            initial_capital=initial_capital,
            current_capital=initial_capital,
            cash=initial_capital,
            daily_stats=TradingDayStats(date=date.today()),
        )

        self.daily_pnl_history: list[tuple[date, Decimal]] = []

    def can_trade(self) -> tuple[bool, TradingBlockReason | None, str | None]:
        stats = self._get_today_stats()
        limits: RiskLimitConfigDTO = self.config.risk_limits
        sizing: PositionSizingConfigDTO = self.config.position_sizing

        # 1) 일일 손실 한도
        if self.config.enable_daily_loss_guard:
            daily_pnl_rate = float(stats.total_pnl / self.initial_capital)
            if daily_pnl_rate <= limits.daily_loss_limit_ratio:
                return (
                    False,
                    TradingBlockReason.DAILY_LOSS_LIMIT,
                    f"일일 손실 한도 도달 ({daily_pnl_rate:.2%} <= {limits.daily_loss_limit_ratio:.2%})",
                )

        # 2) 주간 손실 한도
        weekly_pnl_rate = float(self.account.weekly_pnl / self.initial_capital)
        if weekly_pnl_rate <= limits.weekly_loss_limit_ratio:
            return (
                False,
                TradingBlockReason.WEEKLY_LOSS_LIMIT,
                f"주간 손실 한도 도달 ({weekly_pnl_rate:.2%} <= {limits.weekly_loss_limit_ratio:.2%})",
            )

        # 3) 월간 손실 한도
        monthly_pnl_rate = float(self.account.monthly_pnl / self.initial_capital)
        if monthly_pnl_rate <= limits.monthly_loss_limit_ratio:
            return (
                False,
                TradingBlockReason.MONTHLY_LOSS_LIMIT,
                f"월간 손실 한도 도달 ({monthly_pnl_rate:.2%} <= {limits.monthly_loss_limit_ratio:.2%})",
            )

        # 4) 거래 횟수
        if self.config.enable_trade_count_guard:
            if stats.trades >= limits.max_daily_trades:
                return (
                    False,
                    TradingBlockReason.MAX_TRADES_REACHED,
                    f"일일 거래 횟수 한도 도달 ({stats.trades}/{limits.max_daily_trades})",
                )

        # 5) 연속 손실
        if self.config.enable_consecutive_loss_guard:
            if stats.consecutive_losses >= limits.max_consecutive_losses:
                return (
                    False,
                    TradingBlockReason.CONSECUTIVE_LOSSES,
                    f"연속 손실 한도 도달 ({stats.consecutive_losses}회)",
                )

        # 6) 시장 급락
        if self.config.enable_market_crash_guard:
            if self.account.market_change <= limits.market_crash_threshold:
                return (
                    False,
                    TradingBlockReason.MARKET_CRASH,
                    f"시장 급락 ({self.account.market_change:.2%} <= {limits.market_crash_threshold:.2%})",
                )

        # 7) 손절 후 쿨다운
        if stats.last_loss_time:
            cooldown_end = stats.last_loss_time + timedelta(
                minutes=limits.cooldown_after_loss_minutes
            )
            if datetime.now() < cooldown_end:
                remaining = (cooldown_end - datetime.now()).seconds // 60
                return (
                    False,
                    TradingBlockReason.COOLDOWN_PERIOD,
                    f"손절 후 쿨다운 중 (남은 시간: {remaining}분)",
                )

        # 8) 최대 포지션 수
        if self.account.position_count >= sizing.max_concurrent_positions:
            return (
                False,
                TradingBlockReason.MAX_POSITIONS,
                f"최대 포지션 수 도달 ({self.account.position_count}/{sizing.max_concurrent_positions})",
            )

        # 9) 일일 최대 투자 비중 (단순: 현재 투자금 기준)
        if self.account.total_invested / self.initial_capital >= sizing.max_daily_investment_ratio:
            return (
                False,
                TradingBlockReason.MAX_DAILY_INVESTMENT,
                f"일일 최대 투자 비중 도달 ({self.account.total_invested/self.initial_capital:.2%} >= {sizing.max_daily_investment_ratio:.2%})",
            )

        return (True, None, None)

    def _get_today_stats(self) -> TradingDayStats:
        if not self.account.daily_stats or self.account.daily_stats.date != date.today():
            self.account.daily_stats = TradingDayStats(date=date.today())
        return self.account.daily_stats
