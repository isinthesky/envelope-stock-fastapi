from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.application.domain.strategy.strategy_service import StrategyService


def test_build_portfolio_cash_plan_prioritizes_exit_all_and_reduce_stage() -> None:
    service = StrategyService(session=None)
    histories = [
        SimpleNamespace(
            symbol="A",
            name="Alpha",
            sell_stage="EXIT_ALL",
            sell_reasons=["데드크로스", "거래량 급증"],
            entry_price=Decimal("100"),
            current_price=Decimal("88"),
            is_death_cross=True,
            is_volume_sell_signal=True,
            is_volume_spike=True,
            overbought_sell_blocked=False,
            volume_ratio=1.8,
        ),
        SimpleNamespace(
            symbol="B",
            name="Beta",
            sell_stage="REDUCE_1",
            sell_reasons=["과열 초기"],
            entry_price=Decimal("100"),
            current_price=Decimal("112"),
            is_death_cross=False,
            is_volume_sell_signal=False,
            is_volume_spike=False,
            overbought_sell_blocked=False,
            volume_ratio=1.0,
        ),
    ]

    result = service.build_portfolio_cash_plan(
        histories,
        target_cash_ratio=0.4,
        current_cash_ratio=0.1,
    )

    assert result.active_sell_count == 2
    assert result.target_cash_ratio == 0.4
    assert result.cash_gap_ratio == 0.3
    assert result.market_risk_score > 0
    assert result.actions[0].symbol == "A"
    assert result.actions[0].action == "전량 현금화"
    assert result.actions[0].suggested_sell_ratio == 1.0
    assert result.actions[1].symbol == "B"
    assert result.actions[1].suggested_sell_ratio >= 0.30
    assert any("목표보다" in line for line in result.summary)
    assert any("수익 구간 종목" in line for line in result.summary)


def test_build_portfolio_cash_plan_prefers_winners_first_for_cash_creation() -> None:
    service = StrategyService(session=None)
    histories = [
        SimpleNamespace(
            symbol="WIN",
            name="Winner",
            market="KOSPI",
            sell_stage="REDUCE_1",
            sell_reasons=["고점 경고"],
            entry_price=Decimal("100"),
            current_price=Decimal("114"),
            is_death_cross=False,
            is_volume_sell_signal=False,
            is_volume_spike=True,
            overbought_sell_blocked=False,
            volume_ratio=1.4,
        ),
        SimpleNamespace(
            symbol="LOSS",
            name="Loser",
            market="KOSPI",
            sell_stage="REDUCE_1",
            sell_reasons=["리스크 관리"],
            entry_price=Decimal("100"),
            current_price=Decimal("94"),
            is_death_cross=False,
            is_volume_sell_signal=False,
            is_volume_spike=False,
            overbought_sell_blocked=False,
            volume_ratio=1.0,
        ),
    ]

    result = service.build_portfolio_cash_plan(
        histories,
        target_cash_ratio=0.3,
        current_cash_ratio=0.1,
    )

    assert result.actions[0].symbol == "WIN"
    assert result.actions[0].profit_ratio == 0.14
    assert result.actions[0].suggested_sell_ratio >= 0.30
    assert "수익" in (result.actions[0].note or "")


def test_build_portfolio_cash_plan_clamps_non_negative_urgency_for_hold_items() -> None:
    service = StrategyService(session=None)
    histories = [
        SimpleNamespace(
            symbol="HOLD",
            name="Hold Only",
            market="KOSPI",
            sell_stage="HOLD",
            sell_reasons=[],
            entry_price=Decimal("100"),
            current_price=Decimal("100"),
            is_death_cross=False,
            is_volume_sell_signal=False,
            is_volume_spike=False,
            overbought_sell_blocked=True,
            volume_ratio=1.0,
        ),
    ]

    result = service.build_portfolio_cash_plan(histories)

    assert result.actions[0].symbol == "HOLD"
    assert result.actions[0].urgency_score == 0.0
    assert result.market_risk_score == 0.0


