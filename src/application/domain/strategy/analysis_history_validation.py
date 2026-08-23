"""Persisted sell-stage recommendations post-validation.

The evaluator is deliberately pure: callers provide historical recommendations and
subsequent closes, so tests and research scripts share the same outcome contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from statistics import mean, median
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class SellRecommendationObservation:
    history_id: int
    symbol: str
    analyzed_at: datetime
    signal_price: float
    sell_stage: str
    sell_ratio_min: float = 0.0
    sell_ratio_max: float = 0.0
    stage_source: str = "persisted_stage"


@dataclass(frozen=True, slots=True)
class ForwardClose:
    timestamp: datetime
    close: float


_PHASE_STAGE_FALLBACK = {
    "NONE": ("HOLD", 0.0, 0.0),
    "PHASE_1": ("HOLD", 0.0, 0.0),
    "PHASE_2": ("REDUCE_1", 0.2, 0.3),
    "PHASE_3": ("REDUCE_1", 0.2, 0.3),
    "PHASE_4": ("REDUCE_2", 0.3, 0.4),
    "PHASE_5": ("EXIT_ALL", 1.0, 1.0),
    "INSUFFICIENT_DATA": ("INSUFFICIENT_DATA", 0.0, 0.0),
}


def resolve_historical_sell_stage(
    sell_stage: str | None,
    sell_phase: str | None,
    sell_ratio_min: float | None,
    sell_ratio_max: float | None,
) -> tuple[str, float, float, str] | None:
    """Resolve old rows that predate final-stage persistence without inventing scores."""
    if sell_stage:
        return (
            sell_stage,
            float(sell_ratio_min or 0.0),
            float(sell_ratio_max or 0.0),
            "persisted_stage",
        )
    fallback = _PHASE_STAGE_FALLBACK.get(sell_phase or "")
    if fallback is None:
        return None
    return (*fallback, "phase_fallback")


def evaluate_sell_recommendations(
    observations: Iterable[SellRecommendationObservation],
    closes_by_symbol: Mapping[str, Sequence[ForwardClose]],
    *,
    horizons: tuple[int, ...] = (1, 5, 10, 20),
) -> dict:
    """Stage별 forward return, 적중률과 추정 회피손실을 집계한다."""
    rows: list[dict] = []
    for observation in observations:
        future = sorted(
            [
                item
                for item in closes_by_symbol.get(observation.symbol, ())
                if _comparable_datetime(item.timestamp)
                > _comparable_datetime(observation.analyzed_at)
                and item.close > 0
            ],
            key=lambda item: _comparable_datetime(item.timestamp),
        )
        if not future or observation.signal_price <= 0:
            continue

        returns: dict[str, float | None] = {}
        for horizon in horizons:
            value = None
            if len(future) >= horizon:
                value = future[horizon - 1].close / observation.signal_price - 1.0
            returns[f"return_{horizon}d"] = value

        available_closes = [item.close for item in future[: max(horizons)]]
        running_peak = observation.signal_price
        max_drawdown = 0.0
        for price in available_closes:
            running_peak = max(running_peak, price)
            max_drawdown = min(max_drawdown, price / running_peak - 1.0)
        target_return = returns.get("return_10d")
        if target_return is None:
            target_return = next(
                (returns[key] for key in reversed(returns) if returns[key] is not None), None
            )
        action_ratio = (observation.sell_ratio_min + observation.sell_ratio_max) / 2.0
        avoided_loss = (
            max(0.0, -target_return) * action_ratio
            if target_return is not None and observation.sell_stage != "HOLD"
            else 0.0
        )
        rows.append(
            {
                **asdict(observation),
                **returns,
                "max_drawdown": max_drawdown,
                "avoided_loss_estimate": avoided_loss,
                "hit": (
                    None
                    if target_return is None or observation.sell_stage == "INSUFFICIENT_DATA"
                    else (
                        target_return < 0
                        if observation.sell_stage != "HOLD"
                        else target_return >= 0
                    )
                ),
            }
        )

    stage_order = ("EXIT_ALL", "REDUCE_2", "REDUCE_1", "HOLD", "INSUFFICIENT_DATA")
    stages = [*stage_order, *sorted({row["sell_stage"] for row in rows} - set(stage_order))]
    summaries = []
    for stage in stages:
        for source in sorted({row["stage_source"] for row in rows if row["sell_stage"] == stage}):
            group = [
                row for row in rows if row["sell_stage"] == stage and row["stage_source"] == source
            ]
            hits = [row["hit"] for row in group if row["hit"] is not None]
            summary = {
                "sell_stage": stage,
                "stage_source": source,
                "count": len(group),
                "hit_rate": sum(bool(value) for value in hits) / len(hits) if hits else None,
                "avg_max_drawdown": mean(row["max_drawdown"] for row in group),
                "avg_avoided_loss_estimate": mean(row["avoided_loss_estimate"] for row in group),
            }
            for horizon in horizons:
                key = f"return_{horizon}d"
                values = [row[key] for row in group if row[key] is not None]
                summary[f"avg_{key}"] = mean(values) if values else None
                summary[f"median_{key}"] = median(values) if values else None
            summaries.append(summary)

    source_counts = {
        source: sum(row["stage_source"] == source for row in rows)
        for source in sorted({row["stage_source"] for row in rows})
    }
    persisted_count = source_counts.get("persisted_stage", 0)
    fallback_count = source_counts.get("phase_fallback", 0)

    return {
        "horizons": list(horizons),
        "evaluated_count": len(rows),
        "source_counts": source_counts,
        "conclusion_status": (
            "READY_PERSISTED_ONLY"
            if persisted_count and not fallback_count
            else (
                "PARTIAL_PERSISTED_WITH_FALLBACK"
                if persisted_count
                else "DEFERRED_NO_PERSISTED_STAGE"
            )
        ),
        "warning": (
            None
            if not fallback_count
            else (
                f"{fallback_count} phase-fallback observations are descriptive only; "
                f"persisted-stage sample size is {persisted_count}."
            )
        ),
        "stage_summary": summaries,
        "observations": rows,
    }


def render_sell_validation_markdown(result: dict) -> str:
    lines = [
        "# Sell Recommendation Forward Validation",
        "",
        f"Evaluated observations: **{result['evaluated_count']}**",
        "",
        f"Conclusion status: **{result['conclusion_status']}**",
        "",
        f"Source counts: `{result['source_counts']}`",
        "",
    ]
    if result.get("warning"):
        lines.extend([f"> Warning: {result['warning']}", ""])
    lines.extend(
        [
            "| Stage | Source | N | Hit rate | Avg 5d | Avg 10d | Avg max drawdown | Avoided loss est. |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in result["stage_summary"]:
        lines.append(
            f"| {row['sell_stage']} | {row['stage_source']} | {row['count']} | "
            f"{_percent(row['hit_rate'])} | {_percent(row.get('avg_return_5d'))} | "
            f"{_percent(row.get('avg_return_10d'))} | "
            f"{_percent(row['avg_max_drawdown'])} | "
            f"{_percent(row['avg_avoided_loss_estimate'])} |"
        )
    return "\n".join(lines) + "\n"


def _comparable_datetime(value: datetime) -> datetime:
    return (
        value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo is not None else value
    )


def _percent(value: float | None) -> str:
    return "NA" if value is None else f"{value:.2%}"
