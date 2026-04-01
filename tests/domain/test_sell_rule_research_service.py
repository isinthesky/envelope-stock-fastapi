from datetime import datetime

import pandas as pd

from src.application.domain.strategy.sell_rule_research_service import (
    SellPeakRuleResearchService,
)


async def test_research_service_prefers_combo_peak_rule() -> None:
    service = SellPeakRuleResearchService(session=None)  # type: ignore[arg-type]

    async def fake_resolve(symbols=None):
        _ = symbols
        return [{"symbol": "005930", "name": "삼성전자", "market": "KOSPI"}]

    async def fake_load(symbol: str, market: str | None, start_date: str, end_date: str) -> pd.DataFrame:
        _ = symbol, market, start_date, end_date
        rows = []
        base = datetime(2024, 1, 1)
        for i in range(80):
            rows.append(
                {
                    "timestamp": pd.Timestamp(base) + pd.Timedelta(days=i),
                    "close": 100 + i,
                    "high_52week_ratio": 0.99 if i % 10 == 0 else 0.94,
                    "is_52week_high": i % 10 == 0,
                    "personal_buy_days_5d": 5 if i % 10 == 0 else 2,
                    "personal_buy_ratio_5d_to_volume": 0.22 if i % 10 == 0 else 0.05,
                    "market_credit_change_ratio": 0.011 if i % 10 == 0 else 0.001,
                    "market_credit_recent_high_ratio": 0.997 if i % 10 == 0 else 0.96,
                    "stoch_k": 88 if i % 10 == 0 else 55,
                }
            )
        return pd.DataFrame(rows)

    def fake_label(df: pd.DataFrame) -> pd.DataFrame:
        labeled = df.copy()
        labeled["is_peak_label"] = labeled["is_52week_high"]
        labeled["future_drawdown_10d"] = labeled["is_52week_high"].map(lambda v: 0.09 if v else 0.02)
        labeled["future_return_10d"] = labeled["is_52week_high"].map(lambda v: 0.01 if v else 0.04)
        return labeled

    service._resolve_symbols = fake_resolve  # type: ignore[method-assign]
    service._load_symbol_frame = fake_load  # type: ignore[method-assign]
    service._label_local_peaks = fake_label  # type: ignore[method-assign]

    result = await service.research_top_signal_rules()

    assert result["top_rule"] is not None
    assert result["top_rule"]["rule_id"] == "combo_peak_near_high"


def test_evaluate_peak_rule_inputs_returns_combo_bonus() -> None:
    result = SellPeakRuleResearchService.evaluate_peak_rule_inputs(
        personal_buy_days_5d=5,
        personal_buy_ratio_5d_to_volume=0.23,
        market_credit_change_ratio=0.011,
        market_credit_recent_high_ratio=0.996,
        stoch_k=87.0,
        is_52week_high=True,
        high_52week_ratio=1.0,
    )

    assert result["market_credit_score"] == 8.0
    assert result["combo_bonus"] == 6.0
    assert result["risk_combo_extreme"] is True
    assert result["risk_combo_peak"] is True



def test_evaluate_peak_rule_inputs_keeps_stoch_combo_as_research_only() -> None:
    result = SellPeakRuleResearchService.evaluate_peak_rule_inputs(
        personal_buy_days_5d=5,
        personal_buy_ratio_5d_to_volume=0.23,
        market_credit_change_ratio=0.011,
        market_credit_recent_high_ratio=0.996,
        stoch_k=87.0,
        is_52week_high=False,
        high_52week_ratio=0.95,
    )

    assert result["risk_combo_peak"] is False
    assert result["risk_combo_extreme"] is False
    assert result["research_combo_peak_with_stoch"] is True
    assert result["combo_bonus"] == 0.0
    assert any("[research]" in reason for reason in result["combo_reasons"])
