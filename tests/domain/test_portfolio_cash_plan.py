from decimal import Decimal
from types import SimpleNamespace

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

    result = service.build_portfolio_cash_plan(histories, target_cash_ratio=0.4, current_cash_ratio=0.1)

    assert result.active_sell_count == 2
    assert result.target_cash_ratio == 0.4
    assert result.market_risk_score > 0
    assert result.actions[0].symbol == "A"
    assert result.actions[0].action == "전량 현금화"
    assert result.actions[0].suggested_sell_ratio == 1.0
    assert result.actions[1].symbol == "B"
    assert result.actions[1].suggested_sell_ratio >= 0.25
    assert any("목표보다" in line for line in result.summary)
