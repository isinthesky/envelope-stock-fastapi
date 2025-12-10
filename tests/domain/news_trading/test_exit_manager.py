# -*- coding: utf-8 -*-
"""
Exit Manager 유닛 테스트
"""

import pytest
from datetime import datetime, time
from decimal import Decimal

from src.application.domain.news_trading.dto import (
    ExitReason,
    ExitConditionConfigDTO,
    StagedProfitTakingConfig,
    MomentumExitConfigDTO,
    TradingStatus,
)
from src.application.domain.news_trading.exit_manager import (
    ExitManager,
    BacktestExitManager,
)


class TestExitManager:
    """ExitManager 테스트"""

    @pytest.fixture
    def exit_config(self):
        """테스트용 청산 설정"""
        return ExitConditionConfigDTO(
            stop_loss_rate=-0.07,
            staged_profit_taking=StagedProfitTakingConfig(
                first_take_profit_rate=0.05,
                first_take_profit_ratio=0.5,
                second_take_profit_rate=0.08,
            ),
            momentum_exit=MomentumExitConfigDTO(
                momentum_weakness_threshold=3,
            ),
            force_exit_time=time(10, 40),
        )

    @pytest.fixture
    def exit_manager(self, exit_config):
        """테스트용 청산 관리자"""
        return ExitManager(exit_config)

    def test_open_position(self, exit_manager):
        """포지션 오픈"""
        entry_time = datetime.now().replace(hour=9, minute=10)
        position = exit_manager.open_position(
            symbol="005930",
            name="삼성전자",
            entry_time=entry_time,
            entry_price=Decimal("70000"),
            quantity=100,
        )

        assert position.symbol == "005930"
        assert position.entry_price == Decimal("70000")
        assert position.total_quantity == 100
        assert position.remaining_quantity == 100
        assert position.first_exit_done is False

    def test_check_stop_loss(self, exit_manager):
        """손절 체크"""
        entry_time = datetime.now().replace(hour=9, minute=10)
        exit_manager.open_position(
            symbol="005930",
            name="삼성전자",
            entry_time=entry_time,
            entry_price=Decimal("70000"),
            quantity=100,
        )

        # 7% 손실 (-4900원)
        current_price = Decimal("65100")
        current_time = datetime.now().replace(hour=9, minute=30)

        signal = exit_manager.check_exit_conditions("005930", current_price, current_time)

        assert signal is not None
        assert signal.exit_reason == ExitReason.STOP_LOSS
        assert signal.quantity == 100  # 전량 청산

    def test_check_first_take_profit(self, exit_manager):
        """1차 익절 체크"""
        entry_time = datetime.now().replace(hour=9, minute=10)
        exit_manager.open_position(
            symbol="005930",
            name="삼성전자",
            entry_time=entry_time,
            entry_price=Decimal("70000"),
            quantity=100,
        )

        # 5% 수익 (+3500원)
        current_price = Decimal("73500")
        current_time = datetime.now().replace(hour=9, minute=30)

        signal = exit_manager.check_exit_conditions("005930", current_price, current_time)

        assert signal is not None
        assert signal.exit_reason == ExitReason.FIRST_PROFIT_TAKING
        assert signal.quantity == 50  # 50% 청산

    def test_check_second_take_profit(self, exit_manager):
        """2차 익절 체크"""
        entry_time = datetime.now().replace(hour=9, minute=10)
        exit_manager.open_position(
            symbol="005930",
            name="삼성전자",
            entry_time=entry_time,
            entry_price=Decimal("70000"),
            quantity=100,
        )

        # 1차 익절 실행 후
        exit_manager.execute_partial_exit(
            symbol="005930",
            exit_price=Decimal("73500"),
            exit_quantity=50,
            exit_time=datetime.now().replace(hour=9, minute=20),
            exit_reason=ExitReason.FIRST_PROFIT_TAKING,
        )

        # 8% 수익 (+5600원)
        current_price = Decimal("75600")
        current_time = datetime.now().replace(hour=9, minute=40)

        signal = exit_manager.check_exit_conditions("005930", current_price, current_time)

        assert signal is not None
        assert signal.exit_reason == ExitReason.SECOND_PROFIT_TAKING
        assert signal.quantity == 50  # 잔량 전량 청산

    def test_check_force_exit(self, exit_manager):
        """강제 청산 시간 체크"""
        entry_time = datetime.now().replace(hour=9, minute=10)
        exit_manager.open_position(
            symbol="005930",
            name="삼성전자",
            entry_time=entry_time,
            entry_price=Decimal("70000"),
            quantity=100,
        )

        # 강제 청산 시간 (10:40) 이후
        current_price = Decimal("70500")
        force_exit_datetime = datetime.now().replace(hour=10, minute=41)

        signal = exit_manager.check_exit_conditions("005930", current_price, force_exit_datetime)

        assert signal is not None
        assert signal.exit_reason == ExitReason.TIME_EXIT
        assert signal.quantity == 100

    def test_execute_partial_exit(self, exit_manager):
        """부분 청산 실행"""
        entry_time = datetime.now().replace(hour=9, minute=10)
        exit_manager.open_position(
            symbol="005930",
            name="삼성전자",
            entry_time=entry_time,
            entry_price=Decimal("70000"),
            quantity=100,
        )

        realized = exit_manager.execute_partial_exit(
            symbol="005930",
            exit_price=Decimal("73500"),
            exit_quantity=50,
            exit_time=datetime.now().replace(hour=9, minute=20),
            exit_reason=ExitReason.FIRST_PROFIT_TAKING,
        )

        position = exit_manager.get_position("005930")
        assert position.remaining_quantity == 50
        assert position.first_exit_done is True
        assert position.status == TradingStatus.PARTIALLY_CLOSED
        assert realized == Decimal("175000")  # (73500 - 70000) * 50

    def test_execute_full_exit(self, exit_manager):
        """전량 청산 실행"""
        entry_time = datetime.now().replace(hour=9, minute=10)
        exit_manager.open_position(
            symbol="005930",
            name="삼성전자",
            entry_time=entry_time,
            entry_price=Decimal("70000"),
            quantity=100,
        )

        realized = exit_manager.execute_full_exit(
            symbol="005930",
            exit_price=Decimal("75000"),
            exit_time=datetime.now().replace(hour=10, minute=40),
            exit_reason=ExitReason.TIME_EXIT,
        )

        position = exit_manager.get_position("005930")
        assert position.remaining_quantity == 0
        assert position.status == TradingStatus.CLOSED
        assert realized == Decimal("500000")  # (75000 - 70000) * 100

    def test_no_exit_conditions_met(self, exit_manager):
        """청산 조건 미충족"""
        entry_time = datetime.now().replace(hour=9, minute=10)
        exit_manager.open_position(
            symbol="005930",
            name="삼성전자",
            entry_time=entry_time,
            entry_price=Decimal("70000"),
            quantity=100,
        )

        # 수익/손실 없음
        current_price = Decimal("70000")
        current_time = datetime.now().replace(hour=9, minute=30)

        signal = exit_manager.check_exit_conditions("005930", current_price, current_time)

        assert signal is None

    def test_get_position_summary(self, exit_manager):
        """포지션 요약"""
        entry_time = datetime.now().replace(hour=9, minute=10)
        exit_manager.open_position(
            symbol="005930",
            name="삼성전자",
            entry_time=entry_time,
            entry_price=Decimal("70000"),
            quantity=100,
        )

        summary = exit_manager.get_position_summary("005930")

        assert summary is not None
        assert summary["symbol"] == "005930"
        assert summary["entry_price"] == 70000.0
        assert summary["total_quantity"] == 100


