# -*- coding: utf-8 -*-
"""
골든크로스 전략 테스트 - _determine_gc_state 메서드 검증
"""

import pytest

from src.application.domain.strategy.buy_strategy_service import BuyStrategyService


class TestDetermineGCState:
    """_determine_gc_state 메서드 테스트"""

    def test_not_gc_when_inactive(self):
        """골든크로스 비활성 시 NOT_GC 반환"""
        result = BuyStrategyService._determine_gc_state(
            is_gc_active=False,
            stoch_k=20.0,
            stoch_threshold=30.0,
        )
        assert result == "NOT_GC"

    def test_gc_active_when_stoch_high(self):
        """Stochastic이 높을 때 GC_ACTIVE 반환"""
        result = BuyStrategyService._determine_gc_state(
            is_gc_active=True,
            stoch_k=60.0,
            stoch_threshold=30.0,
        )
        assert result == "GC_ACTIVE"

    def test_waiting_for_pullback_when_stoch_middle(self):
        """Stochastic 중간 구간에서 WAITING_FOR_PULLBACK 반환"""
        result = BuyStrategyService._determine_gc_state(
            is_gc_active=True,
            stoch_k=40.0,
            stoch_threshold=30.0,
        )
        assert result == "WAITING_FOR_PULLBACK"

    def test_optimal_buy_all_conditions_met(self):
        """모든 조건 충족 시 OPTIMAL_BUY 반환"""
        result = BuyStrategyService._determine_gc_state(
            is_gc_active=True,
            stoch_k=25.0,  # < deep_oversold_threshold(30)
            stoch_threshold=30.0,
            stoch_d=30.0,  # K > D 조건은 require_momentum_turn=False라 무시됨
            ma_gap_ratio=5.0,  # 0 <= gap <= 8
            deep_oversold_threshold=30.0,
            require_momentum_turn=False,
            min_ma_gap=0.0,
            max_ma_gap=8.0,
        )
        assert result == "OPTIMAL_BUY"

    def test_optimal_buy_with_momentum_turn_required(self):
        """K>D 조건 필수일 때 모든 조건 충족 시 OPTIMAL_BUY"""
        result = BuyStrategyService._determine_gc_state(
            is_gc_active=True,
            stoch_k=25.0,
            stoch_threshold=30.0,
            stoch_d=20.0,  # K(25) > D(20), 조건 충족
            ma_gap_ratio=5.0,
            deep_oversold_threshold=30.0,
            require_momentum_turn=True,  # K>D 필수
            min_ma_gap=0.0,
            max_ma_gap=8.0,
        )
        assert result == "OPTIMAL_BUY"

    def test_buy_interest_two_conditions_met(self):
        """2개 조건 충족 시 BUY_INTEREST 반환"""
        # is_deep_oversold=True, is_momentum_turning=True (require=False), is_healthy_trend=False
        result = BuyStrategyService._determine_gc_state(
            is_gc_active=True,
            stoch_k=25.0,  # < 30, 조건 충족
            stoch_threshold=30.0,
            stoch_d=30.0,
            ma_gap_ratio=15.0,  # > 8, MA갭 조건 미충족
            deep_oversold_threshold=30.0,
            require_momentum_turn=False,
            min_ma_gap=0.0,
            max_ma_gap=8.0,
        )
        # is_deep_oversold=True, is_momentum_turning=True, is_healthy_trend=False
        # 2개 조건 충족 -> BUY_INTEREST
        assert result == "BUY_INTEREST"

    def test_buy_interest_with_momentum_turn_failed(self):
        """K>D 필수일 때 K<D이면 2개 조건으로 BUY_INTEREST"""
        result = BuyStrategyService._determine_gc_state(
            is_gc_active=True,
            stoch_k=25.0,  # < 30, 조건 충족
            stoch_threshold=30.0,
            stoch_d=30.0,  # K(25) < D(30), 조건 미충족
            ma_gap_ratio=5.0,  # 조건 충족
            deep_oversold_threshold=30.0,
            require_momentum_turn=True,  # K>D 필수
            min_ma_gap=0.0,
            max_ma_gap=8.0,
        )
        # is_deep_oversold=True, is_momentum_turning=False, is_healthy_trend=True
        # 2개 조건 충족 -> BUY_INTEREST
        assert result == "BUY_INTEREST"

    def test_ready_to_buy_one_condition_met(self):
        """1개 조건만 충족 시 READY_TO_BUY 반환"""
        result = BuyStrategyService._determine_gc_state(
            is_gc_active=True,
            stoch_k=28.0,  # < 30, 과매도 구간이지만
            stoch_threshold=30.0,
            stoch_d=20.0,
            ma_gap_ratio=15.0,  # > 8, MA갭 조건 미충족
            deep_oversold_threshold=25.0,  # K(28) > 25, deep oversold 미충족
            require_momentum_turn=False,
            min_ma_gap=0.0,
            max_ma_gap=8.0,
        )
        # is_deep_oversold=False, is_momentum_turning=True, is_healthy_trend=False
        # 1개 조건 충족 -> READY_TO_BUY
        assert result == "READY_TO_BUY"

    def test_relaxed_conditions_vs_strict(self):
        """완화된 조건 vs 엄격한 조건 비교"""
        # 엄격한 조건 (기존 값)
        strict_result = BuyStrategyService._determine_gc_state(
            is_gc_active=True,
            stoch_k=27.0,
            stoch_threshold=30.0,
            stoch_d=30.0,
            ma_gap_ratio=6.0,
            deep_oversold_threshold=25.0,  # 엄격
            require_momentum_turn=True,  # K>D 필수
            min_ma_gap=0.0,
            max_ma_gap=5.0,  # 엄격
        )

        # 완화된 조건 (새 기본값)
        relaxed_result = BuyStrategyService._determine_gc_state(
            is_gc_active=True,
            stoch_k=27.0,
            stoch_threshold=30.0,
            stoch_d=30.0,
            ma_gap_ratio=6.0,
            deep_oversold_threshold=30.0,  # 완화
            require_momentum_turn=False,  # K>D 선택적
            min_ma_gap=0.0,
            max_ma_gap=8.0,  # 완화
        )

        # 엄격한 조건: K(27) > 25 (미충족), K(27) < D(30) (미충족), gap(6) > 5 (미충족)
        # -> READY_TO_BUY
        assert strict_result == "READY_TO_BUY"

        # 완화된 조건: K(27) < 30 (충족), K>D 무시 (충족), gap(6) < 8 (충족)
        # -> OPTIMAL_BUY
        assert relaxed_result == "OPTIMAL_BUY"

    def test_default_parameters_backward_compatible(self):
        """기본 파라미터로 호출 시 하위 호환성 테스트"""
        # 기존 호출 방식 (신규 파라미터 없이)
        result = BuyStrategyService._determine_gc_state(
            is_gc_active=True,
            stoch_k=25.0,
            stoch_threshold=30.0,
            stoch_d=20.0,
            ma_gap_ratio=5.0,
        )
        # 기본값: deep_oversold=30, require_momentum=False, max_ma_gap=8
        # 모든 조건 충족 -> OPTIMAL_BUY
        assert result == "OPTIMAL_BUY"

    def test_ma_gap_out_of_range_negative(self):
        """MA갭이 음수일 때 (MA55 < MA165인 상태에서 GC 활성화된 특수 케이스)"""
        result = BuyStrategyService._determine_gc_state(
            is_gc_active=True,
            stoch_k=25.0,
            stoch_threshold=30.0,
            stoch_d=30.0,
            ma_gap_ratio=-2.0,  # 음수 갭
            deep_oversold_threshold=30.0,
            require_momentum_turn=False,
            min_ma_gap=0.0,
            max_ma_gap=8.0,
        )
        # is_healthy_trend = 0 <= -2 <= 8 -> False
        # 2개 조건 충족 -> BUY_INTEREST
        assert result == "BUY_INTEREST"
