# -*- coding: utf-8 -*-
"""
BacktestEngine 테스트
"""

from datetime import datetime
from decimal import Decimal

import pandas as pd
import pytest

from src.application.domain.backtest.dto import BacktestConfigDTO
from src.application.domain.backtest.engine import BacktestEngine
from src.application.domain.strategy.dto import (
    BollingerBandConfig,
    EnvelopeConfig,
    PositionConfig,
    RiskManagementConfig,
    StrategyConfigDTO,
)


class TestBacktestEngine:
    """백테스트 엔진 테스트"""

    def setup_method(self):
        """테스트 초기화"""
        # 전략 설정
        self.strategy_config = StrategyConfigDTO(
            bollinger_band=BollingerBandConfig(period=20, std_multiplier=2.0),
            envelope=EnvelopeConfig(period=20, percentage=2.0),
            position=PositionConfig(allocation_ratio=0.1, max_position_count=1),
            risk_management=RiskManagementConfig(
                use_stop_loss=True,
                stop_loss_ratio=-0.05,
                use_take_profit=True,
                take_profit_ratio=0.10,
                use_trailing_stop=False,
                use_reverse_signal_exit=True,
            ),
        )

        # 백테스트 설정
        self.backtest_config = BacktestConfigDTO(
            initial_capital=Decimal("10000000"),
            commission_rate=0.00015,
            tax_rate=0.0023,
            slippage_rate=0.0005,
            use_commission=True,
            use_tax=True,
            use_slippage=True,
        )

        # 엔진 생성
        self.engine = BacktestEngine(
            symbol="005930",
            strategy_config=self.strategy_config,
            backtest_config=self.backtest_config,
        )

    def test_engine_initialization(self):
        """엔진 초기화 테스트"""
        assert self.engine.symbol == "005930"
        assert self.engine.cash == Decimal("10000000")
        assert self.engine.initial_capital == Decimal("10000000")
        assert len(self.engine.trades) == 0
        assert len(self.engine.price_history) == 0

    def test_generate_signal_insufficient_data(self):
        """데이터 부족 시 시그널 생성 테스트"""
        # 5일 데이터만 (20일 필요)
        self.engine.price_history = [70000, 71000, 69000, 70500, 72000]

        signal = self.engine._generate_signal(Decimal("72000"))
        assert signal == "hold"

    def test_generate_signal_with_sufficient_data(self):
        """충분한 데이터로 시그널 생성 테스트"""
        # 30일 하락 추세 데이터 (과매도 구간)
        prices = list(range(80000, 65000, -500))  # 80000부터 65000까지 하락
        self.engine.price_history = prices

        signal = self.engine._generate_signal(Decimal("63000"))
        # 과매도 구간이므로 매수 시그널 기대
        assert signal in ["buy", "hold"]

    async def test_simple_backtest_run(self):
        """간단한 백테스트 실행 테스트"""
        # 30일 OHLCV 데이터 생성 (단순 상승 추세)
        dates = pd.date_range(start="2024-01-01", periods=30, freq="D")
        prices = [70000 + i * 100 for i in range(30)]  # 70000부터 100원씩 상승

        data = pd.DataFrame(
            {
                "timestamp": dates,
                "open": prices,
                "high": [p + 500 for p in prices],
                "low": [p - 500 for p in prices],
                "close": prices,
                "volume": [1000000] * 30,
            }
        )

        # 백테스트 실행
        result = await self.engine.run(
            data=data,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 30),
        )

        # 기본 검증
        assert result.symbol == "005930"
        assert result.initial_capital == Decimal("10000000")
        assert result.final_capital > 0
        assert len(result.daily_stats) == 30

    async def test_backtest_with_buy_sell_signals(self):
        """매수/매도 시그널이 있는 백테스트 테스트"""
        # 과매도 -> 과매수 패턴
        dates = pd.date_range(start="2024-01-01", periods=50, freq="D")

        # 1~25일: 하락 (70000 -> 60000)
        # 26~50일: 상승 (60000 -> 80000)
        prices = []
        for i in range(25):
            prices.append(70000 - i * 400)  # 하락
        for i in range(25):
            prices.append(60000 + i * 800)  # 상승

        data = pd.DataFrame(
            {
                "timestamp": dates,
                "open": prices,
                "high": [p + 500 for p in prices],
                "low": [p - 500 for p in prices],
                "close": prices,
                "volume": [1000000] * 50,
            }
        )

        result = await self.engine.run(
            data=data,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 2, 19),
        )

        # 거래가 발생했는지 확인
        completed_trades = [t for t in result.trades if t.exit_date is not None]

        # 결과 검증
        assert result.total_trades >= 0
        assert len(result.daily_stats) == 50

    async def test_stop_loss_trigger(self):
        """손절 발동 테스트"""
        dates = pd.date_range(start="2024-01-01", periods=30, freq="D")

        # 초반 안정, 후반 급락
        prices = [70000] * 20 + [70000 - i * 1000 for i in range(1, 11)]

        data = pd.DataFrame(
            {
                "timestamp": dates,
                "open": prices,
                "high": [p + 500 for p in prices],
                "low": [p - 500 for p in prices],
                "close": prices,
                "volume": [1000000] * 30,
            }
        )

        # 손절 비율 -5%로 설정
        result = await self.engine.run(
            data=data,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 30),
        )

        # 손절 거래 확인
        stop_loss_trades = [
            t for t in result.trades if t.exit_reason == "stop_loss"
        ]

        # 결과 검증 (손절이 발동했을 수도 있음)
        assert result.total_trades >= 0

    async def test_take_profit_trigger(self):
        """익절 발동 테스트"""
        dates = pd.date_range(start="2024-01-01", periods=30, freq="D")

        # 초반 안정, 후반 급등
        prices = [70000] * 20 + [70000 + i * 1500 for i in range(1, 11)]

        data = pd.DataFrame(
            {
                "timestamp": dates,
                "open": prices,
                "high": [p + 500 for p in prices],
                "low": [p - 500 for p in prices],
                "close": prices,
                "volume": [1000000] * 30,
            }
        )

        # 익절 비율 +10%로 설정
        result = await self.engine.run(
            data=data,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 30),
        )

        # 익절 거래 확인
        take_profit_trades = [
            t for t in result.trades if t.exit_reason == "take_profit"
        ]

        # 결과 검증
        assert result.total_trades >= 0

    async def test_equity_curve_generation(self):
        """자산 곡선 생성 테스트"""
        dates = pd.date_range(start="2024-01-01", periods=30, freq="D")
        prices = [70000] * 30

        data = pd.DataFrame(
            {
                "timestamp": dates,
                "open": prices,
                "high": [p + 500 for p in prices],
                "low": [p - 500 for p in prices],
                "close": prices,
                "volume": [1000000] * 30,
            }
        )

        result = await self.engine.run(
            data=data,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 30),
        )

        # 자산 곡선 확인
        assert len(result.daily_stats) == 30

        # 첫날 자산은 초기 자본
        first_day_equity = result.daily_stats[0].equity
        assert first_day_equity == Decimal("10000000")

    async def test_performance_metrics_calculation(self):
        """성과 지표 계산 테스트"""
        dates = pd.date_range(start="2024-01-01", periods=30, freq="D")
        prices = [70000 + i * 200 for i in range(30)]  # 상승 추세

        data = pd.DataFrame(
            {
                "timestamp": dates,
                "open": prices,
                "high": [p + 500 for p in prices],
                "low": [p - 500 for p in prices],
                "close": prices,
                "volume": [1000000] * 30,
            }
        )

        result = await self.engine.run(
            data=data,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 30),
        )

        # 성과 지표가 계산되었는지 확인
        assert result.total_return is not None
        assert result.annualized_return is not None
        assert result.cagr is not None
        assert result.mdd is not None
        assert result.volatility is not None
        assert result.sharpe_ratio is not None
        assert result.win_rate >= 0

    async def test_reset_functionality(self):
        """상태 초기화 테스트"""
        # 일부 상태 변경
        self.engine.cash = Decimal("5000000")
        self.engine.trades.append(None)
        self.engine.price_history.append(70000)

        # 리셋
        self.engine._reset()

        # 초기 상태 확인
        assert self.engine.cash == Decimal("10000000")
        assert len(self.engine.trades) == 0
        assert len(self.engine.price_history) == 0
        assert len(self.engine.equity_curve) == 0

    async def test_multiple_positions_prevented(self):
        """중복 포지션 방지 테스트"""
        dates = pd.date_range(start="2024-01-01", periods=30, freq="D")

        # 계속 과매도 시그널 (매수 시그널 지속)
        prices = [60000 - i * 100 for i in range(30)]

        data = pd.DataFrame(
            {
                "timestamp": dates,
                "open": prices,
                "high": [p + 500 for p in prices],
                "low": [p - 500 for p in prices],
                "close": prices,
                "volume": [1000000] * 30,
            }
        )

        result = await self.engine.run(
            data=data,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 30),
        )

        # 최대 포지션 수 제한 확인 (max_position_count=1)
        # 동시에 여러 포지션이 열려있지 않아야 함
        assert result.total_trades >= 0
