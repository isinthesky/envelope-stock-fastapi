# -*- coding: utf-8 -*-
"""
Strategy Presets - 전략 설정 프리셋 모듈

자주 사용되는 전략 설정을 미리 정의해 둡니다.
"""

from decimal import Decimal

from src.application.domain.backtest.dto import BacktestConfigDTO
from src.application.domain.strategy.dto import (
    BollingerBandConfig,
    EnvelopeConfig,
    GoldenCrossConfigDTO,
    PositionConfig,
    RiskManagementConfig,
    StrategyConfigDTO,
)


class StrategyPresets:
    """
    전략 설정 프리셋 모음

    자주 사용되는 전략 설정을 메서드로 제공합니다.
    """

    # ==================== 볼린저 밴드 전략 ====================

    @staticmethod
    def default_bollinger() -> StrategyConfigDTO:
        """
        기본 볼린저 밴드 전략

        - BB: 20일, 2σ
        - Envelope: 20일, 2%
        - 손절: -3%, 익절: +5%
        - 역신호 청산 활성화
        """
        return StrategyConfigDTO(
            bollinger_band=BollingerBandConfig(period=20, std_multiplier=2.0),
            envelope=EnvelopeConfig(period=20, percentage=2.0),
            position=PositionConfig(allocation_ratio=0.1, max_position_count=1),
            risk_management=RiskManagementConfig(
                use_stop_loss=True,
                stop_loss_ratio=-0.03,
                use_take_profit=True,
                take_profit_ratio=0.05,
                use_trailing_stop=False,
                use_reverse_signal_exit=True,
            ),
        )

    @staticmethod
    def conservative() -> StrategyConfigDTO:
        """
        보수적 전략 (낮은 리스크)

        - BB: 20일, 2.5σ (더 넓은 밴드)
        - 손절: -2%, 익절: +3%
        - 낮은 포지션 비율
        """
        return StrategyConfigDTO(
            bollinger_band=BollingerBandConfig(period=20, std_multiplier=2.5),
            envelope=EnvelopeConfig(period=20, percentage=1.5),
            position=PositionConfig(allocation_ratio=0.05, max_position_count=1),
            risk_management=RiskManagementConfig(
                use_stop_loss=True,
                stop_loss_ratio=-0.02,
                use_take_profit=True,
                take_profit_ratio=0.03,
                use_trailing_stop=True,
                trailing_stop_ratio=0.02,
                use_reverse_signal_exit=True,
            ),
        )

    @staticmethod
    def aggressive() -> StrategyConfigDTO:
        """
        공격적 전략 (높은 수익 추구)

        - BB: 15일, 1.5σ (좁은 밴드 = 더 많은 신호)
        - 손절: -5%, 익절: +10%
        - 높은 포지션 비율
        """
        return StrategyConfigDTO(
            bollinger_band=BollingerBandConfig(period=15, std_multiplier=1.5),
            envelope=EnvelopeConfig(period=15, percentage=2.5),
            position=PositionConfig(allocation_ratio=0.2, max_position_count=1),
            risk_management=RiskManagementConfig(
                use_stop_loss=True,
                stop_loss_ratio=-0.05,
                use_take_profit=True,
                take_profit_ratio=0.10,
                use_trailing_stop=False,
                use_reverse_signal_exit=True,
            ),
        )

    @staticmethod
    def trailing_stop_focus() -> StrategyConfigDTO:
        """
        트레일링 스탑 중심 전략

        - 익절 없이 트레일링 스탑으로 수익 극대화
        - 추세 추종에 적합
        """
        return StrategyConfigDTO(
            bollinger_band=BollingerBandConfig(period=20, std_multiplier=2.0),
            envelope=EnvelopeConfig(period=20, percentage=2.0),
            position=PositionConfig(allocation_ratio=0.15, max_position_count=1),
            risk_management=RiskManagementConfig(
                use_stop_loss=True,
                stop_loss_ratio=-0.03,
                use_take_profit=False,  # 익절 비활성화
                use_trailing_stop=True,
                trailing_stop_ratio=0.03,  # 3% 트레일링
                use_reverse_signal_exit=True,
            ),
        )

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
        - 수수료: 0.015%
        - 세금: 0.23%
        - 슬리피지: 0.05%
        """
        return BacktestConfigDTO(
            initial_capital=Decimal("10000000"),
            commission_rate=0.00015,
            tax_rate=0.0023,
            slippage_rate=0.0005,
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
            commission_rate=0.00015,
            tax_rate=0.0023,
            slippage_rate=0.0005,
            use_commission=True,
            use_tax=True,
            use_slippage=True,
        )

    # ==================== 프리셋 조회 ====================

    @classmethod
    def get_strategy_preset(cls, name: str) -> StrategyConfigDTO:
        """
        이름으로 전략 프리셋 조회

        Args:
            name: 프리셋 이름 (default, conservative, aggressive, trailing)

        Returns:
            StrategyConfigDTO: 전략 설정
        """
        presets = {
            "default": cls.default_bollinger,
            "conservative": cls.conservative,
            "aggressive": cls.aggressive,
            "trailing": cls.trailing_stop_focus,
        }

        if name not in presets:
            raise ValueError(f"Unknown preset: {name}. Available: {list(presets.keys())}")

        return presets[name]()

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
            "strategy": ["default", "conservative", "aggressive", "trailing"],
            "golden_cross": ["default", "fast", "slow"],
            "backtest": ["default", "no_cost", "high_capital"],
        }
