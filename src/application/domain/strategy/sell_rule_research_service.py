# -*- coding: utf-8 -*-
"""
Sell peak rule research service

저장된 OHLCV, 개인 수급, 시장 신용 데이터를 조합해
로컬 고점/과열 신호 후보를 평가한다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Callable, Self, assert_never

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.stock_universe import StockUniverseModel
from src.adapters.database.repositories.analysis_history_repository import (
    AnalysisHistoryRepository,
)
from src.adapters.database.repositories.market_credit_snapshot_repository import (
    MarketCreditSnapshotRepository,
)
from src.adapters.database.repositories.ohlcv_repository import OHLCVRepository
from src.adapters.database.repositories.personal_flow_snapshot_repository import (
    PersonalFlowSnapshotRepository,
)
from src.application.common.indicators import TechnicalIndicators


@dataclass(frozen=True)
class SellRuleCandidate:
    """후보 매도 규칙"""

    rule_id: str
    description: str
    evaluator: Callable[[pd.Series], bool]


class SellRuleCandidateType(StrEnum):
    ALL_THRESHOLDS = "all_thresholds"
    CURRENT_OVERLAY_SCORE = "current_overlay_score"


class SellRuleThresholdOperator(StrEnum):
    GTE = "gte"
    GT = "gt"
    LTE = "lte"
    LT = "lt"
    EQ = "eq"
    IS_TRUE = "is_true"


class SellRuleThresholdDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    operator: SellRuleThresholdOperator
    value: float | bool | str | None = None


class SellRuleEvaluationWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    train_start_date: str
    train_end_date: str
    test_start_date: str
    test_end_date: str

    @model_validator(mode="after")
    def validate_ordered_windows(self) -> Self:
        train_start = datetime.strptime(self.train_start_date, "%Y%m%d")
        train_end = datetime.strptime(self.train_end_date, "%Y%m%d")
        test_start = datetime.strptime(self.test_start_date, "%Y%m%d")
        test_end = datetime.strptime(self.test_end_date, "%Y%m%d")
        if train_start > train_end:
            raise ValueError("train_start_date must be on or before train_end_date")
        if test_start > test_end:
            raise ValueError("test_start_date must be on or before test_end_date")
        if train_end >= test_start:
            raise ValueError("train window must end before out-of-sample test window starts")
        return self


class PreRegisteredSellRuleCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    description: str
    rule_type: SellRuleCandidateType = SellRuleCandidateType.ALL_THRESHOLDS
    thresholds: tuple[SellRuleThresholdDefinition, ...] = Field(min_length=1)
    evaluation_window: SellRuleEvaluationWindow

    @property
    def definition_hash(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class SellRuleResearchFixtureRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    biz_date: str
    personal_buy_days_5d: int | None = None
    personal_buy_ratio_5d_to_volume: float | None = None
    market_credit_change_ratio: float | None = None
    market_credit_recent_high_ratio: float | None = None
    stoch_k: float | None = None
    is_52week_high: bool = False
    high_52week_ratio: float | None = None
    is_peak_label: bool
    future_drawdown_10d: float
    future_return_10d: float


class SellRulePreRegistrationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbols: tuple[str, ...] | None = None
    candidates: tuple[PreRegisteredSellRuleCandidate, ...] = Field(min_length=1)
    fixture_rows: tuple[SellRuleResearchFixtureRow, ...] | None = None


class SellPeakRuleResearchService:
    """저장된 리스크/가격 데이터 기반 매도 피크 규칙 리서치"""

    PEAK_LOOKAHEAD_DAYS = 10
    PEAK_DROP_THRESHOLD = 0.06
    MIN_ROWS_PER_SYMBOL = 60

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def evaluate_peak_rule_inputs(
        *,
        personal_buy_days_5d: int | None,
        personal_buy_ratio_5d_to_volume: float | None,
        market_credit_change_ratio: float | None,
        market_credit_recent_high_ratio: float | None,
        stoch_k: float | None,
        is_52week_high: bool,
        high_52week_ratio: float | None,
    ) -> dict[str, Any]:
        personal_strong = (
            personal_buy_days_5d is not None
            and personal_buy_days_5d >= 4
            and personal_buy_ratio_5d_to_volume is not None
            and personal_buy_ratio_5d_to_volume >= 0.15
        )
        personal_extreme = (
            personal_buy_days_5d is not None
            and personal_buy_days_5d >= 5
            and personal_buy_ratio_5d_to_volume is not None
            and personal_buy_ratio_5d_to_volume >= 0.20
        )
        market_credit_hot = (
            market_credit_change_ratio is not None
            and market_credit_change_ratio >= 0.008
            and market_credit_recent_high_ratio is not None
            and market_credit_recent_high_ratio >= 0.99
        )
        market_credit_extreme = (
            market_credit_change_ratio is not None
            and market_credit_change_ratio >= 0.01
            and market_credit_recent_high_ratio is not None
            and market_credit_recent_high_ratio >= 0.995
        )
        near_high = bool(
            is_52week_high
            or (high_52week_ratio is not None and high_52week_ratio >= 0.98)
        )
        stoch_hot = stoch_k is not None and stoch_k >= 85.0

        risk_combo_peak = personal_strong and market_credit_hot and near_high
        risk_combo_extreme = personal_extreme and market_credit_extreme and near_high
        research_combo_peak_with_stoch = personal_extreme and market_credit_extreme and stoch_hot
        research_credit_hot_personal_strong = personal_strong and market_credit_hot

        market_credit_score = 0.0
        market_credit_reasons: list[str] = []
        if market_credit_extreme:
            market_credit_score = 8.0
            market_credit_reasons.append("시장 신용 과열 강함 (증가율 + 고점권 동시 충족)")
        elif market_credit_hot:
            market_credit_score = 5.0
            market_credit_reasons.append("시장 신용 과열 경고 (증가율/고점권)")

        combo_bonus = 0.0
        combo_reasons: list[str] = []
        if risk_combo_extreme:
            combo_bonus = 6.0
            combo_reasons.append("개인 수급 + 시장 신용 + 고점권 과열 정렬")
        elif risk_combo_peak:
            combo_bonus = 3.0
            combo_reasons.append("개인 수급 + 시장 신용 + 고점권 정렬")
        elif research_combo_peak_with_stoch:
            combo_reasons.append("[research] 개인 수급 + 시장 신용 + Stoch 과열 정렬")
        elif research_credit_hot_personal_strong:
            combo_reasons.append("[research] 개인 수급 + 시장 신용 동시 과열")

        return {
            "personal_strong": personal_strong,
            "personal_extreme": personal_extreme,
            "market_credit_hot": market_credit_hot,
            "market_credit_extreme": market_credit_extreme,
            "near_high": near_high,
            "stoch_hot": stoch_hot,
            "risk_combo_peak": risk_combo_peak,
            "risk_combo_extreme": risk_combo_extreme,
            "research_combo_peak_with_stoch": research_combo_peak_with_stoch,
            "research_credit_hot_personal_strong": research_credit_hot_personal_strong,
            "market_credit_score": market_credit_score,
            "market_credit_reasons": market_credit_reasons,
            "combo_bonus": combo_bonus,
            "combo_reasons": combo_reasons,
        }

    async def _resolve_symbols(
        self,
        symbols: list[str] | None = None,
    ) -> list[dict[str, str | None]]:
        if symbols:
            stmt = select(
                StockUniverseModel.symbol,
                StockUniverseModel.name,
                StockUniverseModel.market,
            ).where(StockUniverseModel.symbol.in_(symbols))
            result = await self.session.execute(stmt)
            mapped = {
                row[0]: {"symbol": row[0], "name": row[1], "market": row[2]}
                for row in result.all()
            }
            return [
                mapped.get(symbol, {"symbol": symbol, "name": None, "market": None})
                for symbol in symbols
            ]

        rows = await AnalysisHistoryRepository(self.session).get_active_symbols_with_names(
            "sell",
            session=self.session,
        )
        return rows

    async def _load_symbol_frame(
        self,
        symbol: str,
        market: str | None,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        start_dt = datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.strptime(end_date, "%Y%m%d") + timedelta(days=1)

        ohlcv_df = await OHLCVRepository(self.session).get_candles_to_dataframe(
            symbol=symbol,
            start_date=start_dt,
            end_date=end_dt,
            interval="1d",
        )
        if ohlcv_df.empty:
            return pd.DataFrame()

        ohlcv_df = ohlcv_df.copy()
        ohlcv_df["biz_date"] = ohlcv_df["timestamp"].dt.strftime("%Y%m%d")
        ohlcv_df = TechnicalIndicators.prepare_golden_cross_indicators(
            ohlcv_df,
            short_ma_period=55,
            long_ma_period=165,
            stoch_k_period=14,
            stoch_d_period=3,
        )
        ohlcv_df["rolling_20_high"] = ohlcv_df["close"].rolling(20, min_periods=5).max()
        ohlcv_df["high_52w"] = ohlcv_df["high"].rolling(252, min_periods=20).max()
        ohlcv_df["high_52week_ratio"] = ohlcv_df["close"] / ohlcv_df["high_52w"]
        ohlcv_df["is_52week_high"] = ohlcv_df["high_52week_ratio"] >= 0.999

        personal_rows = await PersonalFlowSnapshotRepository(self.session).get_by_symbol_between(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            session=self.session,
        )
        personal_df = pd.DataFrame(
            [
                {
                    "biz_date": row.biz_date,
                    "individual_net_buy": row.individual_net_buy or 0,
                    "personal_volume": row.trading_volume,
                }
                for row in personal_rows
            ]
        )
        if not personal_df.empty:
            personal_df = personal_df.sort_values("biz_date")
            personal_df["recent_5d_personal_net_buy"] = (
                personal_df["individual_net_buy"].rolling(5, min_periods=1).sum()
            )
            personal_df["personal_buy_days_5d"] = (
                (personal_df["individual_net_buy"] > 0).astype(int).rolling(5, min_periods=1).sum()
            )
            volume_series = personal_df["personal_volume"].replace(0, pd.NA)
            personal_df["personal_buy_ratio_5d_to_volume"] = (
                personal_df["recent_5d_personal_net_buy"] / volume_series
            )

        market_label = "전체"
        if (market or "").upper() == "KOSPI":
            market_label = "유가증권"
        elif (market or "").upper() == "KOSDAQ":
            market_label = "코스닥"

        credit_rows = await MarketCreditSnapshotRepository(self.session).get_by_market_between(
            market_label=market_label,
            start_date=start_date,
            end_date=end_date,
            session=self.session,
        )
        credit_df = pd.DataFrame(
            [
                {
                    "biz_date": row.biz_date,
                    "market_credit_balance_million": row.balance_million,
                }
                for row in credit_rows
            ]
        )
        if not credit_df.empty:
            credit_df = credit_df.sort_values("biz_date")
            prev_balance = credit_df["market_credit_balance_million"].shift(1)
            credit_df["market_credit_change_ratio"] = (
                credit_df["market_credit_balance_million"] - prev_balance
            ) / prev_balance.replace(0, pd.NA)
            rolling_high = credit_df["market_credit_balance_million"].rolling(5, min_periods=1).max()
            credit_df["market_credit_recent_high_ratio"] = (
                credit_df["market_credit_balance_million"] / rolling_high.replace(0, pd.NA)
            )

        merged = ohlcv_df.merge(
            personal_df[
                [
                    "biz_date",
                    "recent_5d_personal_net_buy",
                    "personal_buy_days_5d",
                    "personal_buy_ratio_5d_to_volume",
                ]
            ]
            if not personal_df.empty
            else pd.DataFrame(columns=["biz_date"]),
            on="biz_date",
            how="left",
        ).merge(
            credit_df[
                [
                    "biz_date",
                    "market_credit_change_ratio",
                    "market_credit_recent_high_ratio",
                ]
            ]
            if not credit_df.empty
            else pd.DataFrame(columns=["biz_date"]),
            on="biz_date",
            how="left",
        )
        return merged.sort_values("timestamp").reset_index(drop=True)

    def _label_local_peaks(self, df: pd.DataFrame) -> pd.DataFrame:
        labeled = df.copy()
        future_min = (
            labeled["close"]
            .shift(-1)
            .rolling(self.PEAK_LOOKAHEAD_DAYS, min_periods=1)
            .min()
            .shift(-(self.PEAK_LOOKAHEAD_DAYS - 1))
        )
        future_max = (
            labeled["close"]
            .shift(-1)
            .rolling(self.PEAK_LOOKAHEAD_DAYS, min_periods=1)
            .max()
            .shift(-(self.PEAK_LOOKAHEAD_DAYS - 1))
        )
        labeled["future_min_close"] = future_min
        labeled["future_max_close"] = future_max
        labeled["future_drawdown_10d"] = (labeled["close"] - future_min) / labeled["close"]
        labeled["future_return_10d"] = (future_max - labeled["close"]) / labeled["close"]
        labeled["is_peak_label"] = (
            (labeled["future_drawdown_10d"] >= self.PEAK_DROP_THRESHOLD)
            & (labeled["high_52week_ratio"] >= 0.97)
        )
        return labeled

    @staticmethod
    def _candidate_rules() -> list[SellRuleCandidate]:
        return [
            SellRuleCandidate(
                rule_id="combo_peak_near_high",
                description="개인수급 + 시장신용 + 고점권",
                evaluator=lambda row: bool(
                    row.get("personal_buy_days_5d", 0) >= 4
                    and (row.get("personal_buy_ratio_5d_to_volume") or 0) >= 0.15
                    and (row.get("market_credit_change_ratio") or 0) >= 0.008
                    and (row.get("market_credit_recent_high_ratio") or 0) >= 0.99
                    and (
                        bool(row.get("is_52week_high"))
                        or (row.get("high_52week_ratio") or 0) >= 0.98
                    )
                ),
            ),
            SellRuleCandidate(
                rule_id="credit_hot_personal_strong",
                description="[research] 개인수급 강함 + 시장신용 과열",
                evaluator=lambda row: bool(
                    row.get("personal_buy_days_5d", 0) >= 4
                    and (row.get("personal_buy_ratio_5d_to_volume") or 0) >= 0.15
                    and (row.get("market_credit_change_ratio") or 0) >= 0.008
                    and (row.get("market_credit_recent_high_ratio") or 0) >= 0.99
                ),
            ),
            SellRuleCandidate(
                rule_id="combo_peak_with_stoch",
                description="[research] 개인수급 극단 + 시장신용 극단 + Stoch 과열",
                evaluator=lambda row: bool(
                    row.get("personal_buy_days_5d", 0) >= 5
                    and (row.get("personal_buy_ratio_5d_to_volume") or 0) >= 0.20
                    and (row.get("market_credit_change_ratio") or 0) >= 0.01
                    and (row.get("market_credit_recent_high_ratio") or 0) >= 0.995
                    and (row.get("stoch_k") or 0) >= 85
                ),
            ),
        ]

    def _score_candidate(self, rule: SellRuleCandidate, df: pd.DataFrame) -> dict[str, Any]:
        triggered = df[df.apply(rule.evaluator, axis=1)].copy()
        trigger_count = len(triggered)
        if trigger_count == 0:
            return {
                "rule_id": rule.rule_id,
                "description": rule.description,
                "trigger_count": 0,
                "peak_hit_count": 0,
                "precision": 0.0,
                "avg_future_drawdown_10d": 0.0,
                "avg_future_return_10d": 0.0,
                "score": 0.0,
            }

        peak_hit_count = int(triggered["is_peak_label"].sum())
        precision = peak_hit_count / trigger_count if trigger_count else 0.0
        avg_drawdown = float(triggered["future_drawdown_10d"].fillna(0).mean())
        avg_return = float(triggered["future_return_10d"].fillna(0).mean())
        score = precision * 100 + avg_drawdown * 100 - avg_return * 30 + min(trigger_count, 20) * 0.5
        return {
            "rule_id": rule.rule_id,
            "description": rule.description,
            "trigger_count": trigger_count,
            "peak_hit_count": peak_hit_count,
            "precision": round(precision, 4),
            "avg_future_drawdown_10d": round(avg_drawdown, 4),
            "avg_future_return_10d": round(avg_return, 4),
            "score": round(score, 2),
        }

    @staticmethod
    def _frame_for_window(
        df: pd.DataFrame,
        *,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        dated = df.copy()
        if "biz_date" not in dated.columns:
            dated["biz_date"] = pd.to_datetime(dated["timestamp"]).dt.strftime("%Y%m%d")
        return dated[(dated["biz_date"] >= start_date) & (dated["biz_date"] <= end_date)]

    @staticmethod
    def _row_float(row: pd.Series, field: str) -> float | None:
        value = row.get(field)
        if pd.isna(value):
            return None
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, int | float):
            return float(value)
        return None

    @staticmethod
    def _row_bool(row: pd.Series, field: str) -> bool:
        value = row.get(field)
        if pd.isna(value):
            return False
        return bool(value)

    @staticmethod
    def _current_overlay_score(row: pd.Series) -> float:
        overlay = SellPeakRuleResearchService.evaluate_peak_rule_inputs(
            personal_buy_days_5d=(
                int(row["personal_buy_days_5d"])
                if not pd.isna(row.get("personal_buy_days_5d"))
                else None
            ),
            personal_buy_ratio_5d_to_volume=SellPeakRuleResearchService._row_float(
                row,
                "personal_buy_ratio_5d_to_volume",
            ),
            market_credit_change_ratio=SellPeakRuleResearchService._row_float(
                row,
                "market_credit_change_ratio",
            ),
            market_credit_recent_high_ratio=SellPeakRuleResearchService._row_float(
                row,
                "market_credit_recent_high_ratio",
            ),
            stoch_k=SellPeakRuleResearchService._row_float(row, "stoch_k"),
            is_52week_high=SellPeakRuleResearchService._row_bool(row, "is_52week_high"),
            high_52week_ratio=SellPeakRuleResearchService._row_float(row, "high_52week_ratio"),
        )
        return float(overlay["market_credit_score"]) + float(overlay["combo_bonus"])

    @staticmethod
    def _threshold_value(
        row: pd.Series,
        threshold: SellRuleThresholdDefinition,
    ) -> float | bool | str | None:
        if threshold.field == "current_overlay_score":
            return SellPeakRuleResearchService._current_overlay_score(row)
        value = row.get(threshold.field)
        if pd.isna(value):
            return None
        if isinstance(value, bool | str):
            return value
        if isinstance(value, int | float):
            return float(value)
        return None

    @staticmethod
    def _passes_threshold(row: pd.Series, threshold: SellRuleThresholdDefinition) -> bool:
        actual = SellPeakRuleResearchService._threshold_value(row, threshold)
        expected = threshold.value
        match threshold.operator:
            case SellRuleThresholdOperator.GTE:
                return (
                    isinstance(actual, int | float)
                    and isinstance(expected, int | float)
                    and actual >= expected
                )
            case SellRuleThresholdOperator.GT:
                return (
                    isinstance(actual, int | float)
                    and isinstance(expected, int | float)
                    and actual > expected
                )
            case SellRuleThresholdOperator.LTE:
                return (
                    isinstance(actual, int | float)
                    and isinstance(expected, int | float)
                    and actual <= expected
                )
            case SellRuleThresholdOperator.LT:
                return (
                    isinstance(actual, int | float)
                    and isinstance(expected, int | float)
                    and actual < expected
                )
            case SellRuleThresholdOperator.EQ:
                return actual == expected
            case SellRuleThresholdOperator.IS_TRUE:
                return bool(actual) is True
            case _ as unreachable:
                assert_never(unreachable)

    @staticmethod
    def _evaluate_preregistered_candidate(
        row: pd.Series,
        candidate: PreRegisteredSellRuleCandidate,
    ) -> bool:
        match candidate.rule_type:
            case SellRuleCandidateType.ALL_THRESHOLDS | SellRuleCandidateType.CURRENT_OVERLAY_SCORE:
                return all(
                    SellPeakRuleResearchService._passes_threshold(row, threshold)
                    for threshold in candidate.thresholds
                )
            case _ as unreachable:
                assert_never(unreachable)

    def _score_preregistered_candidate(
        self,
        candidate: PreRegisteredSellRuleCandidate,
        df: pd.DataFrame,
    ) -> dict[str, Any]:
        test_frame = self._frame_for_window(
            df,
            start_date=candidate.evaluation_window.test_start_date,
            end_date=candidate.evaluation_window.test_end_date,
        )
        triggered = test_frame[
            test_frame.apply(
                lambda row: self._evaluate_preregistered_candidate(row, candidate),
                axis=1,
            )
        ].copy()
        trigger_count = len(triggered)
        peak_hit_count = int(triggered["is_peak_label"].sum()) if trigger_count else 0
        precision = peak_hit_count / trigger_count if trigger_count else 0.0
        avg_drawdown = (
            float(triggered["future_drawdown_10d"].fillna(0).mean())
            if trigger_count
            else 0.0
        )
        avg_return = (
            float(triggered["future_return_10d"].fillna(0).mean())
            if trigger_count
            else 0.0
        )
        avg_trade_impact = avg_drawdown - avg_return
        return {
            "candidate_id": candidate.candidate_id,
            "description": candidate.description,
            "definition_hash": candidate.definition_hash,
            "rule_type": candidate.rule_type.value,
            "threshold_set": [
                threshold.model_dump(mode="json") for threshold in candidate.thresholds
            ],
            "evaluation_window": candidate.evaluation_window.model_dump(mode="json"),
            "period": "out_of_sample",
            "rows_evaluated": len(test_frame),
            "trigger_count": trigger_count,
            "peak_hit_count": peak_hit_count,
            "precision": round(precision, 4),
            "avg_future_drawdown_10d": round(avg_drawdown, 4),
            "avg_future_return_10d": round(avg_return, 4),
            "avg_trade_impact_10d": round(avg_trade_impact, 4),
            "trade_impact_sum_10d": round(avg_trade_impact * trigger_count, 4),
        }

    @staticmethod
    def _frozen_candidate_definitions(
        candidates: tuple[PreRegisteredSellRuleCandidate, ...],
    ) -> list[dict[str, Any]]:
        return [
            {
                "candidate_id": candidate.candidate_id,
                "definition_hash": candidate.definition_hash,
                "threshold_set": [
                    threshold.model_dump(mode="json") for threshold in candidate.thresholds
                ],
                "evaluation_window": candidate.evaluation_window.model_dump(mode="json"),
            }
            for candidate in candidates
        ]

    def _research_preregistered_frame(
        self,
        *,
        config: SellRulePreRegistrationConfig,
        combined: pd.DataFrame,
        symbol_summaries: list[dict[str, Any]],
        resolved_start: str,
        resolved_end: str,
        data_source: str,
    ) -> dict[str, Any]:
        scored_rules = [
            self._score_preregistered_candidate(candidate, combined)
            for candidate in config.candidates
        ]
        return {
            "mode": "pre_registered",
            "data_source": data_source,
            "start_date": resolved_start,
            "end_date": resolved_end,
            "symbols": symbol_summaries,
            "rows_analyzed": len(combined),
            "candidate_count": len(config.candidates),
            "frozen_candidate_definitions": self._frozen_candidate_definitions(config.candidates),
            "out_of_sample": scored_rules,
            "data_snooping_warning": len(config.candidates) > 1,
        }

    async def research_top_signal_rules(
        self,
        symbols: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        resolved_end = end_date or datetime.now().strftime("%Y%m%d")
        resolved_start = start_date or (
            datetime.strptime(resolved_end, "%Y%m%d") - timedelta(days=365 * 2)
        ).strftime("%Y%m%d")
        symbol_rows = await self._resolve_symbols(symbols)

        frames: list[pd.DataFrame] = []
        symbol_summaries: list[dict[str, Any]] = []
        for row in symbol_rows:
            frame = await self._load_symbol_frame(
                symbol=row["symbol"] or "",
                market=row.get("market"),
                start_date=resolved_start,
                end_date=resolved_end,
            )
            if len(frame) < self.MIN_ROWS_PER_SYMBOL:
                continue
            labeled = self._label_local_peaks(frame)
            labeled["symbol"] = row["symbol"]
            frames.append(labeled)
            symbol_summaries.append(
                {
                    "symbol": row["symbol"],
                    "rows": len(labeled),
                    "peak_labels": int(labeled["is_peak_label"].sum()),
                }
            )

        if not frames:
            return {
                "start_date": resolved_start,
                "end_date": resolved_end,
                "symbols": [],
                "rules": [],
                "top_rule": None,
            }

        combined = pd.concat(frames, ignore_index=True)
        scored_rules = [
            self._score_candidate(rule, combined)
            for rule in self._candidate_rules()
        ]
        scored_rules.sort(key=lambda item: item["score"], reverse=True)

        return {
            "start_date": resolved_start,
            "end_date": resolved_end,
            "symbols": symbol_summaries,
            "rows_analyzed": len(combined),
            "rules": scored_rules,
            "top_rule": scored_rules[0] if scored_rules else None,
        }

    async def research_preregistered_sell_rules(
        self,
        config: SellRulePreRegistrationConfig,
    ) -> dict[str, Any]:
        windows = [candidate.evaluation_window for candidate in config.candidates]
        resolved_start = min(window.train_start_date for window in windows)
        resolved_end = max(window.test_end_date for window in windows)

        if config.fixture_rows:
            combined = pd.DataFrame(
                [row.model_dump(mode="json") for row in config.fixture_rows]
            )
            symbol_summaries = [
                {
                    "symbol": symbol,
                    "rows": len(symbol_frame),
                    "peak_labels": int(symbol_frame["is_peak_label"].sum()),
                }
                for symbol, symbol_frame in combined.groupby("symbol", sort=True)
            ]
            return self._research_preregistered_frame(
                config=config,
                combined=combined,
                symbol_summaries=symbol_summaries,
                resolved_start=resolved_start,
                resolved_end=resolved_end,
                data_source="config_fixture",
            )

        symbol_rows = await self._resolve_symbols(list(config.symbols) if config.symbols else None)

        frames: list[pd.DataFrame] = []
        symbol_summaries: list[dict[str, Any]] = []
        for row in symbol_rows:
            frame = await self._load_symbol_frame(
                symbol=row["symbol"] or "",
                market=row.get("market"),
                start_date=resolved_start,
                end_date=resolved_end,
            )
            if len(frame) < self.MIN_ROWS_PER_SYMBOL:
                continue
            labeled = self._label_local_peaks(frame)
            labeled["symbol"] = row["symbol"]
            frames.append(labeled)
            symbol_summaries.append(
                {
                    "symbol": row["symbol"],
                    "rows": len(labeled),
                    "peak_labels": int(labeled["is_peak_label"].sum()),
                }
            )

        if not frames:
            return {
                "mode": "pre_registered",
                "data_source": "database",
                "start_date": resolved_start,
                "end_date": resolved_end,
                "symbols": [],
                "candidate_count": len(config.candidates),
                "frozen_candidate_definitions": self._frozen_candidate_definitions(
                    config.candidates
                ),
                "out_of_sample": [],
                "data_snooping_warning": len(config.candidates) > 1,
            }

        combined = pd.concat(frames, ignore_index=True)
        return self._research_preregistered_frame(
            config=config,
            combined=combined,
            symbol_summaries=symbol_summaries,
            resolved_start=resolved_start,
            resolved_end=resolved_end,
            data_source="database",
        )


def render_preregistered_sell_rule_report(result: dict[str, Any]) -> str:
    lines = [
        "# Pre-Registered Sell Rule Research",
        "",
        f"- Mode: {result.get('mode')}",
        f"- Data source: {result.get('data_source')}",
        f"- Research window: {result.get('start_date')} to {result.get('end_date')}",
        f"- Candidate count: {result.get('candidate_count')}",
        f"- Data-snooping warning: {result.get('data_snooping_warning')}",
        "",
        "## Frozen Candidate Definitions",
        "",
    ]
    for definition in result.get("frozen_candidate_definitions", []):
        threshold_set_json = json.dumps(
            definition["threshold_set"],
            ensure_ascii=False,
            sort_keys=True,
        )
        evaluation_window_json = json.dumps(
            definition["evaluation_window"],
            ensure_ascii=False,
            sort_keys=True,
        )
        lines.extend(
            [
                f"### {definition['candidate_id']}",
                "",
                f"- Definition hash: `{definition['definition_hash']}`",
                f"- Threshold set: `{threshold_set_json}`",
                f"- Evaluation window: `{evaluation_window_json}`",
                "",
            ]
        )

    lines.extend(
        [
            "## Out-of-Sample Comparison",
            "",
            "| Candidate ID | Precision | Future Drawdown | Future Return | "
            "Trade Impact | Triggers |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in result.get("out_of_sample", []):
        lines.append(
            (
                "| {candidate_id} | {precision:.4f} | {drawdown:.4f} | "
                "{future_return:.4f} | {impact:.4f} | {triggers} |"
            ).format(
                candidate_id=row["candidate_id"],
                precision=row["precision"],
                drawdown=row["avg_future_drawdown_10d"],
                future_return=row["avg_future_return_10d"],
                impact=row["avg_trade_impact_10d"],
                triggers=row["trigger_count"],
            )
        )
    lines.append("")
    return "\n".join(lines)