def test_insufficient_data_is_not_presented_as_hold() -> None:
    service = StrategyService(session=None)
    histories = [
        SimpleNamespace(
            symbol="NEW",
            name="New Listing",
            market="KOSPI",
            sell_phase="INSUFFICIENT_DATA",
            sell_reasons=["기술 지표 산출에 필요한 데이터 부족"],
            entry_price=Decimal("100"),
            highest_price=Decimal("102"),
            current_price=Decimal("98"),
        ),
    ]

    result = service.build_portfolio_cash_plan(histories)

    action = result.actions[0]
    assert action.analysis_status == "INSUFFICIENT_DATA"
    assert action.sell_stage == "INSUFFICIENT_DATA"
    assert action.action == "분석 보류"
    assert action.suggested_sell_ratio == 0.0


def test_emergency_stop_precedes_insufficient_indicator_data() -> None:
    service = StrategyService(session=None)
    histories = [
        SimpleNamespace(
            symbol="LOSS",
            name="Large Loss",
            market="KOSPI",
            sell_phase="INSUFFICIENT_DATA",
            sell_reasons=["기술 지표 산출에 필요한 데이터 부족"],
            entry_price=Decimal("100"),
            highest_price=Decimal("120"),
            current_price=Decimal("102"),
        ),
    ]

    result = service.build_portfolio_cash_plan(histories)

    action = result.actions[0]
    assert action.analysis_status == "INSUFFICIENT_DATA"
    assert action.sell_stage == "EXIT_ALL"
    assert action.action == "전량 현금화"
    assert action.suggested_sell_ratio == 1.0
    assert any("최고가 대비 15% 손절" in reason for reason in action.reasons)


def _cash_plan_history() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        symbol="LOSS",
        name="Loss",
        entry_price=Decimal("100"),
        highest_price=Decimal("120"),
        current_price=Decimal("110"),
        sell_reasons="[]",
        is_death_cross=False,
    )


@pytest.mark.asyncio
async def test_cash_plan_uses_latest_close_when_full_analysis_fails() -> None:
    model = _cash_plan_history()
    repo = SimpleNamespace(
        get_by_type=AsyncMock(return_value=[model]),
        raise_highest_price=AsyncMock(),
    )
    service = StrategyService(analysis_repo=repo)
    service._universe_repo = lambda session: SimpleNamespace(
        get_by_symbol=AsyncMock(return_value=None)
    )

    with patch(
        "src.application.domain.strategy.sell_strategy_service.SellStrategyService"
    ) as sell_cls:
        sell = sell_cls.return_value
        sell.analyze_sell_signal = AsyncMock(side_effect=RuntimeError("indicators failed"))
        sell.load_latest_close = AsyncMock(return_value=100.0)

        result = await service.get_portfolio_cash_plan.__wrapped__(service, None)

    assert result.actions[0].sell_stage == "EXIT_ALL"
    assert result.actions[0].profit_ratio == 0.0
    repo.raise_highest_price.assert_awaited_once_with(1, Decimal("120.0"), session=None)


@pytest.mark.asyncio
async def test_cash_plan_persists_new_live_peak_atomically() -> None:
    model = _cash_plan_history()
    repo = SimpleNamespace(
        get_by_type=AsyncMock(return_value=[model]),
        raise_highest_price=AsyncMock(),
    )
    service = StrategyService(analysis_repo=repo)
    service._universe_repo = lambda session: SimpleNamespace(
        get_by_symbol=AsyncMock(return_value=None)
    )
    live = SimpleNamespace(
        symbol="LOSS",
        name="Loss",
        final_stage="HOLD",
        sell_stage="HOLD",
        sell_stage_reasons=[],
        sell_reasons=[],
        entry_price=Decimal("100"),
        highest_price=Decimal("140"),
        current_price=Decimal("140"),
        is_death_cross=False,
        is_volume_sell_signal=False,
        is_volume_spike=False,
        is_volume_peak=False,
        overbought_sell_blocked=False,
        volume_ratio=1.0,
    )

    with patch(
        "src.application.domain.strategy.sell_strategy_service.SellStrategyService"
    ) as sell_cls:
        sell_cls.return_value.analyze_sell_signal = AsyncMock(return_value=live)

        await service.get_portfolio_cash_plan.__wrapped__(service, None)

    repo.raise_highest_price.assert_awaited_once_with(1, Decimal("140"), session=None)
