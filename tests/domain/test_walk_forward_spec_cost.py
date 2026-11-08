"""walk-forward 실행 명세 동결(D7)·비용 민감도 G7·벤치 기간 정합·G3 비유한값 회귀 테스트(2026-11-08).

Codex(gpt-6-astra) 검토 + 직접 재현으로 확인된 결함:
- D7: _freeze가 label+config만 해시 → 국면 필터·실행옵션·비용이 달라도 같은 해시, OOS 전 재검증 없음
- G7: slippage_2x_positive가 항상 None(미측정)
- 벤치 OOS 수익이 건너뛴 fold 기간까지 포함
- G3: 전략 수익 None → TypeError, +inf → PASS
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.application.domain.backtest import gates as g
from src.application.domain.backtest.cost_schedule import get_backtest_cost_schedule
from src.application.domain.backtest.dto import BacktestConfigDTO
from src.application.domain.backtest.entry_guard import EntryGuardConfig
from src.application.domain.backtest.order_manager import BacktestOrderManager
from src.application.domain.backtest.portfolio_parity_engine import (
    PortfolioConstraints,
    PortfolioExecutionOptions,
)
from src.application.domain.backtest.regime_filter import RegimeEntryFilter
from src.application.domain.backtest.run_spec import SpecSerializationError, canonical, digest
from src.application.domain.backtest.walk_forward_runner import (
    WalkForwardCandidate,
    WalkForwardRunner,
)
from src.application.domain.backtest.walk_forward_windows import generate_rolling_windows
from tests.test_walk_forward import CAPITAL, _cfg, _panels, _trading_days

# ==================== run_spec 직렬화 ====================


def test_canonical_is_order_and_notation_invariant() -> None:
    assert digest({"a": 1, "b": Decimal("1.0")}) == digest({"b": Decimal("1.00"), "a": 1})
    assert digest([1, 2]) != digest([2, 1])  # 순서가 의미 있는 시퀀스는 정렬하지 않는다
    assert digest(Decimal("-0")) == digest(Decimal("0"))
    with pytest.raises(SpecSerializationError):
        canonical(float("nan"))
    with pytest.raises(SpecSerializationError):
        canonical(object())


def test_dataclass_fields_excluded_from_compare_are_still_hashed() -> None:
    a = EntryGuardConfig(benchmark_returns={date(2026, 1, 2): -0.01})
    b = EntryGuardConfig(benchmark_returns={date(2026, 1, 2): -0.03})
    assert a == b  # compare=False라 동등 비교로는 구분 안 됨
    assert digest(a) != digest(b)  # 실제 매수 차단 입력이므로 명세 digest는 달라야 한다


# ==================== D7 실행 명세 ====================


def _runner(**kw) -> WalkForwardRunner:
    base = dict(
        candidates=[WalkForwardCandidate("live", _cfg(25.0))],
        constraints=PortfolioConstraints(max_positions=3),
        backtest_config=CAPITAL,
    )
    base.update(kw)
    return WalkForwardRunner(**base)


def _spec(runner: WalkForwardRunner, cand: WalkForwardCandidate) -> dict:
    return runner._candidate_spec(cand, runner._resolved_backtest_config())


def test_spec_hash_covers_regime_execution_constraints_and_costs() -> None:
    cand = WalkForwardCandidate("live", _cfg(25.0))
    base = _spec(_runner(), cand)
    variants = [
        _spec(_runner(), replace(cand, regime_filter=RegimeEntryFilter(use_adx=True))),
        _spec(_runner(execution=PortfolioExecutionOptions(fill_timing="next_open")), cand),
        _spec(_runner(constraints=PortfolioConstraints(max_positions=4)), cand),
        _spec(
            _runner(
                backtest_config=BacktestConfigDTO(
                    initial_capital=Decimal("10000000"), slippage_rate=0.002
                )
            ),
            cand,
        ),
        _spec(_runner(eligibility="pit"), cand),
    ]
    hashes = {digest(base)} | {digest(v) for v in variants}
    assert len(hashes) == 1 + len(variants)
    # legacy 16자리 해시는 국면 필터 차이를 구분하지 못한다(하위호환 유지 대상)
    assert WalkForwardRunner._freeze(cand) == WalkForwardRunner._freeze(
        replace(cand, regime_filter=RegimeEntryFilter(use_adx=True))
    )


def test_duplicate_candidate_labels_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate candidate labels"):
        _runner(
            candidates=[
                WalkForwardCandidate("x", _cfg(25.0)),
                WalkForwardCandidate("x", _cfg(30.0)),
            ]
        )


def test_report_records_spec_hash_and_detects_mutation(monkeypatch) -> None:
    panels = _panels(["A", "B", "C"])
    days = _trading_days(panels)
    windows = generate_rolling_windows(days, train_size=140, test_size=40, step=40, embargo=5)
    runner = _runner()
    report = runner.run(panels, days, windows)
    assert report.spec["hash_schema_version"] == 2
    assert all(len(f.selected_spec_hash) == 64 for f in report.folds if f.selected_label != "-")
    assert len(report.spec["run_digest"]) == 64

    # 선택 후 OOS 전에 후보 설정이 바뀌면 예외
    runner2 = _runner()
    original = runner2._freeze

    def mutate_then_freeze(candidate):
        candidate.config.stochastic_config.oversold_threshold = 10.0  # pydantic 모델은 가변
        return original(candidate)

    monkeypatch.setattr(runner2, "_freeze", mutate_then_freeze)
    with pytest.raises(RuntimeError, match="spec changed"):
        runner2.run(panels, days, windows)


# ==================== G7 비용 민감도 · 벤치 정합 ====================


def test_slippage_multiplier_scales_override_and_schedule_default() -> None:
    base = BacktestOrderManager(BacktestConfigDTO(slippage_rate=0.001))
    doubled = BacktestOrderManager(BacktestConfigDTO(slippage_rate=0.001, slippage_multiplier=2.0))
    sched = get_backtest_cost_schedule(date(2026, 1, 5))
    assert doubled._slippage_rate(sched) == base._slippage_rate(sched) * 2
    default2 = BacktestOrderManager(BacktestConfigDTO(slippage_multiplier=2.0))
    assert default2._slippage_rate(sched) == sched.default_slippage_rate * 2


def test_cost_sensitivity_measured_with_aligned_benchmark() -> None:
    panels = _panels(["A", "B", "C"])
    days = _trading_days(panels)
    windows = generate_rolling_windows(days, train_size=140, test_size=40, step=40, embargo=5)
    bench = panels["A"]
    report = _runner(benchmark=bench, measure_slippage_sensitivity=True).run(panels, days, windows)

    cs = report.cost_sensitivity
    assert cs["status"] == "measured"
    assert cs["slippage_multiplier"] == 2.0
    assert cs["stress_return_pct"] <= cs["baseline_return_pct"] + 1e-9  # 비용 증가 → 수익 비증가
    assert isinstance(cs["slippage_2x_positive"], bool)
    assert report.benchmark_oos_return_pct == pytest.approx(cs["benchmark_return_pct"])

    gi = g.gate_inputs_from_report(report)
    assert gi.slippage_2x_positive == cs["slippage_2x_positive"]
    assert gi.benchmark_oos_return_pct == pytest.approx(report.benchmark_oos_return_pct)


def test_cost_sensitivity_na_reasons() -> None:
    panels = _panels(["A", "B", "C"])
    days = _trading_days(panels)
    windows = generate_rolling_windows(days, train_size=140, test_size=40, step=40, embargo=5)
    assert _runner().run(panels, days, windows).cost_sensitivity["reason"] == "not_requested"
    no_bench = _runner(measure_slippage_sensitivity=True).run(panels, days, windows)
    assert no_bench.cost_sensitivity == {"status": "na", "reason": "benchmark_unavailable"}
    zero = _runner(
        benchmark=panels["A"],
        measure_slippage_sensitivity=True,
        backtest_config=BacktestConfigDTO(initial_capital=Decimal("10000000"), slippage_rate=0.0),
    ).run(panels, days, windows)
    assert zero.cost_sensitivity["reason"] == "no_effective_slippage"


def test_benchmark_return_uses_only_evaluated_dates() -> None:
    panels = _panels(["A"])
    runner = _runner(benchmark=panels["A"])
    ts = list(panels["A"]["timestamp"])
    closes = [float(c) for c in panels["A"]["close"]]
    picked = [ts[10], ts[11], ts[50]]  # 11→50 사이 공백(건너뛴 fold)은 포함하지 않아야 한다
    expected = (closes[10] / closes[9]) * (closes[11] / closes[10]) * (closes[50] / closes[49]) - 1
    assert runner._benchmark_return_over(picked) == pytest.approx(expected * 100)


# ==================== G3 비유한값 ====================


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), float("-inf")])
def test_g3_non_finite_strategy_return_is_na(value) -> None:
    inp = g.GateInputs(
        oos_sharpe=0.5,
        oos_total_return_pct=value,
        benchmark_oos_return_pct=5.0,
        dsr=0.99,
        pbo=0.1,
        mean_train_sharpe=1.0,
        mean_test_sharpe=0.9,
        oos_trading_days=600,
        strat_bear_mdd=-5.0,
        benchmark_bear_mdd=-20.0,
        slippage_2x_positive=True,
    )
    g3 = next(c for c in g.evaluate_gates(inp).checks if c.key == "G3")
    assert g3.status == "NA"


# ==================== 2차 적대적 검토(Codex) 반영 ====================


def test_decimal_digest_is_exact_not_context_rounded() -> None:
    import decimal

    a = Decimal("1.0000000000000000000000000001")
    b = Decimal("1.0000000000000000000000000002")
    assert digest(a) != digest(b)  # 이전: normalize()가 28자리로 반올림해 충돌
    with decimal.localcontext() as ctx:
        ctx.prec = 6
        assert digest(Decimal("123456.789")) != digest(Decimal("123457"))
    assert digest(Decimal("1E+2")) == digest(Decimal("100")) == digest(Decimal("100.00"))


def test_stress_run_receives_exactly_2x_slippage_config(monkeypatch) -> None:
    from src.application.domain.backtest import walk_forward_runner as wfr

    seen: list[float] = []
    original_run = wfr.PortfolioParityEngine.run

    def spy(self, panels, config, **kw):
        seen.append(config.slippage_multiplier)
        return original_run(self, panels, config, **kw)

    monkeypatch.setattr(wfr.PortfolioParityEngine, "run", spy)
    panels = _panels(["A", "B", "C"])
    days = _trading_days(panels)
    windows = generate_rolling_windows(days, train_size=140, test_size=40, step=40, embargo=5)
    report = _runner(benchmark=panels["A"], measure_slippage_sensitivity=True).run(
        panels, days, windows
    )
    evaluated = sum(1 for f in report.folds if f.selected_label != "-")
    assert seen.count(2.0) == evaluated  # fold마다 스트레스 1회, 정확히 2배
    assert seen.count(1.0) == evaluated * 2  # train(후보 1개) + OOS


def test_run_does_not_mutate_runner_config() -> None:
    panels = _panels(["A", "B", "C"])
    days = _trading_days(panels)
    windows = generate_rolling_windows(days, train_size=140, test_size=40, step=40, embargo=5)
    runner = _runner()
    before = runner.backtest_config
    runner.run(panels, days, windows)
    assert runner.backtest_config is before
    assert runner.backtest_config.tax_exempt_symbols is None


def test_cli_bear_mdd_is_na_when_benchmark_date_missing() -> None:
    from types import SimpleNamespace

    from scripts.research.run_walk_forward import _benchmark_oos_metrics

    bench = _panels(["A"])["A"]
    ts = list(bench["timestamp"])
    report = SimpleNamespace(
        oos_dated_returns=[(ts[300], 0.0), (ts[301], 0.0), (ts[302], 0.0)],
        benchmark_oos_return_pct=1.0,
    )
    ret, mdd = _benchmark_oos_metrics(bench.drop(index=301).reset_index(drop=True), report)
    assert mdd is None  # 부분 날짜로 G4를 판정하지 않는다
