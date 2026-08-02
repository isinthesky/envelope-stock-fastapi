# -*- coding: utf-8 -*-
"""
Backtest Overfitting Statistics (P4) — Deflated Sharpe / PBO / Bootstrap

walk-forward OOS 결과가 '우연/과적합'인지 정량화한다. scipy 비의존(순수 numpy+math).

- Deflated Sharpe Ratio (Bailey & López de Prado, 2014): N회 시도 중 최고를 골랐을
  때의 선택 편향을 보정한 Sharpe의 통계적 유의도.
- Probability of Backtest Overfitting (PBO, CSCV): IS 최적 설정이 OOS에서 중위
  이하로 추락할 확률.
- Bootstrap CI: OOS 수익 통계량의 신뢰구간.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations

import numpy as np

_EULER_MASCHERONI = 0.5772156649015329


def norm_cdf(x: float) -> float:
    """표준정규 누적분포 Φ(x) (math.erf 기반)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """표준정규 역함수 Φ⁻¹(p). Acklam 유리근사(정밀도 ~1e-9)."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    p_low = 0.02425
    p_high = 1.0 - p_low
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
        )
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
    )


@dataclass(frozen=True, slots=True)
class SharpeStats:
    sharpe: float  # per-period(일별) Sharpe
    n_obs: int
    skew: float
    kurtosis: float  # 원 첨도(정규=3)


def sharpe_stats(returns: list[float]) -> SharpeStats:
    """일별 수익 배열에서 per-period Sharpe + 적률을 계산한다."""
    r = np.asarray([x for x in returns if x == x], dtype=float)  # NaN 제거
    n = int(r.size)
    if n < 2 or r.std(ddof=1) == 0.0:
        return SharpeStats(0.0, n, 0.0, 3.0)
    mean = float(r.mean())
    sd = float(r.std(ddof=1))
    sr = mean / sd
    m = r - mean
    var = float((m**2).mean())
    if var == 0.0:
        return SharpeStats(sr, n, 0.0, 3.0)
    skew = float((m**3).mean() / var**1.5)
    kurt = float((m**4).mean() / var**2)
    return SharpeStats(sr, n, skew, kurt)


@dataclass(frozen=True, slots=True)
class DeflatedSharpeResult:
    observed_sharpe: float  # per-period
    expected_max_sharpe: float  # SR0
    deflated_sharpe: float  # DSR = Φ(...), 0~1 확률
    n_trials: int
    n_obs: int


def expected_max_sharpe(trial_sharpes: list[float], n_trials: int) -> float:
    """N회 독립 시도 시 기대 최대 Sharpe(SR0) — 선택 편향 벤치마크.

    SR0 = sqrt(Var(SR)) · [(1-γ)·Φ⁻¹(1-1/N) + γ·Φ⁻¹(1-1/(N·e))]
    """
    if n_trials < 2:
        return 0.0
    var_sr = (
        float(np.var(np.asarray(trial_sharpes, dtype=float), ddof=1))
        if len(trial_sharpes) > 1
        else 0.0
    )
    if var_sr <= 0.0:
        return 0.0
    z1 = norm_ppf(1.0 - 1.0 / n_trials)
    z2 = norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(var_sr) * ((1.0 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2)


def deflated_sharpe_ratio(
    returns: list[float],
    trial_sharpes: list[float],
    n_trials: int | None = None,
) -> DeflatedSharpeResult:
    """Deflated Sharpe Ratio.

    Args:
        returns: 선택된 전략의 OOS 일별 수익(per-period Sharpe/적률 계산용)
        trial_sharpes: 모든 시도(후보×fold)의 per-period Sharpe(SR0 분산 추정용)
        n_trials: 시도 수(기본 len(trial_sharpes))
    """
    stats = sharpe_stats(returns)
    n = n_trials if n_trials is not None else len(trial_sharpes)
    sr0 = expected_max_sharpe(trial_sharpes, n)
    sr = stats.sharpe
    denom = 1.0 - stats.skew * sr + ((stats.kurtosis - 1.0) / 4.0) * sr * sr
    if stats.n_obs < 2 or denom <= 0.0:
        dsr = 0.0
    else:
        z = (sr - sr0) * math.sqrt(stats.n_obs - 1) / math.sqrt(denom)
        dsr = norm_cdf(z)
    return DeflatedSharpeResult(
        observed_sharpe=round(sr, 6),
        expected_max_sharpe=round(sr0, 6),
        deflated_sharpe=round(dsr, 6),
        n_trials=n,
        n_obs=stats.n_obs,
    )


def probability_of_backtest_overfitting(
    perf_matrix: list[list[float]],
    n_splits: int = 8,
) -> float:
    """PBO — Combinatorially Symmetric Cross-Validation.

    Args:
        perf_matrix: shape (T_slices, N_configs). 각 (슬라이스, 설정)의 성과지표
            (예: 후보별 fold별 Sharpe). 행을 n_splits 그룹으로 나눠 절반은 IS,
            절반은 OOS로 하는 모든 대칭 조합에서 IS 최적 설정의 OOS 상대순위를 본다.

    Returns:
        PBO: IS 최적 설정이 OOS 중위 이하로 추락하는 조합 비율(0~1).
    """
    M = np.asarray(perf_matrix, dtype=float)
    if M.ndim != 2 or M.shape[0] < 2 or M.shape[1] < 2:
        return float("nan")
    T, N = M.shape
    s = min(n_splits, T)
    if s % 2 == 1:
        s -= 1
    if s < 2:
        return float("nan")
    # 행을 s개의 연속 그룹으로 분할
    groups = np.array_split(np.arange(T), s)
    logits: list[float] = []
    for is_combo in combinations(range(s), s // 2):
        is_rows = np.concatenate([groups[g] for g in is_combo])
        oos_rows = np.concatenate([groups[g] for g in range(s) if g not in is_combo])
        is_perf = M[is_rows].mean(axis=0)
        oos_perf = M[oos_rows].mean(axis=0)
        best = int(np.argmax(is_perf))
        # OOS 상대순위 ω (1=최고 … N=최저를 0~1로): 큰 성과가 순위 상위
        order = np.argsort(oos_perf)  # 오름차순
        rank = int(np.where(order == best)[0][0]) + 1  # 1..N (1=최저)
        omega = rank / (N + 1.0)  # 1에 가까울수록 OOS 우수
        omega = min(max(omega, 1e-6), 1.0 - 1e-6)
        logits.append(math.log(omega / (1.0 - omega)))
    if not logits:
        return float("nan")
    # PBO = 최적 설정이 OOS 중위 이하(logit<=0)인 비율
    return float(np.mean([1.0 if lam <= 0.0 else 0.0 for lam in logits]))


@dataclass(frozen=True, slots=True)
class BootstrapCI:
    point: float
    low: float
    high: float
    n_boot: int


def bootstrap_mean_ci(
    returns: list[float],
    n_boot: int = 2000,
    ci: float = 0.95,
    seed: int = 12345,
) -> BootstrapCI:
    """일별 수익 평균의 부트스트랩 신뢰구간(단순 재표집)."""
    r = np.asarray([x for x in returns if x == x], dtype=float)
    if r.size < 2:
        return BootstrapCI(0.0, 0.0, 0.0, 0)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, r.size, size=(n_boot, r.size))
    boot_means = r[idx].mean(axis=1)
    lo = float(np.quantile(boot_means, (1.0 - ci) / 2.0))
    hi = float(np.quantile(boot_means, 1.0 - (1.0 - ci) / 2.0))
    return BootstrapCI(point=float(r.mean()), low=lo, high=hi, n_boot=n_boot)


def bootstrap_sharpe_ci(
    returns: list[float],
    n_boot: int = 2000,
    ci: float = 0.95,
    seed: int = 12345,
) -> BootstrapCI:
    """per-period Sharpe의 부트스트랩 신뢰구간."""
    r = np.asarray([x for x in returns if x == x], dtype=float)
    if r.size < 2:
        return BootstrapCI(0.0, 0.0, 0.0, 0)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, r.size, size=(n_boot, r.size))
    sample = r[idx]
    means = sample.mean(axis=1)
    sds = sample.std(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpes = np.where(sds > 0, means / sds, 0.0)
    lo = float(np.quantile(sharpes, (1.0 - ci) / 2.0))
    hi = float(np.quantile(sharpes, 1.0 - (1.0 - ci) / 2.0))
    point = float(r.mean() / r.std(ddof=1)) if r.std(ddof=1) > 0 else 0.0
    return BootstrapCI(point=point, low=lo, high=hi, n_boot=n_boot)
