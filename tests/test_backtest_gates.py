# -*- coding: utf-8 -*-
"""P5 Go/No-Go 게이트 테스트 — evaluate_gates / gate_inputs_from_report (순수 로직)."""

from dataclasses import dataclass, field

from src.application.domain.backtest.gates import (
    GateInputs,
    GateThresholds,
    evaluate_gates,
    gate_inputs_from_report,
)


def _passing_inputs(**over) -> GateInputs:
    """모든 게이트를 통과시키는 기준 입력(개별 테스트에서 필드만 덮어씀)."""
    base = dict(
        dsr=0.97,
        oos_sharpe=1.2,
        oos_total_return_pct=25.0,
        oos_trading_days=1000,
        pbo=0.1,
        mean_train_sharpe=1.5,
        mean_test_sharpe=1.2,  # 감쇠 20%
        strat_bear_mdd=-5.0,
        benchmark_oos_return_pct=10.0,
        benchmark_bear_mdd=-8.0,
        slippage_2x_positive=True,
    )
    base.update(over)
    return GateInputs(**base)


# ==================== 종합 판정 ====================


def test_all_pass_is_go():
    r = evaluate_gates(_passing_inputs())
    assert r.verdict == "GO"
    assert r.failed == 0 and r.na == 0
    assert r.passed == 7


def test_any_fail_is_no_go():
    r = evaluate_gates(_passing_inputs(dsr=0.5))  # G1 실패
    assert r.verdict == "NO_GO"
    assert r.failed == 1
    assert "G1" in r.reason


def test_na_without_fail_is_incomplete():
    # 벤치/민감도 미제공 → G3/G4/G7 NA, 나머지 PASS, FAIL 없음
    r = evaluate_gates(
        _passing_inputs(
            benchmark_oos_return_pct=None,
            benchmark_bear_mdd=None,
            slippage_2x_positive=None,
        )
    )
    assert r.verdict == "INCOMPLETE"
    assert r.failed == 0 and r.na >= 1
    assert "근거 부족" in r.reason


def test_fail_dominates_na():
    # FAIL과 NA가 동시 → NO_GO(FAIL 우선)
    r = evaluate_gates(_passing_inputs(oos_sharpe=0.2, slippage_2x_positive=None))
    assert r.verdict == "NO_GO"


# ==================== 개별 게이트 ====================


def test_g2_sample_insufficiency_is_na_not_pass():
    r = evaluate_gates(_passing_inputs(oos_trading_days=100))
    g2 = next(c for c in r.checks if c.key == "G2")
    assert g2.status == "NA"
    assert r.verdict == "INCOMPLETE"


def test_g4_bear_mdd_worse_than_bench_fails():
    # 전략 MDD가 벤치보다 더 나쁨(더 음수) → FAIL
    r = evaluate_gates(_passing_inputs(strat_bear_mdd=-12.0, benchmark_bear_mdd=-8.0))
    g4 = next(c for c in r.checks if c.key == "G4")
    assert g4.status == "FAIL"


def test_g4_bear_mdd_better_passes():
    r = evaluate_gates(_passing_inputs(strat_bear_mdd=-4.0, benchmark_bear_mdd=-8.0))
    g4 = next(c for c in r.checks if c.key == "G4")
    assert g4.status == "PASS"


def test_g6_negative_train_sharpe_is_na():
    # IS Sharpe ≤ 0 → 감쇠 정의 불가 → NA
    r = evaluate_gates(_passing_inputs(mean_train_sharpe=-0.5, mean_test_sharpe=-0.2))
    g6 = next(c for c in r.checks if c.key == "G6")
    assert g6.status == "NA"


def test_g6_excessive_decay_fails():
    # IS 2.0 → OOS 0.5 = 75% 감쇠 > 30% → FAIL
    r = evaluate_gates(_passing_inputs(mean_train_sharpe=2.0, mean_test_sharpe=0.5))
    g6 = next(c for c in r.checks if c.key == "G6")
    assert g6.status == "FAIL"


def test_g5_pbo_none_is_na():
    r = evaluate_gates(_passing_inputs(pbo=None))
    g5 = next(c for c in r.checks if c.key == "G5")
    assert g5.status == "NA"


def test_dsr_nan_is_na():
    r = evaluate_gates(_passing_inputs(dsr=float("nan")))
    g1 = next(c for c in r.checks if c.key == "G1")
    assert g1.status == "NA"


def test_custom_thresholds_applied():
    # 완화된 기준(Sharpe ≥ 0.1)이면 통과
    r = evaluate_gates(
        _passing_inputs(oos_sharpe=0.2),
        GateThresholds(min_oos_sharpe=0.1),
    )
    g2 = next(c for c in r.checks if c.key == "G2")
    assert g2.status == "PASS"


# ==================== report 추출 ====================


@dataclass
class _FakeFold:
    train: dict = field(default_factory=dict)
    test: dict = field(default_factory=dict)


@dataclass
class _FakeReport:
    oos: dict
    stats: dict
    folds: list


def test_gate_inputs_from_report_extracts_means_and_regime():
    report = _FakeReport(
        oos={"sharpe": -0.24, "total_return": 8.14, "trading_days": 1008},
        stats={
            "deflated_sharpe": 0.37,
            "pbo": 0.03,
            "regime": {"bear": {"mdd": -9.11}},
        },
        folds=[
            _FakeFold(train={"sharpe": -0.55}, test={"sharpe": -2.08}),
            _FakeFold(train={"sharpe": -1.04}, test={"sharpe": -0.08}),
        ],
    )
    inp = gate_inputs_from_report(report, benchmark_oos_return_pct=12.0, benchmark_bear_mdd=-15.0)
    assert inp.dsr == 0.37
    assert inp.oos_sharpe == -0.24
    assert inp.oos_trading_days == 1008
    assert inp.strat_bear_mdd == -9.11
    assert inp.mean_train_sharpe == (-0.55 + -1.04) / 2
    assert inp.mean_test_sharpe == (-2.08 + -0.08) / 2
    # 실측 데이터 형태 → NO_GO 여야 함
    assert evaluate_gates(inp).verdict == "NO_GO"
