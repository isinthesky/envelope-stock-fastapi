from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import assert_never

from src.application.domain.backtest.validation import (
    CandidateRule,
    FROZEN_HASH_LENGTH,
    RuleMetric,
    RuleValue,
    WalkForwardConfig,
    WindowMetrics,
)


@dataclass(frozen=True, slots=True)
class FrozenCandidate:
    candidate_id: str
    name: str
    rules: Mapping[str, RuleValue]
    frozen_hash: str

    def rules_json(self) -> str:
        return json.dumps(dict(self.rules), sort_keys=True, separators=(",", ":"))


def _frozen_hash_for_rules(
    candidate_id: str,
    name: str,
    rules: Mapping[str, RuleValue],
) -> str:
    payload = {
        "candidate_id": candidate_id,
        "name": name,
        "rules": dict(rules),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()[:FROZEN_HASH_LENGTH]


@dataclass(frozen=True, slots=True)
class WalkForwardValidationResult:
    config: WalkForwardConfig
    frozen_candidates: list[FrozenCandidate]
    selected_candidate: CandidateRule
    selected_candidate_hash: str

    @property
    def selected_candidate_id(self) -> str:
        return self.selected_candidate.candidate_id

    def to_markdown(self) -> str:
        period = self.config.period
        lines = [
            f"# Walk-Forward Validation Report: {self.config.strategy_id}",
            "",
            f"- Frozen candidate ID: `{self.selected_candidate_id}`",
            f"- Frozen candidate hash: `{self.selected_candidate_hash}`",
            f"- Train period: `{period.train_start}` to `{period.train_end}`",
            f"- Test period: `{period.test_start}` to `{period.test_end}`",
            f"- Benchmark: `{self.config.benchmark}`",
            f"- Selection metric: `{self.config.selection_metric.value}`",
            "",
        ]
        if len(self.config.candidates) > 1:
            lines.extend(
                [
                    "## Data-Snooping Warning",
                    "",
                    (
                        "Data-snooping warning: multiple candidates were reviewed. "
                        "Treat out-of-sample metrics as validation evidence only; "
                        "do not tune thresholds on the frozen test window."
                    ),
                    "",
                ]
            )
        lines.extend(
            [
                "## Frozen Candidate Ledger",
                "",
                "| Candidate ID | Frozen Hash | Rule Definition |",
                "| --- | --- | --- |",
            ]
        )
        for candidate in self.frozen_candidates:
            lines.append(
                f"| `{candidate.candidate_id}` | `{candidate.frozen_hash}` | "
                f"`{candidate.rules_json()}` |"
            )
        lines.extend(
            [
                "",
                "## In-Sample vs Out-of-Sample Metrics",
                "",
                "| Window | CAGR | Excess Return | MDD | Sharpe | Turnover |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
                self._metric_row("Train", self.selected_candidate.train_metrics),
                self._metric_row("Test", self.selected_candidate.test_metrics),
                "",
            ]
        )
        return "\n".join(lines)

    def _metric_row(self, label: str, metrics: WindowMetrics) -> str:
        return (
            f"| {label} | {metrics.cagr:.2f}% | {metrics.excess_return:.2f}% | "
            f"{metrics.mdd:.2f}% | {metrics.sharpe:.2f} | {metrics.turnover:.2f} |"
        )


class WalkForwardValidationRunner:
    def __init__(self, config: WalkForwardConfig):
        self.config = config

    def run(self) -> WalkForwardValidationResult:
        frozen_candidates = self._freeze_candidates()
        selected_candidate = max(
            self.config.candidates,
            key=self._selection_score,
        )
        selected_hash = self._frozen_hash_for(selected_candidate, frozen_candidates)
        return WalkForwardValidationResult(
            config=self.config,
            frozen_candidates=frozen_candidates,
            selected_candidate=selected_candidate,
            selected_candidate_hash=selected_hash,
        )

    def _freeze_candidates(self) -> list[FrozenCandidate]:
        frozen_candidates: list[FrozenCandidate] = []
        for candidate in self.config.candidates:
            frozen_rules = MappingProxyType(dict(candidate.rules))
            frozen_candidates.append(
                FrozenCandidate(
                    candidate_id=candidate.candidate_id,
                    name=candidate.name,
                    rules=frozen_rules,
                    frozen_hash=_frozen_hash_for_rules(
                        candidate.candidate_id,
                        candidate.name,
                        frozen_rules,
                    ),
                )
            )
        return frozen_candidates

    def _selection_score(self, candidate: CandidateRule) -> float:
        metrics = candidate.train_metrics
        match self.config.selection_metric:
            case RuleMetric.CAGR:
                return metrics.cagr
            case RuleMetric.EXCESS_RETURN:
                return metrics.excess_return
            case RuleMetric.SHARPE:
                return metrics.sharpe
            case unreachable:
                assert_never(unreachable)

    def _frozen_hash_for(
        self,
        selected_candidate: CandidateRule,
        frozen_candidates: list[FrozenCandidate],
    ) -> str:
        for candidate in frozen_candidates:
            if candidate.candidate_id == selected_candidate.candidate_id:
                return candidate.frozen_hash
        return selected_candidate.frozen_hash()
