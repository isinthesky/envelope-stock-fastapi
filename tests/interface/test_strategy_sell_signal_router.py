from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.common.exceptions import ServiceUnavailableError
from src.application.interface.api.strategy_router import analyze_sell_signal


@pytest.mark.asyncio
async def test_explicit_entry_price_still_uses_persisted_position_peak() -> None:
    result = SimpleNamespace(name="삼성전자")
    service = SimpleNamespace(
        get_symbol_state_for_sell_signal=AsyncMock(
            return_value={
                "entry_price": 90.0,
                "highest_price": 140.0,
                "trailing_stop_activated": True,
            }
        ),
        analyze_sell_signal=AsyncMock(return_value=result),
    )

    await analyze_sell_signal(
        symbol="005930",
        service=service,
        market_data_service=SimpleNamespace(),
        stoch_overbought=70.0,
        rsi_overbought=70.0,
        entry_price=100.0,
        strategy_id=1,
    )

    service.analyze_sell_signal.assert_awaited_once_with(
        symbol="005930",
        stoch_overbought=70.0,
        rsi_overbought=70.0,
        entry_price=100.0,
        highest_price=140.0,
        trailing_stop_activated=True,
    )


@pytest.mark.asyncio
async def test_strategy_state_lookup_failure_is_not_silently_ignored() -> None:
    service = SimpleNamespace(
        get_symbol_state_for_sell_signal=AsyncMock(side_effect=RuntimeError("db down"))
    )

    with pytest.raises(ServiceUnavailableError, match="persisted position state"):
        await analyze_sell_signal(
            symbol="005930",
            service=service,
            market_data_service=SimpleNamespace(),
            stoch_overbought=70.0,
            rsi_overbought=70.0,
            entry_price=100.0,
            strategy_id=1,
        )
