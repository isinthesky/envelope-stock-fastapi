from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Callable, Self, assert_never

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SellRuleCandidateType(StrEnum):
    ALL_THRESHOLDS = "all_thresholds"
    CURRENT_OVERLAY_SCORE = "current_overlay_score"


class SellRuleThresholdOperator(StrEnum):
    GTE = "gte"
    GT = "gt"
    LTE = "lte"
    LT = "lt"
    EQ = "eq"
    IS_TRUE = "is_true"


class SellRuleThresholdDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    operator: SellRuleThresholdOperator
    value: float | bool | str | None = None


class SellRuleEvaluationWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    train_start_date: str
    train_end_date: str
    test_start_date: str
    test_end_date: str

    @model_validator(mode="after")
    def validate_ordered_windows(self) -> Self:
        train_start = datetime.strptime(self.train_start_date, "%Y%m%d")
        train_end = datetime.strptime(self.train_end_date, "%Y%m%d")
        test_start = datetime.strptime(self.test_start_date, "%Y%m%d")
        test_end = datetime.strptime(self.test_end_date, "%Y%m%d")
        if train_start > train_end:
            raise ValueError("train_start_date must be on or before train_end_date")
        if test_start > test_end:
            raise ValueError("test_start_date must be on or before test_end_date")
        if train_end >= test_start:
            raise ValueError("train window must end before out-of-sample test window starts")
        return self


class PreRegisteredSellRuleCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    description: str
    rule_type: SellRuleCandidateType = SellRuleCandidateType.ALL_THRESHOLDS
    thresholds: tuple[SellRuleThresholdDefinition, ...] = Field(min_length=1)
    evaluation_window: SellRuleEvaluationWindow

    @property
    def definition_hash(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class SellRuleResearchFixtureRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    biz_date: str
    personal_buy_days_5d: int | None = None
    personal_buy_ratio_5d_to_volume: float | None = None
    market_credit_change_ratio: float | None = None
    market_credit_recent_high_ratio: float | None = None
    stoch_k: float | None = None
    is_52week_high: bool = False
    high_52week_ratio: float | None = None
    is_peak_label: bool
    future_drawdown_10d: float
    future_return_10d: float


class SellRulePreRegistrationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbols: tuple[str, ...] | None = None
    candidates: tuple[PreRegisteredSellRuleCandidate, ...] = Field(min_length=1)
    fixture_rows: tuple[SellRuleResearchFixtureRow, ...] | None = None


OverlayScore = Callable[[pd.Series], float]


def frozen_candidate_definitions(
    candidates: tuple[PreRegisteredSellRuleCandidate, ...],
) -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": candidate.candidate_id,
            "definition_hash": candidate.definition_hash,
            "threshold_set": [
                threshold.model_dump(mode="json") for threshold in candidate.thresholds
            ],
            "evaluation_window": candidate.evaluation_window.model_dump(mode="json"),
        }
        for candidate in candidates
    ]


def score_preregistered_candidate(
    candidate: PreRegisteredSellRuleCandidate,
    df: pd.DataFrame,
    overlay_score: OverlayScore,
) -> dict[str, Any]:
    test_frame = _frame_for_window(
        df,
        start_date=candidate.evaluation_window.test_start_date,
        end_date=candidate.evaluation_window.test_end_date,
    )
    triggered = test_frame[
        test_frame.apply(
            lambda row: _evaluate_preregistered_candidate(row, candidate, overlay_score),
            axis=1,
        )
    ].copy()
    trigger_count = len(triggered)
    peak_hit_count = int(triggered["is_peak_label"].sum()) if trigger_count else 0
    precision = peak_hit_count / trigger_count if trigger_count else 0.0
    avg_drawdown = (
        float(triggered["future_drawdown_10d"].fillna(0).mean())
        if trigger_count
        else 0.0
    )
    avg_return = (
        float(triggered["future_return_10d"].fillna(0).mean())
        if trigger_count
        else 0.0
    )
    avg_trade_impact = avg_drawdown - avg_return
    return {
        "candidate_id": candidate.candidate_id,
        "description": candidate.description,
        "definition_hash": candidate.definition_hash,
        "rule_type": candidate.rule_type.value,
        "threshold_set": [
            threshold.model_dump(mode="json") for threshold in candidate.thresholds
        ],
        "evaluation_window": candidate.evaluation_window.model_dump(mode="json"),
        "period": "out_of_sample",
        "rows_evaluated": len(test_frame),
        "trigger_count": trigger_count,
        "peak_hit_count": peak_hit_count,
        "precision": round(precision, 4),
        "avg_future_drawdown_10d": round(avg_drawdown, 4),
        "avg_future_return_10d": round(avg_return, 4),
        "avg_trade_impact_10d": round(avg_trade_impact, 4),
        "trade_impact_sum_10d": round(avg_trade_impact * trigger_count, 4),
    }


