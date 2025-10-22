# -*- coding: utf-8 -*-
"""
PositionManager 테스트
"""

from datetime import datetime
from decimal import Decimal

import pytest

from src.application.domain.backtest.position_manager import Position, PositionManager


class TestPosition:
    """포지션 클래스 테스트"""

    def setup_method(self):
        """테스트 초기화"""
        self.position = Position(
            symbol="005930",
            quantity=10,
            entry_price=Decimal("70000"),
            entry_date=datetime(2024, 1, 1),
            trade_id=1
        )

    def test_position_creation(self):
        """포지션 생성 테스트"""
        assert self.position.symbol == "005930"
        assert self.position.quantity == 10
        assert self.position.entry_price == Decimal("70000")
        assert self.position.highest_price == Decimal("70000")

    def test_update_highest_price(self):
        """최고가 업데이트 테스트"""
        # 상승 시 업데이트
        self.position.update_highest_price(Decimal("75000"))
        assert self.position.highest_price == Decimal("75000")

        # 하락 시 업데이트 안 됨
        self.position.update_highest_price(Decimal("72000"))
        assert self.position.highest_price == Decimal("75000")

    def test_get_unrealized_profit(self):
        """평가 손익 계산 테스트"""
        # 수익
        profit = self.position.get_unrealized_profit(Decimal("75000"))
        assert profit == Decimal("50000")  # (75000 - 70000) * 10

        # 손실
        loss = self.position.get_unrealized_profit(Decimal("65000"))
        assert loss == Decimal("-50000")  # (65000 - 70000) * 10

    def test_get_unrealized_profit_rate(self):
        """평가 손익률 계산 테스트"""
        # 수익률
        profit_rate = self.position.get_unrealized_profit_rate(Decimal("77000"))
        assert profit_rate == pytest.approx(10.0, abs=0.01)  # (77000 - 70000) / 70000 * 100

        # 손실률
        loss_rate = self.position.get_unrealized_profit_rate(Decimal("63000"))
        assert loss_rate == pytest.approx(-10.0, abs=0.01)


