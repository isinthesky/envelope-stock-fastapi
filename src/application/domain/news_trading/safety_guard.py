# -*- coding: utf-8 -*-
"""
Safety Guard - 리스크 관리 모듈

Phase 4 (failure_analysis.md Part 3, 4) 기반:
- 포지션 사이징 (종목당 20%, 최대 3종목, 일일 50%)
- 손실 한도 (일일 -3%, 주간 -7%, 월간 -15%)
- 거래 제한 (일일 3회, 연속 손실 3회)
- 시장 상황 체크 (코스피 -2%)
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

from src.application.domain.news_trading.dto import (
    SafetyGuardConfigDTO,
    PositionSizingConfigDTO,
    RiskLimitConfigDTO,
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
        """총 손익 (실현 + 미실현)"""
        return self.realized_pnl + self.unrealized_pnl

    @property
    def is_loss_day(self) -> bool:
        """손실일 여부"""
        return self.total_pnl < 0


@dataclass
class AccountState:
    """계좌 상태"""
    initial_capital: Decimal
    current_capital: Decimal
    cash: Decimal
    position_value: Decimal = Decimal("0")
    positions: dict[str, Decimal] = field(default_factory=dict)  # symbol -> 투자금액

    # 일별 통계
    daily_stats: TradingDayStats | None = None

    # 주간/월간 손익
    weekly_pnl: Decimal = Decimal("0")
    monthly_pnl: Decimal = Decimal("0")

    # 시장 상태
    market_change: float = 0.0  # 코스피 등락률

    @property
    def total_invested(self) -> Decimal:
        """현재 투자 총액"""
        return sum(self.positions.values(), Decimal("0"))

    @property
    def position_count(self) -> int:
        """현재 포지션 수"""
        return len(self.positions)

    @property
    def available_cash(self) -> Decimal:
        """사용 가능 현금"""
        return self.cash

    @property
    def total_value(self) -> Decimal:
        """총 자산"""
        return self.cash + self.position_value


class SafetyGuard:
    """
    안전장치

    주요 기능:
    1. 거래 가능 여부 체크 (can_trade)
    2. 포지션 사이즈 계산 (calculate_position_size)
    3. 일일/주간/월간 손익 추적
    4. 시장 상황 모니터링
    """

    def __init__(
        self,
        config: SafetyGuardConfigDTO | None = None,
        initial_capital: Decimal = Decimal("10_000_000"),
    ):
        """
        Args:
            config: 안전장치 설정 (None이면 기본값 사용)
            initial_capital: 초기 자본
        """
        self.config = config or SafetyGuardConfigDTO()
        self.initial_capital = initial_capital

        # 계좌 상태 초기화
        self.account = AccountState(
            initial_capital=initial_capital,
            current_capital=initial_capital,
            cash=initial_capital,
            daily_stats=TradingDayStats(date=date.today()),
        )

        # 주간/월간 손익 히스토리
        self.daily_pnl_history: list[tuple[date, Decimal]] = []

    def can_trade(self) -> tuple[bool, TradingBlockReason | None, str | None]:
        """
        거래 가능 여부 체크

        Phase 4 - failure_analysis.md Part 4 기반:
        1. 일일 손실 한도 (-3%)
        2. 주간 손실 한도 (-7%)
        3. 월간 손실 한도 (-15%)
        4. 거래 횟수 한도 (3회/일)
        5. 연속 손실 한도 (3회)
        6. 시장 급락 (-2%)
        7. 손절 후 쿨다운 (30분)
        8. 최대 포지션 수 (3종목)
        9. 일일 최대 투자 비중 (50%)

        Returns:
            (거래 가능 여부, 차단 사유, 상세 메시지)
        """
        stats = self._get_today_stats()
        limits = self.config.risk_limits

        # 1. 일일 손실 한도 체크
        if self.config.enable_daily_loss_guard:
            daily_pnl_rate = float(stats.total_pnl / self.initial_capital)
            if daily_pnl_rate <= limits.daily_loss_limit_ratio:
                return (
                    False,
                    TradingBlockReason.DAILY_LOSS_LIMIT,
                    f"일일 손실 한도 도달 ({daily_pnl_rate:.2%} <= {limits.daily_loss_limit_ratio:.2%})"
                )

        # 2. 주간 손실 한도 체크
        weekly_pnl_rate = float(self.account.weekly_pnl / self.initial_capital)
        if weekly_pnl_rate <= limits.weekly_loss_limit_ratio:
            return (
                False,
                TradingBlockReason.WEEKLY_LOSS_LIMIT,
                f"주간 손실 한도 도달 ({weekly_pnl_rate:.2%} <= {limits.weekly_loss_limit_ratio:.2%})"
            )

        # 3. 월간 손실 한도 체크
        monthly_pnl_rate = float(self.account.monthly_pnl / self.initial_capital)
        if monthly_pnl_rate <= limits.monthly_loss_limit_ratio:
            return (
                False,
                TradingBlockReason.MONTHLY_LOSS_LIMIT,
                f"월간 손실 한도 도달 ({monthly_pnl_rate:.2%} <= {limits.monthly_loss_limit_ratio:.2%})"
            )

        # 4. 거래 횟수 한도 체크
        if self.config.enable_trade_count_guard:
            if stats.trades >= limits.max_daily_trades:
                return (
                    False,
                    TradingBlockReason.MAX_TRADES_REACHED,
                    f"일일 거래 횟수 한도 도달 ({stats.trades}/{limits.max_daily_trades})"
                )

        # 5. 연속 손실 한도 체크
        if self.config.enable_consecutive_loss_guard:
            if stats.consecutive_losses >= limits.max_consecutive_losses:
                return (
                    False,
                    TradingBlockReason.CONSECUTIVE_LOSSES,
                    f"연속 손실 한도 도달 ({stats.consecutive_losses}회)"
                )

        # 6. 시장 급락 체크
        if self.config.enable_market_crash_guard:
            if self.account.market_change <= limits.market_crash_threshold:
                return (
                    False,
                    TradingBlockReason.MARKET_CRASH,
                    f"시장 급락 ({self.account.market_change:.2%} <= {limits.market_crash_threshold:.2%})"
                )

        # 7. 손절 후 쿨다운 체크
        if stats.last_loss_time:
            cooldown_end = stats.last_loss_time + timedelta(
                minutes=limits.cooldown_after_loss_minutes
            )
            if datetime.now() < cooldown_end:
                remaining = (cooldown_end - datetime.now()).seconds // 60
                return (
                    False,
                    TradingBlockReason.COOLDOWN_PERIOD,
                    f"쿨다운 기간 ({remaining}분 남음)"
                )

        # 8. 최대 포지션 수 체크
        position_config = self.config.position_sizing
        if self.account.position_count >= position_config.max_concurrent_positions:
            return (
                False,
                TradingBlockReason.MAX_POSITIONS,
                f"최대 포지션 수 도달 ({self.account.position_count}/{position_config.max_concurrent_positions})"
            )

        # 9. 일일 최대 투자 비중 체크
        max_daily = self.initial_capital * Decimal(str(position_config.max_daily_investment_ratio))
        if self.account.total_invested >= max_daily:
            return (
                False,
                TradingBlockReason.MAX_DAILY_INVESTMENT,
                f"일일 투자 한도 도달 ({float(self.account.total_invested):,.0f}/{float(max_daily):,.0f})"
            )

        return True, None, None

    def calculate_position_size(
        self,
        symbol: str,
        current_price: Decimal,
        atr: Decimal | None = None,
    ) -> tuple[Decimal, int]:
        """
        포지션 사이즈 계산

        Args:
            symbol: 종목코드
            current_price: 현재가
            atr: ATR (변동성 기반 사이징 시 사용)

        Returns:
            (투자금액, 수량)
        """
        position_config = self.config.position_sizing

        # 기본 포지션 사이즈 (종목당 최대 비중)
        max_position_amount = self.initial_capital * Decimal(
            str(position_config.max_position_ratio)
        )

        # 가용 현금 고려
        available = min(max_position_amount, self.account.available_cash)

        # 일일 투자 한도 고려
        max_daily = self.initial_capital * Decimal(str(position_config.max_daily_investment_ratio))
        remaining_daily = max_daily - self.account.total_invested
        available = min(available, remaining_daily)

        # 변동성 기반 사이징 (옵션)
        if position_config.use_volatility_sizing and atr and atr > 0:
            # 1R = 계좌의 per_trade_risk_ratio
            one_r = self.initial_capital * Decimal(str(position_config.per_trade_risk_ratio))
            stop_distance = atr * 2
            if stop_distance > 0:
                volatility_based_amount = one_r / (stop_distance / current_price)
                available = min(available, volatility_based_amount)

        # 수량 계산
        if current_price > 0:
            quantity = int(available / current_price)
        else:
            quantity = 0

        # 실제 투자금액 재계산
        actual_amount = current_price * quantity

        return actual_amount, quantity

    def record_trade_result(
        self,
        symbol: str,
        is_win: bool,
        realized_pnl: Decimal,
        exit_reason: str | None = None,
    ) -> None:
        """
        거래 결과 기록

        Args:
            symbol: 종목코드
            is_win: 수익 여부
            realized_pnl: 실현 손익
            exit_reason: 청산 사유
        """
        stats = self._get_today_stats()

        stats.trades += 1
        stats.realized_pnl += realized_pnl

        if is_win:
            stats.wins += 1
            stats.consecutive_losses = 0
        else:
            stats.losses += 1
            stats.consecutive_losses += 1
            stats.last_loss_time = datetime.now()

        # 계좌 업데이트
        self.account.cash += realized_pnl
        self.account.current_capital += realized_pnl

        # 포지션 제거
        if symbol in self.account.positions:
            del self.account.positions[symbol]

        # 주간/월간 손익 업데이트
        self.account.weekly_pnl += realized_pnl
        self.account.monthly_pnl += realized_pnl

    def open_position(
        self,
        symbol: str,
        amount: Decimal,
    ) -> bool:
        """
        포지션 오픈 기록

        Args:
            symbol: 종목코드
            amount: 투자금액

        Returns:
            성공 여부
        """
        can, reason, _ = self.can_trade()
        if not can:
            return False

        self.account.positions[symbol] = amount
        self.account.cash -= amount

        stats = self._get_today_stats()
        stats.total_invested += amount

        return True

    def update_unrealized_pnl(
        self,
        symbol: str,
        unrealized_pnl: Decimal,
    ) -> None:
        """미실현 손익 업데이트"""
        stats = self._get_today_stats()
        stats.unrealized_pnl = unrealized_pnl

    def update_market_change(self, change_rate: float) -> None:
        """시장 등락률 업데이트 (코스피 기준)"""
        self.account.market_change = change_rate

    def reset_daily_stats(self) -> None:
        """일별 통계 초기화 (새 거래일 시작)"""
        today = date.today()

        # 이전 일 통계 저장
        if self.account.daily_stats and self.account.daily_stats.date != today:
            self.daily_pnl_history.append((
                self.account.daily_stats.date,
                self.account.daily_stats.total_pnl,
            ))

            # 히스토리 관리 (최근 60일)
            if len(self.daily_pnl_history) > 60:
                self.daily_pnl_history = self.daily_pnl_history[-60:]

        # 새 통계 초기화
        self.account.daily_stats = TradingDayStats(date=today)

        # 주간/월간 손익 재계산
        self._recalculate_periodic_pnl()

    def _get_today_stats(self) -> TradingDayStats:
        """오늘 통계 가져오기 (없으면 생성)"""
        today = date.today()

        if self.account.daily_stats is None or self.account.daily_stats.date != today:
            self.reset_daily_stats()

        return self.account.daily_stats  # type: ignore

    def _recalculate_periodic_pnl(self) -> None:
        """주간/월간 손익 재계산"""
        today = date.today()

        # 주간 손익 (최근 7일)
        week_start = today - timedelta(days=7)
        self.account.weekly_pnl = sum(
            pnl for d, pnl in self.daily_pnl_history
            if d >= week_start
        )

        # 월간 손익 (최근 30일)
        month_start = today - timedelta(days=30)
        self.account.monthly_pnl = sum(
            pnl for d, pnl in self.daily_pnl_history
            if d >= month_start
        )

    def get_status(self) -> dict[str, Any]:
        """현재 상태 요약"""
        stats = self._get_today_stats()
        can_trade, block_reason, block_message = self.can_trade()

        return {
            "can_trade": can_trade,
            "block_reason": block_reason.value if block_reason else None,
            "block_message": block_message,
            "account": {
                "initial_capital": float(self.initial_capital),
                "current_capital": float(self.account.current_capital),
                "cash": float(self.account.cash),
                "total_invested": float(self.account.total_invested),
                "position_count": self.account.position_count,
                "market_change": self.account.market_change,
            },
            "daily_stats": {
                "date": stats.date.isoformat(),
                "trades": stats.trades,
                "wins": stats.wins,
                "losses": stats.losses,
                "consecutive_losses": stats.consecutive_losses,
                "realized_pnl": float(stats.realized_pnl),
                "unrealized_pnl": float(stats.unrealized_pnl),
                "total_pnl": float(stats.total_pnl),
                "pnl_rate": float(stats.total_pnl / self.initial_capital) * 100,
            },
            "periodic_pnl": {
                "weekly": float(self.account.weekly_pnl),
                "weekly_rate": float(self.account.weekly_pnl / self.initial_capital) * 100,
                "monthly": float(self.account.monthly_pnl),
                "monthly_rate": float(self.account.monthly_pnl / self.initial_capital) * 100,
            },
            "limits": {
                "max_daily_trades": self.config.risk_limits.max_daily_trades,
                "trades_remaining": max(0, self.config.risk_limits.max_daily_trades - stats.trades),
                "max_positions": self.config.position_sizing.max_concurrent_positions,
                "positions_remaining": max(
                    0,
                    self.config.position_sizing.max_concurrent_positions - self.account.position_count
                ),
            },
        }

    def get_position_size_recommendation(
        self,
        symbol: str,
        current_price: Decimal,
    ) -> dict[str, Any]:
        """포지션 사이즈 권장 정보"""
        amount, quantity = self.calculate_position_size(symbol, current_price)

        return {
            "symbol": symbol,
            "current_price": float(current_price),
            "recommended_amount": float(amount),
            "recommended_quantity": quantity,
            "max_position_ratio": self.config.position_sizing.max_position_ratio,
            "available_cash": float(self.account.available_cash),
        }
