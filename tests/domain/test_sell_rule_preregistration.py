from datetime import datetime

import pandas as pd
import pytest
from pydantic import ValidationError

from src.application.domain.strategy.sell_rule_research_service import (
    PreRegisteredSellRuleCandidate,
    SellPeakRuleResearchService,
    SellRulePreRegistrationConfig,
    render_preregistered_sell_rule_report,
)


def _candidate_config(candidate_id: str = "current-overlay-score-v1") -> dict:
    return {
        "candidate_id": candidate_id,
        "description": "current overlay score frozen before test",
        "rule_type": "current_overlay_score",
        "thresholds": [
            {"field": "current_overlay_score", "operator": "gte", "value": 8.0},
        ],
        "evaluation_window": {
            "train_start_date": "20240101",
            "train_end_date": "20240215",
            "test_start_date": "20240216",
            "test_end_date": "20240331",
        },
    }


def test_candidate_definition_is_immutable_and_has_id_thresholds_window() -> None:
    candidate = PreRegisteredSellRuleCandidate.model_validate(_candidate_config())

    assert candidate.candidate_id == "current-overlay-score-v1"
    assert candidate.thresholds[0].field == "current_overlay_score"
    assert candidate.evaluation_window.test_start_date == "20240216"
    assert candidate.definition_hash == PreRegisteredSellRuleCandidate.model_validate(
        _candidate_config()
    ).definition_hash

    with pytest.raises(ValidationError):
        candidate.candidate_id = "changed-after-test-window"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        candidate.thresholds.append(  # type: ignore[attr-defined]
            {"field": "stoch_k", "operator": "gte", "value": 90.0}
        )


def test_config_missing_candidate_id_fails_validation() -> None:
    raw_candidate = _candidate_config()
    raw_candidate.pop("candidate_id")

    with pytest.raises(ValidationError, match="candidate_id"):
        SellRulePreRegistrationConfig.model_validate({"candidates": [raw_candidate]})


def test_overlapping_train_and_test_windows_fail_validation() -> None:
    raw_candidate = _candidate_config()
    raw_candidate["evaluation_window"]["train_end_date"] = "20240216"

    with pytest.raises(ValidationError, match="out-of-sample"):
        SellRulePreRegistrationConfig.model_validate({"candidates": [raw_candidate]})


async def test_preregistered_research_reports_out_of_sample_trade_impact() -> None:
    service = SellPeakRuleResearchService(session=None)  # type: ignore[arg-type]
    config = SellRulePreRegistrationConfig.model_validate(
        {
            "symbols": ["005930"],
            "candidates": [
                _candidate_config("current-overlay-score-v1"),
                {
                    **_candidate_config("simple-credit-personal-v1"),
                    "description": "simple credit and personal flow thresholds",
                    "rule_type": "all_thresholds",
                    "thresholds": [
                        {"field": "personal_buy_days_5d", "operator": "gte", "value": 4.0},
                        {
                            "field": "market_credit_change_ratio",
                            "operator": "gte",
                            "value": 0.008,
                        },
                    ],
                },
            ],
        }
    )

    async def fake_resolve(symbols=None):
        assert symbols == ["005930"]
        return [{"symbol": "005930", "name": "삼성전자", "market": "KOSPI"}]

    async def fake_load(
        symbol: str,
        market: str | None,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        assert (symbol, market, start_date, end_date) == (
            "005930",
            "KOSPI",
            "20240101",
            "20240331",
        )
        rows = []
        base = datetime(2024, 1, 1)
        for day in range(90):
            is_test_signal = day >= 60 and day % 5 == 0
            rows.append(
                {
                    "timestamp": pd.Timestamp(base) + pd.Timedelta(days=day),
                    "close": 100 + day,
                    "high_52week_ratio": 0.99 if is_test_signal else 0.94,
                    "is_52week_high": is_test_signal,
                    "personal_buy_days_5d": 5 if is_test_signal else 2,
                    "personal_buy_ratio_5d_to_volume": 0.22 if is_test_signal else 0.05,
                    "market_credit_change_ratio": 0.011 if is_test_signal else 0.001,
                    "market_credit_recent_high_ratio": 0.997 if is_test_signal else 0.96,
                    "stoch_k": 88 if is_test_signal else 55,
                }
            )
        return pd.DataFrame(rows)

    def fake_label(df: pd.DataFrame) -> pd.DataFrame:
        labeled = df.copy()
        labeled["biz_date"] = labeled["timestamp"].dt.strftime("%Y%m%d")
        labeled["is_peak_label"] = labeled["is_52week_high"]
        labeled["future_drawdown_10d"] = labeled["is_52week_high"].map(
            lambda value: 0.09 if value else 0.02
        )
        labeled["future_return_10d"] = labeled["is_52week_high"].map(
            lambda value: 0.01 if value else 0.04
        )
        return labeled

    service._resolve_symbols = fake_resolve  # type: ignore[method-assign]
    service._load_symbol_frame = fake_load  # type: ignore[method-assign]
    service._label_local_peaks = fake_label  # type: ignore[method-assign]

    result = await service.research_preregistered_sell_rules(config)
    report = render_preregistered_sell_rule_report(result)

    assert result["data_snooping_warning"] is True
    assert {row["candidate_id"] for row in result["out_of_sample"]} == {
        "current-overlay-score-v1",
        "simple-credit-personal-v1",
    }
    assert result["out_of_sample"][0]["precision"] == 1.0
    assert result["out_of_sample"][0]["avg_future_drawdown_10d"] == 0.09
    assert result["out_of_sample"][0]["avg_future_return_10d"] == 0.01
    assert result["out_of_sample"][0]["avg_trade_impact_10d"] == 0.08
    assert "## Out-of-Sample Comparison" in report
    assert "current-overlay-score-v1" in report
