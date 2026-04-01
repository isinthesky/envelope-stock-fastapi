# -*- coding: utf-8 -*-
"""
Sell peak rule research service

저장된 OHLCV, 개인 수급, 시장 신용 데이터를 조합해
로컬 고점/과열 신호 후보를 평가한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

import pandas as pd
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