def research_preregistered_frame(
    *,
    config: SellRulePreRegistrationConfig,
    combined: pd.DataFrame,
    symbol_summaries: list[dict[str, Any]],
    resolved_start: str,
    resolved_end: str,
    data_source: str,
    overlay_score: OverlayScore,
) -> dict[str, Any]:
    scored_rules = [
        score_preregistered_candidate(candidate, combined, overlay_score)
        for candidate in config.candidates
    ]
    return {
        "mode": "pre_registered",
        "data_source": data_source,
        "start_date": resolved_start,
        "end_date": resolved_end,
        "symbols": symbol_summaries,
        "rows_analyzed": len(combined),
        "candidate_count": len(config.candidates),
        "frozen_candidate_definitions": frozen_candidate_definitions(config.candidates),
        "out_of_sample": scored_rules,
        "data_snooping_warning": len(config.candidates) > 1,
    }


def render_preregistered_sell_rule_report(result: dict[str, Any]) -> str:
    lines = [
        "# Pre-Registered Sell Rule Research",
        "",
        f"- Mode: {result.get('mode')}",
        f"- Data source: {result.get('data_source')}",
        f"- Research window: {result.get('start_date')} to {result.get('end_date')}",
        f"- Candidate count: {result.get('candidate_count')}",
        f"- Data-snooping warning: {result.get('data_snooping_warning')}",
        "",
        "## Frozen Candidate Definitions",
        "",
    ]
    for definition in result.get("frozen_candidate_definitions", []):
        threshold_set_json = json.dumps(
            definition["threshold_set"],
            ensure_ascii=False,
            sort_keys=True,
        )
        evaluation_window_json = json.dumps(
            definition["evaluation_window"],
            ensure_ascii=False,
            sort_keys=True,
        )
        lines.extend(
            [
                f"### {definition['candidate_id']}",
                "",
                f"- Definition hash: `{definition['definition_hash']}`",
                f"- Threshold set: `{threshold_set_json}`",
                f"- Evaluation window: `{evaluation_window_json}`",
                "",
            ]
        )

    lines.extend(
        [
            "## Out-of-Sample Comparison",
            "",
            "| Candidate ID | Precision | Future Drawdown | Future Return | "
            "Trade Impact | Triggers |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in result.get("out_of_sample", []):
        lines.append(
            (
                "| {candidate_id} | {precision:.4f} | {drawdown:.4f} | "
                "{future_return:.4f} | {impact:.4f} | {triggers} |"
            ).format(
                candidate_id=row["candidate_id"],
                precision=row["precision"],
                drawdown=row["avg_future_drawdown_10d"],
                future_return=row["avg_future_return_10d"],
                impact=row["avg_trade_impact_10d"],
                triggers=row["trigger_count"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def _frame_for_window(
    df: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    dated = df.copy()
    if "biz_date" not in dated.columns:
        dated["biz_date"] = pd.to_datetime(dated["timestamp"]).dt.strftime("%Y%m%d")
    return dated[(dated["biz_date"] >= start_date) & (dated["biz_date"] <= end_date)]


def _threshold_value(
    row: pd.Series,
    threshold: SellRuleThresholdDefinition,
    overlay_score: OverlayScore,
) -> float | bool | str | None:
    if threshold.field == "current_overlay_score":
        return overlay_score(row)
    value = row.get(threshold.field)
    if pd.isna(value):
        return None
    if isinstance(value, bool | str):
        return value
    if isinstance(value, int | float):
        return float(value)
    return None


def _passes_threshold(
    row: pd.Series,
    threshold: SellRuleThresholdDefinition,
    overlay_score: OverlayScore,
) -> bool:
    actual = _threshold_value(row, threshold, overlay_score)
    expected = threshold.value
    match threshold.operator:
        case SellRuleThresholdOperator.GTE:
            return (
                isinstance(actual, int | float)
                and isinstance(expected, int | float)
                and actual >= expected
            )
        case SellRuleThresholdOperator.GT:
            return (
                isinstance(actual, int | float)
                and isinstance(expected, int | float)
                and actual > expected
            )
        case SellRuleThresholdOperator.LTE:
            return (
                isinstance(actual, int | float)
                and isinstance(expected, int | float)
                and actual <= expected
            )
        case SellRuleThresholdOperator.LT:
            return (
                isinstance(actual, int | float)
                and isinstance(expected, int | float)
                and actual < expected
            )
        case SellRuleThresholdOperator.EQ:
            return actual == expected
        case SellRuleThresholdOperator.IS_TRUE:
            return bool(actual) is True
        case _ as unreachable:
            assert_never(unreachable)


def _evaluate_preregistered_candidate(
    row: pd.Series,
    candidate: PreRegisteredSellRuleCandidate,
    overlay_score: OverlayScore,
) -> bool:
    match candidate.rule_type:
        case SellRuleCandidateType.ALL_THRESHOLDS | SellRuleCandidateType.CURRENT_OVERLAY_SCORE:
            return all(
                _passes_threshold(row, threshold, overlay_score)
                for threshold in candidate.thresholds
            )
        case _ as unreachable:
            assert_never(unreachable)
