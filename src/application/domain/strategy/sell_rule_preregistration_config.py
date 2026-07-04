# -*- coding: utf-8 -*-
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.application.domain.strategy.sell_rule_research_service import (
    DEFAULT_PREREGISTERED_SYMBOL_LIMIT,
    PreRegisteredSellRuleCandidate,
    SellRulePreRegistrationConfig,
)


@dataclass(frozen=True, slots=True)
class SellRulePreRegistrationConfigError(Exception):
    reason: str

    def __str__(self) -> str:
        return self.reason


def build_preregistered_sell_rule_config(
    symbols: str | None,
    start_date: str,
    end_date: str,
    symbol_limit: int = DEFAULT_PREREGISTERED_SYMBOL_LIMIT,
) -> SellRulePreRegistrationConfig:
    try:
        start_dt = datetime.strptime(start_date, "%Y%m%d").date()
        end_dt = datetime.strptime(end_date, "%Y%m%d").date()
    except ValueError as exc:
        raise SellRulePreRegistrationConfigError(
            "start_date/end_date must be YYYYMMDD",
        ) from exc

    if end_dt <= start_dt:
        raise SellRulePreRegistrationConfigError("end_date must be after start_date")
    if (end_dt - start_dt).days < 4:
        raise SellRulePreRegistrationConfigError("date range must be at least 4 days")

    train_end = start_dt + timedelta(days=(end_dt - start_dt).days // 2)
    window = {
        "train_start_date": start_dt.strftime("%Y%m%d"),
        "train_end_date": train_end.strftime("%Y%m%d"),
        "test_start_date": (train_end + timedelta(days=1)).strftime("%Y%m%d"),
        "test_end_date": end_dt.strftime("%Y%m%d"),
    }
    symbol_list = (
        tuple(symbol.strip() for symbol in symbols.split(",") if symbol.strip())
        if symbols
        else None
    )
    if symbol_list and len(symbol_list) > symbol_limit:
        raise SellRulePreRegistrationConfigError(
            f"symbols must contain at most {symbol_limit} items",
        )
    candidates = (
        PreRegisteredSellRuleCandidate.model_validate(
            {
                "candidate_id": "current-overlay-score-v1",
                "description": "current overlay score frozen before OOS test",
                "rule_type": "current_overlay_score",
                "thresholds": [
                    {"field": "current_overlay_score", "operator": "gte", "value": 8.0},
                ],
                "evaluation_window": window,
            }
        ),
        PreRegisteredSellRuleCandidate.model_validate(
            {
                "candidate_id": "credit-personal-near-high-v1",
                "description": "personal flow plus credit heat near 52-week high",
                "rule_type": "all_thresholds",
                "thresholds": [
                    {"field": "personal_buy_days_5d", "operator": "gte", "value": 4.0},
                    {
                        "field": "personal_buy_ratio_5d_to_volume",
                        "operator": "gte",
                        "value": 0.15,
                    },
                    {"field": "market_credit_change_ratio", "operator": "gte", "value": 0.008},
                    {
                        "field": "market_credit_recent_high_ratio",
                        "operator": "gte",
                        "value": 0.99,
                    },
                    {"field": "high_52week_ratio", "operator": "gte", "value": 0.98},
                ],
                "evaluation_window": window,
            }
        ),
    )
    return SellRulePreRegistrationConfig(
        symbols=symbol_list,
        candidates=candidates,
        symbol_limit=symbol_limit,
    )
