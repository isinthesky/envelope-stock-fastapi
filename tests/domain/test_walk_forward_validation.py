from datetime import date

import pytest

from src.application.domain.backtest.validation import (
    CandidateRule,
    RuleMetric,
    WalkForwardConfig,
    WalkForwardPeriod,
    WalkForwardValidationError,
    WindowMetrics,
)
from src.application.domain.backtest.walk_forward import WalkForwardValidationRunner


def _metrics(cagr: float, benchmark_cagr: float = 4.0) -> WindowMetrics:
    return WindowMetrics(
        cagr=cagr,
        benchmark_cagr=benchmark_cagr,
        mdd=-8.0,
        sharpe=1.2,
        turnover=0.35,
    )


def _candidate(candidate_id: str, train_cagr: float, test_cagr: float) -> CandidateRule:
    return CandidateRule(
        candidate_id=candidate_id,
        name=f"{candidate_id} rule",
        rules={
            "short_period": 55,
            "long_period": 165,
            "stoch_oversold": 30.0,
        },
        train_metrics=_metrics(train_cagr),
        test_metrics=_metrics(test_cagr),
    )


def _config(candidates: list[CandidateRule]) -> WalkForwardConfig:
    return WalkForwardConfig(
        strategy_id="golden-cross-pullback",
        benchmark="KOSPI",
        selection_metric=RuleMetric.CAGR,
        period=WalkForwardPeriod(
            train_start=date(2023, 1, 1),
            train_end=date(2023, 12, 31),
            test_start=date(2024, 1, 1),
            test_end=date(2024, 12, 31),
        ),
        candidates=candidates,
    )


def test_selection_uses_train_metrics_when_test_metrics_favor_another_candidate() -> None:
    # Given
    train_winner = _candidate("train-winner", train_cagr=18.0, test_cagr=2.0)
    test_winner = _candidate("test-winner", train_cagr=10.0, test_cagr=80.0)

    # When
    result = WalkForwardValidationRunner(_config([train_winner, test_winner])).run()

    # Then
    assert result.selected_candidate_id == "train-winner"
    assert result.selected_candidate.test_metrics.cagr == 2.0
    assert result.selected_candidate.train_metrics.cagr == 18.0


def test_candidate_hash_is_frozen_from_rule_definition_before_test_metrics_change() -> None:
    # Given
    candidate = _candidate("stable-rule", train_cagr=12.0, test_cagr=4.0)
    baseline_result = WalkForwardValidationRunner(_config([candidate])).run()
    changed_test_metrics = CandidateRule(
        candidate_id=candidate.candidate_id,
        name=candidate.name,
        rules=candidate.rules,
        train_metrics=candidate.train_metrics,
        test_metrics=_metrics(99.0),
    )

    # When
    changed_result = WalkForwardValidationRunner(_config([changed_test_metrics])).run()

    # Then
    assert changed_result.selected_candidate_hash == baseline_result.selected_candidate_hash
    assert changed_result.selected_candidate_id == baseline_result.selected_candidate_id


def test_frozen_candidate_rules_do_not_alias_original_candidate_rules() -> None:
    # Given
    candidate = _candidate("stable-rule", train_cagr=12.0, test_cagr=4.0)
    result = WalkForwardValidationRunner(_config([candidate])).run()
    frozen_candidate = result.frozen_candidates[0]
    frozen_rules_json = frozen_candidate.rules_json()
    frozen_hash = frozen_candidate.frozen_hash

    # When
    candidate.rules["short_period"] = 5

    # Then
    assert frozen_candidate.rules_json() == frozen_rules_json
    assert frozen_candidate.frozen_hash == frozen_hash


def test_markdown_report_contains_frozen_candidate_split_metrics_and_snooping_warning() -> None:
    # Given
    config = _config(
        [
            _candidate("baseline", train_cagr=9.0, test_cagr=5.0),
            _candidate("candidate-v1", train_cagr=16.0, test_cagr=7.5),
        ]
    )

    # When
    report = WalkForwardValidationRunner(config).run().to_markdown()

    # Then
    assert "Frozen candidate ID: `candidate-v1`" in report
    assert "Frozen candidate hash:" in report
    assert "Train period: `2023-01-01` to `2023-12-31`" in report
    assert "Test period: `2024-01-01` to `2024-12-31`" in report
    assert "Benchmark: `KOSPI`" in report
    assert "| Window | CAGR | Excess Return | MDD | Sharpe | Turnover |" in report
    assert "Data-snooping warning" in report


def test_overlapping_train_and_test_windows_fail_validation() -> None:
    # Given / When / Then
    with pytest.raises(WalkForwardValidationError, match="overlap"):
        WalkForwardConfig(
            strategy_id="golden-cross-pullback",
            benchmark="KOSPI",
            selection_metric=RuleMetric.CAGR,
            period=WalkForwardPeriod(
                train_start=date(2023, 1, 1),
                train_end=date(2024, 3, 31),
                test_start=date(2024, 1, 1),
                test_end=date(2024, 12, 31),
            ),
            candidates=[_candidate("baseline", train_cagr=8.0, test_cagr=7.0)],
        )
