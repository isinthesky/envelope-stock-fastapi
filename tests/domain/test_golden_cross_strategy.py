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

    def test_oversold_is_ready_not_optimal(self):
        """과매도 자체는 매수 적기가 아니라 매수 준비 상태"""
        result = BuyStrategyService._determine_gc_state(
            is_gc_active=True,
            stoch_k=25.0,
            stoch_threshold=30.0,
            stoch_d=30.0,
            ma_gap_ratio=5.0,
            deep_oversold_threshold=30.0,
            require_momentum_turn=False,
            min_ma_gap=0.0,
            max_ma_gap=8.0,
        )
        assert result == "READY_TO_BUY"

    def test_optimal_buy_after_pullback_recovery(self):
        """최근 과매도 이후 K 회복 + K>D + 건강한 MA 갭이면 OPTIMAL_BUY"""
        result = BuyStrategyService._determine_gc_state(
            is_gc_active=True,
            stoch_k=35.0,
            stoch_threshold=30.0,
            stoch_d=25.0,
            ma_gap_ratio=5.0,
            prev_stoch_k=25.0,
            recent_oversold=True,
            require_momentum_turn=True,
            min_ma_gap=0.0,
            max_ma_gap=8.0,
        )
        assert result == "OPTIMAL_BUY"

    def test_no_optimal_without_recent_oversold(self):
        """최근 과매도 이력이 없으면 중간 구간은 눌림목 대기"""
        result = BuyStrategyService._determine_gc_state(
            is_gc_active=True,
            stoch_k=35.0,
            stoch_threshold=30.0,
            stoch_d=25.0,
            ma_gap_ratio=5.0,
            prev_stoch_k=25.0,
            recent_oversold=False,
            min_ma_gap=0.0,
            max_ma_gap=8.0,
        )
        assert result == "WAITING_FOR_PULLBACK"

    def test_buy_interest_with_momentum_turn_failed(self):
        """회복 중이지만 K>D 조건이 미충족이면 BUY_INTEREST"""
        result = BuyStrategyService._determine_gc_state(
            is_gc_active=True,
            stoch_k=35.0,
            stoch_threshold=30.0,
            stoch_d=40.0,
            ma_gap_ratio=5.0,
            prev_stoch_k=25.0,
            recent_oversold=True,
            require_momentum_turn=True,
            min_ma_gap=0.0,
            max_ma_gap=8.0,
        )
        assert result == "BUY_INTEREST"

    def test_falling_strong_recovery_is_not_optimal_buy(self):
        """강한 회복 구간이어도 K가 하락 중이면 OPTIMAL_BUY가 아님"""
        result = BuyStrategyService._determine_gc_state(
            is_gc_active=True,
            stoch_k=35.0,
            stoch_threshold=30.0,
            stoch_d=30.0,
            ma_gap_ratio=5.0,
            prev_stoch_k=45.0,
            recent_oversold=True,
            require_momentum_turn=True,
            min_ma_gap=0.0,
            max_ma_gap=8.0,
        )
        assert result == "BUY_INTEREST"

    def test_ready_to_buy_when_still_oversold(self):
        """아직 과매도 구간이면 READY_TO_BUY 반환"""
        result = BuyStrategyService._determine_gc_state(
            is_gc_active=True,
            stoch_k=28.0,
            stoch_threshold=30.0,
            stoch_d=20.0,
            ma_gap_ratio=15.0,
            deep_oversold_threshold=25.0,
            require_momentum_turn=False,
            min_ma_gap=0.0,
            max_ma_gap=8.0,
        )
        assert result == "READY_TO_BUY"

    def test_legacy_positional_arguments_keep_meaning(self):
        """기존 positional 호출에서 deep/require/gap 인자 의미가 보존됨"""
        result = BuyStrategyService._determine_gc_state(
            True,
            35.0,
            30.0,
            25.0,
            5.0,
            30.0,
            True,
            0.0,
            8.0,
            prev_stoch_k=25.0,
            recent_oversold=True,
        )
        assert result == "OPTIMAL_BUY"

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

        # 회복 돌파 조건
        relaxed_result = BuyStrategyService._determine_gc_state(
            is_gc_active=True,
            stoch_k=35.0,
            stoch_threshold=30.0,
            stoch_d=30.0,
            ma_gap_ratio=6.0,
            prev_stoch_k=27.0,
            recent_oversold=True,
            require_momentum_turn=True,
            max_ma_gap=8.0,  # 완화
        )

        # 엄격한 조건: 아직 과매도 구간이므로 READY_TO_BUY
        assert strict_result == "READY_TO_BUY"

        # 회복 돌파: 최근 과매도 이후 K 상승, K>D, gap(6) < 8
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
        assert result == "READY_TO_BUY"

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
        assert result == "READY_TO_BUY"
