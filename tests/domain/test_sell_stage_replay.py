from types import SimpleNamespace

import pandas as pd
import pytest

from src.application.domain.backtest.sell_stage_replay import (
    SellStageCandidate,
    SellStageReplay,
    SellStageScenario,
    SellStageWalkForwardRunner,
)
from src.application.domain.strategy.dto import SellStageEnum


class _StageService:
    _data_loader = None

    async def analyze_sell_signal(self, symbol: str, **kwargs):
        _ = symbol, kwargs
        size = len(self._data_loader.frame)
        if size == 3:
            return SimpleNamespace(final_stage=SellStageEnum.REDUCE_1)
        if size == 4:
            return SimpleNamespace(final_stage=SellStageEnum.REDUCE_1)
        if size == 5:
            return SimpleNamespace(final_stage=SellStageEnum.REDUCE_2)
        return SimpleNamespace(final_stage=SellStageEnum.EXIT_ALL)


async def test_replay_treats_reduce_stages_as_cumulative_targets() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=6, freq="D"),
            "close": [100, 100, 110, 105, 95, 90],
        }
    )
    replay = SellStageReplay(service=_StageService())  # type: ignore[arg-type]

    result = await replay.run("005930", frame, entry_index=1)

    assert [row.incremental_sold_ratio for row in result.executions] == pytest.approx(
        [0.25, 0.10, 0.65]
    )
    assert result.remaining_ratio == 0.0
    assert result.executions[1].stage == "REDUCE_2"


class _ConstantStageService:
    _data_loader = None

    def __init__(self, stage: SellStageEnum) -> None:
        self.stage = stage

    async def analyze_sell_signal(self, symbol: str, **kwargs):
        _ = symbol, kwargs
        return SimpleNamespace(final_stage=self.stage)


async def test_walk_forward_freezes_train_winner_for_test_cohort() -> None:
    train_frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=4, freq="D"),
            "close": [100, 100, 90, 80],
        }
    )
    test_frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-02-01", periods=4, freq="D"),
            "close": [100, 100, 95, 85],
        }
    )
    candidates = [
        SellStageCandidate(
            "hold",
            {"stage": "HOLD"},
            lambda: _ConstantStageService(SellStageEnum.HOLD),  # type: ignore[arg-type]
        ),
        SellStageCandidate(
            "exit",
            {"stage": "EXIT_ALL"},
            lambda: _ConstantStageService(SellStageEnum.EXIT_ALL),  # type: ignore[arg-type]
        ),
    ]
    runner = SellStageWalkForwardRunner(candidates)

    folds = await runner.run(
        [
            SellStageScenario("A", train_frame, 1),
            SellStageScenario("B", test_frame, 1),
        ],
        [
            (
                pd.Timestamp("2026-01-01").date(),
                pd.Timestamp("2026-01-31").date(),
                pd.Timestamp("2026-02-01").date(),
                pd.Timestamp("2026-02-28").date(),
            )
        ],
    )

    assert folds[0].selected_candidate_id == "exit"
    assert folds[0].selected_hash == candidates[1].frozen_hash
    assert folds[0].test_mean_return == pytest.approx(-0.05)


async def test_walk_forward_does_not_use_prices_after_fold_boundary() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=6, freq="D"),
            "close": [100, 100, 90, 80, 200, 300],
        }
    )
    candidate = SellStageCandidate(
        "hold",
        {"stage": "HOLD"},
        lambda: _ConstantStageService(SellStageEnum.HOLD),  # type: ignore[arg-type]
    )
    runner = SellStageWalkForwardRunner([candidate])

    returns = await runner._evaluate(
        candidate,
        [SellStageScenario("A", frame, 1)],
        boundary=pd.Timestamp("2026-01-04").date(),
    )

    assert returns == pytest.approx([-0.20])


def test_scenario_preserves_entry_timestamp_when_input_frame_is_unsorted() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-03", "2026-01-01", "2026-01-02"]),
            "close": [103, 101, 102],
        }
    )

    scenario = SellStageScenario("A", frame, 0)

    assert scenario.entry_date == pd.Timestamp("2026-01-03").date()
    assert scenario.entry_index == 2
    assert scenario.frame["timestamp"].is_monotonic_increasing
