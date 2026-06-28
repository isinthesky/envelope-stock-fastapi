from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from enum import Enum
from hashlib import sha256
from typing import Final

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from yaml import YAMLError

RuleValue = bool | int | float | str
FROZEN_HASH_LENGTH: Final = 16


@dataclass(frozen=True, slots=True)
class WalkForwardValidationError(Exception):
    reason: str

    def __str__(self) -> str:
        return self.reason


class RuleMetric(str, Enum):
    CAGR = "cagr"
    EXCESS_RETURN = "excess_return"
    SHARPE = "sharpe"


class WindowMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    cagr: float = Field(description="Compounded annual growth rate (%)")
    benchmark_cagr: float = Field(description="Benchmark CAGR for the same window (%)")
    mdd: float = Field(description="Maximum drawdown (%)")
    sharpe: float = Field(description="Sharpe ratio")
    turnover: float = Field(description="Portfolio turnover")

    @property
    def excess_return(self) -> float:
        return round(self.cagr - self.benchmark_cagr, 4)


class CandidateRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    rules: dict[str, RuleValue] = Field(min_length=1)
    train_metrics: WindowMetrics
    test_metrics: WindowMetrics

    def frozen_hash(self) -> str:
        payload = {
            "candidate_id": self.candidate_id,
            "name": self.name,
            "rules": self.rules,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return sha256(encoded).hexdigest()[:FROZEN_HASH_LENGTH]


class WalkForwardPeriod(BaseModel):
    model_config = ConfigDict(frozen=True)

    train_start: date
    train_end: date
    test_start: date
    test_end: date

    @model_validator(mode="after")
    def validate_order(self) -> WalkForwardPeriod:
        if self.train_end < self.train_start:
            raise WalkForwardValidationError("train_end must be on or after train_start")
        if self.test_end < self.test_start:
            raise WalkForwardValidationError("test_end must be on or after test_start")
        if self.train_end >= self.test_start:
            raise WalkForwardValidationError(
                "train and test windows overlap; train_end must be before test_start"
            )
        return self


class WalkForwardConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_id: str = Field(min_length=1)
    benchmark: str = Field(min_length=1)
    selection_metric: RuleMetric = RuleMetric.CAGR
    period: WalkForwardPeriod
    candidates: list[CandidateRule] = Field(min_length=1)


def load_walk_forward_config(yaml_text: str) -> WalkForwardConfig:
    try:
        raw_config = yaml.safe_load(yaml_text)
    except YAMLError as exc:
        raise WalkForwardValidationError(f"invalid YAML: {exc}") from exc
    return WalkForwardConfig.model_validate(raw_config)
