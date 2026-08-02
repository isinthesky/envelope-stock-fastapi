# -*- coding: utf-8 -*-
"""P4 통계 테스트 — Deflated Sharpe / PBO / Bootstrap (순수 numpy)."""

import numpy as np

from src.application.domain.backtest.statistics import (
    bootstrap_mean_ci,
    bootstrap_sharpe_ci,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    norm_cdf,
    norm_ppf,
    probability_of_backtest_overfitting,
    sharpe_stats,
)


def test_norm_cdf_ppf_roundtrip():
    assert abs(norm_cdf(0.0) - 0.5) < 1e-9
    assert abs(norm_cdf(1.96) - 0.975) < 1e-3
    for p in (0.01, 0.25, 0.5, 0.75, 0.99):
        assert abs(norm_cdf(norm_ppf(p)) - p) < 1e-6


def test_sharpe_stats_basic():
    rng = np.random.default_rng(0)
    r = rng.normal(0.001, 0.01, 500)
    s = sharpe_stats(list(r))
    assert s.n_obs == 500
    assert abs(s.kurtosis - 3.0) < 0.6  # 정규 ≈ 3
    assert abs(s.skew) < 0.5


def test_expected_max_sharpe_grows_with_trials():
    trials = list(np.random.default_rng(1).normal(0.0, 0.05, 30))
    sr0_10 = expected_max_sharpe(trials, 10)
    sr0_100 = expected_max_sharpe(trials, 100)
    assert sr0_100 > sr0_10 > 0  # 시도 많을수록 우연 최대치 상승


def test_deflated_sharpe_high_for_genuine_signal():
    # 강한 양(+)의 일관된 수익 → DSR 높음
    rng = np.random.default_rng(2)
    good = list(rng.normal(0.0015, 0.008, 750))  # 일별 Sharpe ~0.19
    trials = list(rng.normal(0.0, 0.03, 20))  # 시도 분산 작음
    res = deflated_sharpe_ratio(good, trials, n_trials=20)
    assert res.deflated_sharpe > 0.9
    assert res.observed_sharpe > res.expected_max_sharpe


def test_deflated_sharpe_low_for_noise_with_many_trials():
    # 무수익 잡음 + 많은 시도(넓은 분산) → DSR 낮음(우연과 구분 불가)
    rng = np.random.default_rng(3)
    noise = list(rng.normal(0.0, 0.01, 300))
    trials = list(rng.normal(0.0, 0.15, 200))  # 넓은 시도 분산 → SR0 큼
    res = deflated_sharpe_ratio(noise, trials, n_trials=200)
    assert res.deflated_sharpe < 0.5


def test_pbo_high_for_random_matrix():
    # 설정 간 진짜 우열 없음(순수 잡음) → PBO ≈ 0.5 근방
    rng = np.random.default_rng(4)
    M = rng.normal(0.0, 1.0, (8, 6)).tolist()
    pbo = probability_of_backtest_overfitting(M, n_splits=8)
    assert 0.25 <= pbo <= 0.75


def test_pbo_low_for_robust_config():
    # 설정0이 모든 슬라이스에서 일관 우수 → PBO 낮음
    rng = np.random.default_rng(5)
    base = rng.normal(0.0, 0.3, (8, 5))
    base[:, 0] += 3.0  # config0 지배적
    pbo = probability_of_backtest_overfitting(base.tolist(), n_splits=8)
    assert pbo < 0.2


def test_bootstrap_ci_contains_point_and_orders():
    rng = np.random.default_rng(6)
    r = list(rng.normal(0.001, 0.01, 400))
    mci = bootstrap_mean_ci(r, n_boot=1000)
    assert mci.low <= mci.point <= mci.high
    sci = bootstrap_sharpe_ci(r, n_boot=1000)
    assert sci.low <= sci.point <= sci.high


def test_edge_cases_return_safe_defaults():
    assert deflated_sharpe_ratio([], [], 0).deflated_sharpe == 0.0
    assert bootstrap_mean_ci([0.1]).n_boot == 0
    import math

    assert math.isnan(probability_of_backtest_overfitting([[1.0]], 8))
