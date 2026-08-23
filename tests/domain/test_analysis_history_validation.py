from datetime import datetime, timedelta

import pytest

from src.application.domain.strategy.analysis_history_validation import (
    ForwardClose,
    SellRecommendationObservation,
    evaluate_sell_recommendations,
    render_sell_validation_markdown,
    resolve_historical_sell_stage,
)


def test_forward_validation_groups_stage_returns_and_avoided_loss() -> None:
    base = datetime(2026, 1, 1)
    observations = [
        SellRecommendationObservation(1, "A", base, 100.0, "EXIT_ALL", 1.0, 1.0),
        SellRecommendationObservation(2, "B", base, 100.0, "HOLD"),
    ]
    closes = {
        "A": [ForwardClose(base + timedelta(days=i), 100.0 - i) for i in range(1, 21)],
        "B": [ForwardClose(base + timedelta(days=i), 100.0 + i) for i in range(1, 21)],
    }

    result = evaluate_sell_recommendations(observations, closes)

    assert result["evaluated_count"] == 2
    exit_summary = next(row for row in result["stage_summary"] if row["sell_stage"] == "EXIT_ALL")
    hold_summary = next(row for row in result["stage_summary"] if row["sell_stage"] == "HOLD")
    assert exit_summary["hit_rate"] == 1.0
    assert exit_summary["avg_return_10d"] == pytest.approx(-0.10)
    assert exit_summary["avg_avoided_loss_estimate"] == pytest.approx(0.10)
    assert hold_summary["hit_rate"] == 1.0
    assert "Sell Recommendation Forward Validation" in render_sell_validation_markdown(result)


def test_forward_validation_skips_rows_without_subsequent_prices() -> None:
    result = evaluate_sell_recommendations(
        [SellRecommendationObservation(1, "A", datetime(2026, 1, 1), 100.0, "HOLD")],
        {},
    )

    assert result["evaluated_count"] == 0


def test_forward_validation_sorts_prices_and_uses_running_peak_drawdown() -> None:
    base = datetime(2026, 1, 1)
    result = evaluate_sell_recommendations(
        [SellRecommendationObservation(1, "A", base, 100.0, "HOLD")],
        {
            "A": [
                ForwardClose(base + timedelta(days=3), 100.0),
                ForwardClose(base + timedelta(days=1), 120.0),
                ForwardClose(base + timedelta(days=2), 102.0),
            ]
        },
        horizons=(1, 2, 3),
    )

    assert result["observations"][0]["return_1d"] == pytest.approx(0.20)
    assert result["observations"][0]["max_drawdown"] == pytest.approx(-1 / 6)


def test_insufficient_data_is_excluded_from_hit_rate() -> None:
    base = datetime(2026, 1, 1)
    result = evaluate_sell_recommendations(
        [SellRecommendationObservation(1, "A", base, 100.0, "INSUFFICIENT_DATA")],
        {"A": [ForwardClose(base + timedelta(days=1), 90.0)]},
        horizons=(1,),
    )

    assert result["observations"][0]["hit"] is None
    assert result["stage_summary"][0]["hit_rate"] is None


def test_phase_fallback_report_defers_persisted_stage_conclusion() -> None:
    base = datetime(2026, 1, 1)
    result = evaluate_sell_recommendations(
        [SellRecommendationObservation(1, "A", base, 100.0, "HOLD", stage_source="phase_fallback")],
        {"A": [ForwardClose(base + timedelta(days=1), 101.0)]},
        horizons=(1,),
    )

    assert result["source_counts"] == {"phase_fallback": 1}
    assert result["conclusion_status"] == "DEFERRED_NO_PERSISTED_STAGE"
    assert "phase-fallback" in result["warning"]
    assert "phase_fallback" in render_sell_validation_markdown(result)


def test_old_phase_is_used_only_when_persisted_stage_is_missing() -> None:
    assert resolve_historical_sell_stage(None, "PHASE_4", None, None) == (
        "REDUCE_2",
        0.3,
        0.4,
        "phase_fallback",
    )
    assert resolve_historical_sell_stage("EXIT_ALL", "NONE", 1.0, 1.0) == (
        "EXIT_ALL",
        1.0,
        1.0,
        "persisted_stage",
    )