class TestBacktestExitManager:
    """BacktestExitManager 테스트"""

    @pytest.fixture
    def backtest_exit_manager(self):
        """테스트용 백테스트 청산 관리자"""
        config = ExitConditionConfigDTO(
            stop_loss_rate=-0.07,
            staged_profit_taking=StagedProfitTakingConfig(
                first_take_profit_rate=0.05,
                first_take_profit_ratio=0.5,
                second_take_profit_rate=0.08,
            ),
            force_exit_time=time(10, 40),
        )
        return BacktestExitManager(config)

    def test_check_exit_from_bar_stop_loss(self, backtest_exit_manager):
        """바 데이터에서 손절 체크"""
        entry_price = 70000

        bar = {
            "high": 69500,
            "low": 65000,  # 손절가 터치
            "close": 68000,
        }
        bar_time = datetime.now().replace(hour=9, minute=30)

        reason, exit_price = backtest_exit_manager.check_exit_from_bar(
            entry_price, bar, first_exit_done=False, bar_time=bar_time
        )

        assert reason == ExitReason.STOP_LOSS
        assert exit_price == pytest.approx(65100, rel=0.01)  # 70000 * 0.93

    def test_check_exit_from_bar_take_profit(self, backtest_exit_manager):
        """바 데이터에서 익절 체크"""
        entry_price = 70000

        bar = {
            "high": 74000,  # 1차 익절가 터치
            "low": 72500,
            "close": 73500,
        }
        bar_time = datetime.now().replace(hour=9, minute=30)

        reason, exit_price = backtest_exit_manager.check_exit_from_bar(
            entry_price, bar, first_exit_done=False, bar_time=bar_time
        )

        assert reason == ExitReason.FIRST_PROFIT_TAKING
        assert exit_price == pytest.approx(73500, rel=0.01)  # 70000 * 1.05

    def test_check_exit_from_bar_force_exit(self, backtest_exit_manager):
        """바 데이터에서 강제 청산 체크"""
        entry_price = 70000

        bar = {
            "high": 71000,
            "low": 70000,
            "close": 70300,
        }
        bar_time = datetime.now().replace(hour=10, minute=41)

        reason, exit_price = backtest_exit_manager.check_exit_from_bar(
            entry_price, bar, first_exit_done=False, bar_time=bar_time
        )

        assert reason == ExitReason.TIME_EXIT
        assert exit_price == 70300  # 종가로 청산

    def test_exit_priority_stop_loss_first(self, backtest_exit_manager):
        """청산 우선순위 - 손절 우선"""
        entry_price = 70000

        # 손절과 익절 모두 터치하는 바
        bar = {
            "high": 75000,  # 익절가 터치
            "low": 64000,  # 손절가 터치
            "close": 72000,
        }
        bar_time = datetime.now().replace(hour=9, minute=30)

        reason, exit_price = backtest_exit_manager.check_exit_from_bar(
            entry_price, bar, first_exit_done=False, bar_time=bar_time
        )

        # 손절이 우선
        assert reason == ExitReason.STOP_LOSS

    def test_no_exit_from_bar(self, backtest_exit_manager):
        """바 데이터에서 청산 조건 미충족"""
        entry_price = 70000

        bar = {
            "high": 71000,
            "low": 69500,
            "close": 70500,
        }
        bar_time = datetime.now().replace(hour=9, minute=30)

        reason, exit_price = backtest_exit_manager.check_exit_from_bar(
            entry_price, bar, first_exit_done=False, bar_time=bar_time
        )

        assert reason is None
        assert exit_price == 0

    def test_calculate_profit(self, backtest_exit_manager):
        """손익 계산"""
        result = backtest_exit_manager.calculate_profit(
            entry_price=70000,
            exit_price=73500,
            quantity=100,
            commission_rate=0.00015,
            tax_rate=0.0023,
        )

        assert "gross_profit" in result
        assert "net_profit" in result
        assert "commission" in result
        assert "tax" in result
        assert result["gross_profit"] == 350000  # (73500 - 70000) * 100
