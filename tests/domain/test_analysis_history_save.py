from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.application.domain.strategy.dto import AnalysisHistoryCreateDTO
from src.application.domain.strategy.strategy_service import StrategyService


class _FakeAnalysisRepo:
    def __init__(self) -> None:
        self.create_kwargs = None

    async def create(self, **kwargs):
        self.create_kwargs = kwargs
        now = datetime.now(timezone.utc)
        return SimpleNamespace(
            id=1,
            analysis_type=kwargs["analysis_type"],
            symbol=kwargs["symbol"],
            name=kwargs.get("name"),
            current_price=kwargs["current_price"],
            ma_short=kwargs.get("ma_short"),
            ma_long=kwargs.get("ma_long"),
            ma_gap_ratio=kwargs.get("ma_gap_ratio"),
            stoch_k=kwargs.get("stoch_k"),
            stoch_d=kwargs.get("stoch_d"),
            gc_state=kwargs.get("gc_state"),
            is_gc_active=kwargs.get("is_gc_active"),
            rsi=kwargs.get("rsi"),
            is_death_cross=kwargs.get("is_death_cross"),
            is_stoch_overbought=kwargs.get("is_stoch_overbought"),
            is_rsi_overbought=kwargs.get("is_rsi_overbought"),
            sell_phase=kwargs.get("sell_phase"),
            sell_reasons=kwargs.get("sell_reasons"),
            analyzed_at=kwargs["analyzed_at"],
            entry_price=kwargs.get("entry_price"),
            note=kwargs.get("note"),
            is_active=kwargs.get("is_active"),
            candle_count=kwargs.get("candle_count"),
            created_at=now,
            updated_at=now,
        )


@pytest.mark.asyncio
async def test_save_analysis_history_persists_entry_price_note_and_candle_count() -> None:
    repo = _FakeAnalysisRepo()
    service = StrategyService()
    service.analysis_repo = repo
    dto = AnalysisHistoryCreateDTO(
        analysis_type="sell",
        symbol="005930",
        name="삼성전자",
        current_price=Decimal("65000"),
        sell_phase="PHASE_4",
        sell_reasons=["데드크로스 발생"],
        entry_price=Decimal("70000"),
        note="regression",
        is_active=True,
        candle_count=300,
    )

    result = await service.save_analysis_history.__wrapped__(service, None, dto)

    assert repo.create_kwargs is not None
    assert repo.create_kwargs["entry_price"] == Decimal("70000")
    assert repo.create_kwargs["note"] == "regression"
    assert repo.create_kwargs["candle_count"] == 300
    assert result.entry_price == Decimal("70000")
    assert result.note == "regression"
    assert result.candle_count == 300


def test_history_to_dto_includes_candle_count_without_sell_result() -> None:
    service = StrategyService()
    now = datetime.now(timezone.utc)
    model = SimpleNamespace(
        id=1,
        analysis_type="sell",
        symbol="005930",
        name="삼성전자",
        current_price=Decimal("65000"),
        ma_short=Decimal("64000"),
        ma_long=Decimal("66000"),
        ma_gap_ratio=Decimal("-3.03"),
        stoch_k=Decimal("82.1"),
        stoch_d=Decimal("79.5"),
        gc_state=None,
        is_gc_active=None,
        rsi=Decimal("71.2"),
        is_death_cross=True,
        is_stoch_overbought=True,
        is_rsi_overbought=True,
        sell_phase="PHASE_4",
        sell_reasons='["데드크로스 발생"]',
        analyzed_at=now,
        entry_price=Decimal("70000"),
        note="dto regression",
        is_active=True,
        candle_count=300,
        created_at=now,
        updated_at=now,
    )

    result = service._history_to_dto(model)

    assert result.candle_count == 300
    assert result.entry_price == Decimal("70000")
    assert result.note == "dto regression"
