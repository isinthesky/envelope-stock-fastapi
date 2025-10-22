# -*- coding: utf-8 -*-
"""
BacktestOrderManager 테스트
"""

from datetime import datetime
from decimal import Decimal

import pytest

from src.application.domain.backtest.dto import BacktestConfigDTO, TradeDTO
from src.application.domain.backtest.order_manager import BacktestOrderManager


class TestBacktestOrderManager:
    """주문 관리자 테스트"""

    def setup_method(self):
        """테스트 초기화"""
        self.config = BacktestConfigDTO(
            initial_capital=Decimal("10000000"),
            commission_rate=0.00015,  # 0.015%
            tax_rate=0.0023,  # 0.23%
            slippage_rate=0.0005,  # 0.05%
            use_commission=True,
            use_tax=True,
            use_slippage=True
        )
        self.manager = BacktestOrderManager(self.config)

    def test_execute_buy_order_with_fees(self):
        """매수 주문 실행 (수수료 포함) 테스트"""
        trade, total_cost = self.manager.execute_buy_order(
            symbol="005930",
            price=Decimal("70000"),
            quantity=10,
            date=datetime(2024, 1, 1)
        )

        # 슬리피지 적용: 70000 * 1.0005 = 70035
        expected_price = Decimal("70000") * Decimal("1.0005")
        assert trade.entry_price == expected_price

        # 매수 금액: 70035 * 10 = 700350
        purchase_amount = expected_price * 10

        # 수수료: 700350 * 0.00015 = 105.0525
        expected_commission = purchase_amount * Decimal("0.00015")

        # 총 비용: 700350 + 105.0525 = 700455.0525
        expected_total_cost = purchase_amount + expected_commission

        assert trade.commission == expected_commission
        assert total_cost == expected_total_cost
        assert trade.tax == Decimal("0")  # 매수 시 세금 없음
        assert trade.trade_type == "buy"

    def test_execute_buy_order_without_fees(self):
        """매수 주문 실행 (수수료 미포함) 테스트"""
        config_no_fees = BacktestConfigDTO(
            initial_capital=Decimal("10000000"),
            commission_rate=0.00015,
            tax_rate=0.0023,
            slippage_rate=0.0005,
            use_commission=False,
            use_tax=False,
            use_slippage=False
        )
        manager = BacktestOrderManager(config_no_fees)

        trade, total_cost = manager.execute_buy_order(
            symbol="005930",
            price=Decimal("70000"),
            quantity=10,
            date=datetime(2024, 1, 1)
        )

        # 슬리피지 미적용
        assert trade.entry_price == Decimal("70000")

        # 수수료 미적용
        assert trade.commission == Decimal("0")

        # 총 비용 = 매수 금액
        assert total_cost == Decimal("700000")

    def test_execute_sell_order_with_fees(self):
        """매도 주문 실행 (수수료/세금 포함) 테스트"""
        # 먼저 매수
        buy_trade, _ = self.manager.execute_buy_order(
            symbol="005930",
            price=Decimal("70000"),
            quantity=10,
            date=datetime(2024, 1, 1)
        )

        # 매도 (10% 상승)
        sell_trade, net_proceeds = self.manager.execute_sell_order(
            trade=buy_trade,
            price=Decimal("77000"),
            date=datetime(2024, 2, 1),
            exit_reason="signal"
        )

        # 슬리피지 적용: 77000 * 0.9995 = 76961.5
        expected_sell_price = Decimal("77000") * Decimal("0.9995")
        assert sell_trade.exit_price == expected_sell_price

        # 매도 금액: 76961.5 * 10 = 769615
        sell_amount = expected_sell_price * 10

        # 수수료: 769615 * 0.00015
        sell_commission = sell_amount * Decimal("0.00015")

        # 세금: 769615 * 0.0023
        tax = sell_amount * Decimal("0.0023")

        # 순 수익 = 매도 금액 - 수수료 - 세금
        expected_net_proceeds = sell_amount - sell_commission - tax

        assert sell_trade.commission == buy_trade.commission + sell_commission
        assert sell_trade.tax == tax
        assert net_proceeds == expected_net_proceeds
        assert sell_trade.exit_reason == "signal"
        assert sell_trade.holding_days == 31  # 2024년 1월 1일 ~ 2월 1일

    def test_profit_calculation(self):
        """손익 계산 테스트"""
        # 매수
        buy_trade, buy_cost = self.manager.execute_buy_order(
            symbol="005930",
            price=Decimal("70000"),
            quantity=10,
            date=datetime(2024, 1, 1)
        )

        # 매도 (5% 손실)
        sell_trade, net_proceeds = self.manager.execute_sell_order(
            trade=buy_trade,
            price=Decimal("66500"),
            date=datetime(2024, 1, 15),
            exit_reason="stop_loss"
        )

        # 손실 발생 확인
        assert sell_trade.profit < 0
        assert sell_trade.profit_rate < 0
        assert sell_trade.exit_reason == "stop_loss"

    def test_calculate_position_size(self):
        """포지션 크기 계산 테스트"""
        available_cash = Decimal("1000000")
        allocation_ratio = 0.1  # 10%
        current_price = Decimal("70000")

        quantity = self.manager.calculate_position_size(
            available_cash, allocation_ratio, current_price
        )

        # 할당 금액: 1000000 * 0.1 = 100000
        # 수수료 고려: 100000 / 1.00015 = 99985.0
        # 수량: 99985 / 70000 = 1.42... -> 1주
        assert quantity == 1

    def test_calculate_position_size_with_larger_budget(self):
        """큰 예산으로 포지션 크기 계산 테스트"""
        available_cash = Decimal("10000000")
        allocation_ratio = 0.5  # 50%
        current_price = Decimal("70000")

        quantity = self.manager.calculate_position_size(
            available_cash, allocation_ratio, current_price
        )

        # 할당 금액: 10000000 * 0.5 = 5000000
        # 수수료 고려: 5000000 / 1.00015 = 4999250.28
        # 수량: 4999250 / 70000 = 71.41... -> 71주
        assert quantity == 71

    def test_calculate_position_size_zero_price(self):
        """가격이 0일 때 포지션 크기 계산 테스트"""
        quantity = self.manager.calculate_position_size(
            Decimal("1000000"), 0.1, Decimal("0")
        )
        assert quantity == 0

    def test_can_afford_true(self):
        """매수 가능 여부 확인 (가능) 테스트"""
        can_buy = self.manager.can_afford(
            available_cash=Decimal("1000000"),
            price=Decimal("70000"),
            quantity=10
        )
        # 비용: 70000 * 10 = 700000
        # 수수료: 700000 * 0.00015 = 105
        # 총: 700105 < 1000000
        assert can_buy is True

    def test_can_afford_false(self):
        """매수 가능 여부 확인 (불가) 테스트"""
        can_buy = self.manager.can_afford(
            available_cash=Decimal("100000"),
            price=Decimal("70000"),
            quantity=10
        )
        # 비용: 70000 * 10 = 700000
        # 수수료: 700000 * 0.00015 = 105
        # 총: 700105 > 100000
        assert can_buy is False

    def test_trade_id_increments(self):
        """거래 ID 증가 테스트"""
        trade1, _ = self.manager.execute_buy_order(
            "005930", Decimal("70000"), 10, datetime(2024, 1, 1)
        )
        trade2, _ = self.manager.execute_buy_order(
            "000660", Decimal("100000"), 5, datetime(2024, 1, 2)
        )

        assert trade1.trade_id == 1
        assert trade2.trade_id == 2

    def test_exit_reasons(self):
        """청산 이유 테스트"""
        buy_trade, _ = self.manager.execute_buy_order(
            "005930", Decimal("70000"), 10, datetime(2024, 1, 1)
        )

        # 시그널 청산
        signal_trade, _ = self.manager.execute_sell_order(
            buy_trade, Decimal("75000"), datetime(2024, 1, 10), "signal"
        )
        assert signal_trade.exit_reason == "signal"

        # 손절 청산
        buy_trade2, _ = self.manager.execute_buy_order(
            "005930", Decimal("70000"), 10, datetime(2024, 1, 1)
        )
        stop_loss_trade, _ = self.manager.execute_sell_order(
            buy_trade2, Decimal("67000"), datetime(2024, 1, 5), "stop_loss"
        )
        assert stop_loss_trade.exit_reason == "stop_loss"

        # 익절 청산
        buy_trade3, _ = self.manager.execute_buy_order(
            "005930", Decimal("70000"), 10, datetime(2024, 1, 1)
        )
        take_profit_trade, _ = self.manager.execute_sell_order(
            buy_trade3, Decimal("80000"), datetime(2024, 1, 8), "take_profit"
        )
        assert take_profit_trade.exit_reason == "take_profit"
