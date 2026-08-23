"""E2 sell-stage replay harness with cumulative partial-reduction accounting."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from typing import Callable

import pandas as pd

from src.application.domain.strategy.dto import SELL_STAGE_RATIOS, SellStageEnum
from src.application.domain.strategy.sell_strategy_service import SellStrategyService


@dataclass(frozen=True, slots=True)
class SellStageExecution:
    index: int
    stage: str
    target_sold_ratio: float
    incremental_sold_ratio: float
    price: float


@dataclass(frozen=True, slots=True)
class SellStageReplayResult:
    entry_price: float
    final_price: float
    proceeds_per_initial_share: float
    remaining_ratio: float
    total_return: float
    executions: tuple[SellStageExecution, ...]


@dataclass(frozen=True, slots=True)
class SellStageScenario:
    symbol: str
    frame: pd.DataFrame
    entry_index: int

    def __post_init__(self) -> None:
        if self.entry_index < 0 or self.entry_index >= len(self.frame):
            raise ValueError("entry_index is outside the scenario frame")
        entry_timestamp = pd.Timestamp(self.frame.iloc[self.entry_index]["timestamp"])
        ordered = self.frame.sort_values("timestamp").reset_index(drop=True)
        matches = ordered.index[pd.to_datetime(ordered["timestamp"]) == entry_timestamp]
        if len(matches) != 1:
            raise ValueError("entry timestamp must identify exactly one candle")
        object.__setattr__(self, "frame", ordered)
        object.__setattr__(self, "entry_index", int(matches[0]))

    @property
    def entry_date(self) -> date:
        return pd.Timestamp(self.frame.iloc[self.entry_index]["timestamp"]).date()


@dataclass(frozen=True, slots=True)
class SellStageCandidate:
    candidate_id: str
    definition: dict
    service_factory: Callable[[], SellStrategyService]

    @property
    def frozen_hash(self) -> str:
        payload = json.dumps(self.definition, sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode()).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class SellStageFold:
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    selected_candidate_id: str
    selected_hash: str
    train_mean_return: float
    test_mean_return: float
    train_scenarios: int
    test_scenarios: int


class _FrameLoader:
    def __init__(self) -> None:
        self.frame = pd.DataFrame()

    async def load_ohlcv_dataframe(self, **kwargs) -> pd.DataFrame:
        _ = kwargs
        return self.frame.copy()


class SellStageReplay:
    """Replay the production E2 pipeline over expanding, point-in-time frames.

    REDUCE stages are interpreted as cumulative target ratios, preventing the same
    repeated recommendation from liquidating another slice every day.
    """

    def __init__(self, service: SellStrategyService | None = None) -> None:
        self.service = service or SellStrategyService(session=None)
        self.loader = _FrameLoader()
        self.service._data_loader = self.loader

    async def run(
        self,
        symbol: str,
        frame: pd.DataFrame,
        *,
        entry_index: int,
        sell_mode: str = "hybrid",
    ) -> SellStageReplayResult:
        ordered = frame.sort_values("timestamp").reset_index(drop=True)
        if entry_index < 0 or entry_index >= len(ordered) - 1:
            raise ValueError("entry_index must leave at least one forward candle")
        entry_price = float(ordered.iloc[entry_index]["close"])
        if entry_price <= 0:
            raise ValueError("entry price must be positive")

        highest_price = entry_price
        sold_ratio = 0.0
        proceeds = 0.0
        executions: list[SellStageExecution] = []
        for index in range(entry_index + 1, len(ordered)):
            price = float(ordered.iloc[index]["close"])
            highest_price = max(highest_price, price)
            self.loader.frame = ordered.iloc[: index + 1].copy()
            result = await self.service.analyze_sell_signal(
                symbol,
                entry_price=entry_price,
                highest_price=highest_price,
                include_overlays=False,
                sell_mode=sell_mode,
                name=symbol,
                market="STOCK",
            )
            raw_stage = result.final_stage
            stage = raw_stage if isinstance(raw_stage, SellStageEnum) else SellStageEnum(raw_stage)
            low, high = SELL_STAGE_RATIOS[stage]
            target = 1.0 if stage == SellStageEnum.EXIT_ALL else (low + high) / 2.0
            incremental = max(0.0, min(1.0, target) - sold_ratio)
            if incremental > 0:
                proceeds += price * incremental
                sold_ratio += incremental
                executions.append(
                    SellStageExecution(index, stage.value, target, incremental, price)
                )
            if sold_ratio >= 1.0:
                break

        final_price = float(ordered.iloc[-1]["close"])
        remaining = max(0.0, 1.0 - sold_ratio)
        ending_value = proceeds + final_price * remaining
        return SellStageReplayResult(
            entry_price=entry_price,
            final_price=final_price,
            proceeds_per_initial_share=proceeds,
            remaining_ratio=remaining,
            total_return=ending_value / entry_price - 1.0,
            executions=tuple(executions),
        )


class SellStageWalkForwardRunner:
    """Select E2 candidates on train entry cohorts and open test cohorts once."""

    def __init__(self, candidates: list[SellStageCandidate]) -> None:
        if not candidates:
            raise ValueError("at least one E2 candidate is required")
        self.candidates = candidates

    async def run(
        self,
        scenarios: list[SellStageScenario],
        windows: list[tuple[date, date, date, date]],
    ) -> list[SellStageFold]:
        folds: list[SellStageFold] = []
        for train_start, train_end, test_start, test_end in windows:
            train = [s for s in scenarios if train_start <= s.entry_date <= train_end]
            test = [s for s in scenarios if test_start <= s.entry_date <= test_end]
            if not train or not test:
                continue
            ranked: list[tuple[float, SellStageCandidate]] = []
            for candidate in self.candidates:
                returns = await self._evaluate(candidate, train, boundary=train_end)
                if returns:
                    ranked.append((sum(returns) / len(returns), candidate))
            if not ranked:
                continue
            train_mean, selected = max(ranked, key=lambda item: item[0])
            test_returns = await self._evaluate(selected, test, boundary=test_end)
            if not test_returns:
                continue
            folds.append(
                SellStageFold(
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    selected_candidate_id=selected.candidate_id,
                    selected_hash=selected.frozen_hash,
                    train_mean_return=train_mean,
                    test_mean_return=sum(test_returns) / len(test_returns),
                    train_scenarios=len(returns),
                    test_scenarios=len(test_returns),
                )
            )
        return folds

    @staticmethod
    async def _evaluate(
        candidate: SellStageCandidate,
        scenarios: list[SellStageScenario],
        *,
        boundary: date,
    ) -> list[float]:
        returns = []
        for scenario in scenarios:
            timestamps = pd.to_datetime(scenario.frame["timestamp"])
            bounded_frame = scenario.frame.loc[timestamps.dt.date <= boundary].copy()
            if scenario.entry_index >= len(bounded_frame) - 1:
                continue
            result = await SellStageReplay(candidate.service_factory()).run(
                scenario.symbol,
                bounded_frame,
                entry_index=scenario.entry_index,
            )
            returns.append(result.total_return)
        return returns
