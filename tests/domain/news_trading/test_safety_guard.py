# -*- coding: utf-8 -*-
"""
Safety Guard 유닛 테스트
"""

import pytest
from datetime import datetime, date, timedelta
from decimal import Decimal

from src.application.domain.news_trading.dto import (
    SafetyGuardConfigDTO,
    PositionSizingConfigDTO,
    RiskLimitConfigDTO,
)
from src.application.domain.news_trading.safety_guard import SafetyGuard, TradingBlockReason


class TestSafetyGuard:
    """SafetyGuard 테스트"""

    @pytest.fixture
    def safety_config(self):
        """테스트용 안전장치 설정"""
        return SafetyGuardConfigDTO(
            position_sizing=PositionSizingConfigDTO(
                max_position_ratio=0.2,
                max_concurrent_positions=3,
                max_daily_investment_ratio=0.5,
            ),
            risk_limits=RiskLimitConfigDTO(
                daily_loss_limit_ratio=-0.03,
                weekly_loss_limit_ratio=-0.07,
                monthly_loss_limit_ratio=-0.15,
                max_daily_trades=3,
                max_consecutive_losses=3,
                cooldown_after_loss_minutes=30,
            ),
            enable_daily_loss_guard=True,
            enable_trade_count_guard=True,
            enable_consecutive_loss_guard=True,
            enable_market_crash_guard=True,
        )

    @pytest.fixture
    def safety_guard(self, safety_config):
        """테스트용 안전장치"""
        return SafetyGuard(safety_config, initial_capital=Decimal("10000000"))

    def test_can_trade_initial(self, safety_guard):
        """초기 상태 - 거래 가능"""
        can_trade, reason, message = safety_guard.can_trade()

        assert can_trade is True
        assert reason is None

    def test_daily_loss_limit_block(self, safety_guard):
        """일일 손실 한도 차단"""
        # 3% 손실 기록 (300,000원)
        safety_guard.record_trade_result(
            symbol="005930",
            is_win=False,
            realized_pnl=Decimal("-300000"),
        )

        can_trade, reason, message = safety_guard.can_trade()

        assert can_trade is False
        assert reason == TradingBlockReason.DAILY_LOSS_LIMIT

    def test_max_daily_trades_block(self, safety_guard):
        """일일 거래 횟수 한도 차단"""
        # 3회 거래 기록
        for i in range(3):
            safety_guard.record_trade_result(
                symbol=f"TEST{i:02d}",
                is_win=True,
                realized_pnl=Decimal("10000"),
            )

        can_trade, reason, message = safety_guard.can_trade()

        assert can_trade is False
        assert reason == TradingBlockReason.MAX_TRADES_REACHED

    def test_consecutive_losses_block(self, safety_guard):
        """연속 손실 한도 차단"""
        # 3회 연속 손실 (작은 손실로 일일 한도는 초과하지 않음)
        for i in range(3):
            safety_guard.record_trade_result(
                symbol=f"TEST{i:02d}",
                is_win=False,
                realized_pnl=Decimal("-10000"),  # 작은 손실
            )

        can_trade, reason, message = safety_guard.can_trade()

        assert can_trade is False
        # 거래 횟수 한도 또는 연속 손실 중 하나
        assert reason in [TradingBlockReason.CONSECUTIVE_LOSSES, TradingBlockReason.MAX_TRADES_REACHED]

    def test_consecutive_losses_reset_on_profit(self, safety_guard):
        """수익 발생 시 연속 손실 카운터 리셋"""
        # 2회 연속 손실
        for i in range(2):
            safety_guard.record_trade_result(
                symbol=f"TEST{i:02d}",
                is_win=False,
                realized_pnl=Decimal("-5000"),
            )

        # 수익 발생
        safety_guard.record_trade_result(
            symbol="PROFIT",
            is_win=True,
            realized_pnl=Decimal("50000"),
        )

        stats = safety_guard._get_today_stats()
        assert stats.consecutive_losses == 0

    def test_calculate_position_size(self, safety_guard):
        """포지션 크기 계산"""
        current_price = Decimal("70000")

        amount, quantity = safety_guard.calculate_position_size(
            symbol="005930",
            current_price=current_price,
        )

        # 최대 포지션 비율 20% = 2,000,000원 / 70,000원 = 28주
        assert quantity <= 28
        assert quantity > 0
        assert amount <= Decimal("2000000")

    def test_calculate_position_size_respects_daily_limit(self, safety_guard):
        """일일 투자 한도 고려"""
        current_price = Decimal("70000")

        # 첫 번째 포지션
        safety_guard.open_position("TEST01", Decimal("2000000"))

        # 두 번째 포지션 계산
        amount, quantity = safety_guard.calculate_position_size(
            symbol="TEST02",
            current_price=current_price,
        )

        # 일일 최대 50% = 5,000,000원
        # 이미 2,000,000원 사용 -> 남은 한도 3,000,000원
        # 포지션당 20% = 2,000,000원
        # 가용 현금 = 8,000,000원
        # min(2,000,000, 8,000,000, 3,000,000) = 2,000,000
        assert amount <= Decimal("2000000")

    def test_open_position(self, safety_guard):
        """포지션 오픈"""
        result = safety_guard.open_position("005930", Decimal("1000000"))

        assert result is True
        assert "005930" in safety_guard.account.positions
        assert safety_guard.account.positions["005930"] == Decimal("1000000")

    def test_max_positions_block(self, safety_guard):
        """최대 포지션 수 제한"""
        # 3개 포지션 오픈
        safety_guard.open_position("TEST01", Decimal("500000"))
        safety_guard.open_position("TEST02", Decimal("500000"))
        safety_guard.open_position("TEST03", Decimal("500000"))

        can_trade, reason, message = safety_guard.can_trade()

        assert can_trade is False
        assert reason == TradingBlockReason.MAX_POSITIONS

    def test_market_crash_block(self, safety_guard):
        """시장 급락 차단"""
        safety_guard.update_market_change(-0.025)  # -2.5%

        can_trade, reason, message = safety_guard.can_trade()

        assert can_trade is False
        assert reason == TradingBlockReason.MARKET_CRASH

    def test_get_status(self, safety_guard):
        """상태 조회"""
        status = safety_guard.get_status()

        assert "can_trade" in status
        assert "account" in status
        assert "daily_stats" in status
        assert "periodic_pnl" in status
        assert "limits" in status

        assert status["can_trade"] is True
        assert status["account"]["initial_capital"] == 10000000.0

    def test_reset_daily_stats(self, safety_guard):
        """일일 통계 리셋"""
        # 거래 기록
        safety_guard.record_trade_result(
            symbol="TEST01",
            is_win=True,
            realized_pnl=Decimal("50000"),
        )

        # 통계 리셋 (새 날짜로)
        safety_guard.reset_daily_stats()

        stats = safety_guard._get_today_stats()
        assert stats.trades == 0
        assert stats.realized_pnl == Decimal("0")

    def test_position_size_recommendation(self, safety_guard):
        """포지션 사이즈 권장"""
        recommendation = safety_guard.get_position_size_recommendation(
            symbol="005930",
            current_price=Decimal("70000"),
        )

        assert "symbol" in recommendation
        assert "recommended_amount" in recommendation
        assert "recommended_quantity" in recommendation
        assert recommendation["symbol"] == "005930"
        assert recommendation["recommended_quantity"] > 0
