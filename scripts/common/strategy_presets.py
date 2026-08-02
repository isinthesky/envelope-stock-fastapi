# -*- coding: utf-8 -*-
"""
Strategy Presets - 전략 설정 프리셋 모듈

자주 사용되는 전략 설정을 미리 정의해 둡니다.
레거시 볼린저+엔벨로프 평균회귀 프리셋은 제거되었다(생성기 폐기와 함께).
"""

from decimal import Decimal

from src.application.domain.backtest.dto import BacktestConfigDTO
from src.application.domain.strategy.dto import GoldenCrossConfigDTO


class StrategyPresets:
    """
    전략 설정 프리셋 모음

    자주 사용되는 전략 설정을 메서드로 제공합니다.
    """

    # ==================== 골든크로스 전략 ====================

    @staticmethod
    def default_golden_cross() -> GoldenCrossConfigDTO:
        """
        기본 골든크로스 전략

        - MA55 / MA165 (약 3개월 / 8개월)
        - Stochastic: 14, 3, 3
        - 손절: -5%, 익절: +10%
        """
        return GoldenCrossConfigDTO(
            short_ma_period=55,
            long_ma_period=165,
            stochastic_k=14,
            stochastic_d=3,
            stochastic_smooth=3,
            stop_loss_ratio=-0.05,
            take_profit_ratio=0.10,
            allocation_ratio=0.1,
        )

    @staticmethod
    def fast_golden_cross() -> GoldenCrossConfigDTO:
        """
        빠른 골든크로스 전략

        - MA20 / MA60 (단기)
        - 빠른 신호, 잦은 거래
        """
        return GoldenCrossConfigDTO(
            short_ma_period=20,
            long_ma_period=60,
            stochastic_k=14,
            stochastic_d=3,
            stochastic_smooth=3,
            stop_loss_ratio=-0.03,
            take_profit_ratio=0.07,
            allocation_ratio=0.08,
        )

    @staticmethod
    def slow_golden_cross() -> GoldenCrossConfigDTO:
        """
        느린 골든크로스 전략

        - MA60 / MA200 (전통적)
        - 안정적, 장기 투자
        """
        return GoldenCrossConfigDTO(
            short_ma_period=60,
            long_ma_period=200,
            stochastic_k=14,
            stochastic_d=3,
            stochastic_smooth=3,
            stop_loss_ratio=-0.07,
            take_profit_ratio=0.15,
            allocation_ratio=0.1,
        )

    # ==================== 백테스트 설정 ====================

    @staticmethod
    def default_backtest_config() -> BacktestConfigDTO:
        """
        기본 백테스트 설정

        - 초기 자본: 1,000만원
        - 거래 비용: 날짜별 백테스트 비용 스케줄
        """
        return BacktestConfigDTO(
            initial_capital=Decimal("10000000"),
            use_commission=True,
            use_tax=True,
            use_slippage=True,
        )

    @staticmethod
    def no_cost_backtest_config() -> BacktestConfigDTO:
        """
        비용 없는 백테스트 설정 (순수 전략 성과 측정용)
        """
        return BacktestConfigDTO(
            initial_capital=Decimal("10000000"),
            commission_rate=0.0,
            tax_rate=0.0,
            slippage_rate=0.0,
            use_commission=False,
            use_tax=False,
            use_slippage=False,
        )

    @staticmethod
    def high_capital_backtest_config() -> BacktestConfigDTO:
        """
        고액 투자 백테스트 설정

        - 초기 자본: 1억원
        """
        return BacktestConfigDTO(
            initial_capital=Decimal("100000000"),
            use_commission=True,
            use_tax=True,
            use_slippage=True,
        )

    # ==================== 프리셋 조회 ====================

    @classmethod
    def get_golden_cross_preset(cls, name: str) -> GoldenCrossConfigDTO:
        """
        이름으로 골든크로스 프리셋 조회

        Args:
            name: 프리셋 이름 (default, fast, slow)

        Returns:
            GoldenCrossConfigDTO: 골든크로스 설정
        """
        presets = {
            "default": cls.default_golden_cross,
            "fast": cls.fast_golden_cross,
            "slow": cls.slow_golden_cross,
        }

        if name not in presets:
            raise ValueError(f"Unknown preset: {name}. Available: {list(presets.keys())}")

        return presets[name]()

    @classmethod
    def list_presets(cls) -> dict:
        """사용 가능한 프리셋 목록"""
        return {
            "golden_cross": ["default", "fast", "slow"],
            "backtest": ["default", "no_cost", "high_capital"],
        }