class TestPositionManager:
    """포지션 관리자 테스트"""

    def setup_method(self):
        """테스트 초기화"""
        self.manager = PositionManager()

    def test_open_position(self):
        """포지션 오픈 테스트"""
        self.manager.open_position(
            symbol="005930",
            quantity=10,
            entry_price=Decimal("70000"),
            entry_date=datetime(2024, 1, 1),
            trade_id=1
        )

        assert self.manager.has_position("005930")
        assert self.manager.get_total_position_count() == 1

        position = self.manager.get_position("005930")
        assert position is not None
        assert position.quantity == 10

    def test_close_position(self):
        """포지션 청산 테스트"""
        # 포지션 오픈
        self.manager.open_position(
            symbol="005930",
            quantity=10,
            entry_price=Decimal("70000"),
            entry_date=datetime(2024, 1, 1),
            trade_id=1
        )

        # 포지션 청산
        closed_position = self.manager.close_position("005930")
        assert closed_position is not None
        assert closed_position.symbol == "005930"
        assert not self.manager.has_position("005930")

    def test_close_non_existent_position(self):
        """존재하지 않는 포지션 청산 테스트"""
        result = self.manager.close_position("999999")
        assert result is None

    def test_update_positions(self):
        """포지션 평가액 업데이트 테스트"""
        # 2개 포지션 오픈
        self.manager.open_position(
            symbol="005930",
            quantity=10,
            entry_price=Decimal("70000"),
            entry_date=datetime(2024, 1, 1),
            trade_id=1
        )
        self.manager.open_position(
            symbol="000660",
            quantity=5,
            entry_price=Decimal("100000"),
            entry_date=datetime(2024, 1, 1),
            trade_id=2
        )

        # 평가액 계산
        total_value = self.manager.update_positions({
            "005930": Decimal("75000"),  # +5000 * 10 = +50000
            "000660": Decimal("110000")  # +10000 * 5 = +50000
        })

        # 75000*10 + 110000*5 = 750000 + 550000 = 1300000
        assert total_value == Decimal("1300000")

        # 최고가 업데이트 확인
        pos1 = self.manager.get_position("005930")
        assert pos1.highest_price == Decimal("75000")

    def test_check_stop_loss(self):
        """손절 체크 테스트"""
        self.manager.open_position(
            symbol="005930",
            quantity=10,
            entry_price=Decimal("70000"),
            entry_date=datetime(2024, 1, 1),
            trade_id=1
        )

        # 손절 발동 (진입가 70000, 현재가 67000 = -4.29%)
        is_stop_loss = self.manager.check_stop_loss(
            symbol="005930",
            current_price=Decimal("67000"),
            stop_loss_ratio=-3.0  # -3%
        )
        assert is_stop_loss is True

        # 손절 미발동
        is_stop_loss = self.manager.check_stop_loss(
            symbol="005930",
            current_price=Decimal("69000"),
            stop_loss_ratio=-3.0
        )
        assert is_stop_loss is False

    def test_check_take_profit(self):
        """익절 체크 테스트"""
        self.manager.open_position(
            symbol="005930",
            quantity=10,
            entry_price=Decimal("70000"),
            entry_date=datetime(2024, 1, 1),
            trade_id=1
        )

        # 익절 발동 (진입가 70000, 현재가 74000 = +5.71%)
        is_take_profit = self.manager.check_take_profit(
            symbol="005930",
            current_price=Decimal("74000"),
            take_profit_ratio=5.0  # +5%
        )
        assert is_take_profit is True

        # 익절 미발동
        is_take_profit = self.manager.check_take_profit(
            symbol="005930",
            current_price=Decimal("72000"),
            take_profit_ratio=5.0
        )
        assert is_take_profit is False

    def test_check_trailing_stop(self):
        """Trailing Stop 체크 테스트"""
        self.manager.open_position(
            symbol="005930",
            quantity=10,
            entry_price=Decimal("70000"),
            entry_date=datetime(2024, 1, 1),
            trade_id=1
        )

        # 최고가 업데이트
        self.manager.update_positions({"005930": Decimal("80000")})
        position = self.manager.get_position("005930")
        assert position.highest_price == Decimal("80000")

        # Trailing Stop 발동 (최고가 80000, 현재가 76000 = -5%)
        is_trailing_stop = self.manager.check_trailing_stop(
            symbol="005930",
            current_price=Decimal("76000"),
            trailing_stop_ratio=0.03  # 3%
        )
        assert is_trailing_stop is True

        # Trailing Stop 미발동
        is_trailing_stop = self.manager.check_trailing_stop(
            symbol="005930",
            current_price=Decimal("78000"),
            trailing_stop_ratio=0.03
        )
        assert is_trailing_stop is False

    def test_get_all_positions(self):
        """모든 포지션 조회 테스트"""
        self.manager.open_position(
            symbol="005930",
            quantity=10,
            entry_price=Decimal("70000"),
            entry_date=datetime(2024, 1, 1),
            trade_id=1
        )
        self.manager.open_position(
            symbol="000660",
            quantity=5,
            entry_price=Decimal("100000"),
            entry_date=datetime(2024, 1, 1),
            trade_id=2
        )

        positions = self.manager.get_all_positions()
        assert len(positions) == 2
        assert "005930" in positions
        assert "000660" in positions

    def test_clear_all_positions(self):
        """모든 포지션 청산 테스트"""
        self.manager.open_position(
            symbol="005930",
            quantity=10,
            entry_price=Decimal("70000"),
            entry_date=datetime(2024, 1, 1),
            trade_id=1
        )
        self.manager.open_position(
            symbol="000660",
            quantity=5,
            entry_price=Decimal("100000"),
            entry_date=datetime(2024, 1, 1),
            trade_id=2
        )

        self.manager.clear_all_positions()
        assert self.manager.get_total_position_count() == 0
