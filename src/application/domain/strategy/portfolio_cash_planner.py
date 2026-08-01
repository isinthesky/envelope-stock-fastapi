# -*- coding: utf-8 -*-
"""
Portfolio Cash Planner - 사전 현금화 계획 (순수 정책)

StrategyService.build_portfolio_cash_plan에서 분해한 순수 정책 로직.
urgency 점수/비중 맵/과열 임계값/노트는 원본과 100% 동일하게 유지한다.
"""

import json
from datetime import datetime

from src.application.domain.strategy.dto import (
    PortfolioCashActionDTO,
    PortfolioCashPlanDTO,
)


class PortfolioCashPlanner:
    """활성 매도 분석 이력 기준 사전 현금화 계획 생성기 (순수 정책)"""

    def build(
        self,
        histories: list,
        *,
        target_cash_ratio: float = 0.30,
        current_cash_ratio: float | None = None,
    ) -> PortfolioCashPlanDTO:
        """활성 매도 분석 이력 기준 사전 현금화 계획 생성"""
        from src.application.domain.strategy.sell_strategy_service import SellStrategyService

        scored_actions: list[PortfolioCashActionDTO] = []
        total_score = 0.0
        winner_priority_count = 0

        for item in histories:
            sell_stage = getattr(item, "sell_stage", None) or "HOLD"
            final_stage = getattr(item, "final_stage", None) or sell_stage
            if hasattr(final_stage, "value"):
                final_stage = final_stage.value
            sell_reasons = getattr(item, "sell_reasons", None) or []
            if isinstance(sell_reasons, str):
                try:
                    sell_reasons = json.loads(sell_reasons)
                except json.JSONDecodeError:
                    sell_reasons = [sell_reasons]

            volume_ratio = float(getattr(item, "volume_ratio", 0.0) or 0.0)
            market = getattr(item, "market", None)
            instrument_profile = SellStrategyService.infer_instrument_profile(
                getattr(item, "symbol", ""),
                name=getattr(item, "name", None),
                market=market,
            )
            profit_ratio = None
            entry_price = getattr(item, "entry_price", None)
            current_price = getattr(item, "current_price", None)
            if entry_price and current_price:
                try:
                    profit_ratio = float((current_price - entry_price) / entry_price)
                except Exception:
                    profit_ratio = None

            score = 0.0
            reasons = list(sell_reasons)
            if final_stage == "REDUCE_1":
                score += 35
            elif final_stage == "REDUCE_2":
                score += 60
            elif final_stage == "EXIT_ALL":
                score += 90

            if getattr(item, "is_death_cross", False):
                score += 20
                reasons.append("데드크로스 진행")
            if getattr(item, "is_volume_sell_signal", False):
                score += 15
                reasons.append("거래량 매도 신호")
            if getattr(item, "is_volume_spike", False) and volume_ratio >= 1.3:
                score += 10
                reasons.append(f"거래량 급증 {volume_ratio:.2f}배")
            if getattr(item, "overbought_sell_blocked", False):
                score -= 10
                reasons.append("강한 상승 추세로 과매수 매도 차단")
            if profit_ratio is not None and profit_ratio >= 0.15:
                score += 25
                reasons.append("수익 보호 우선 현금화 구간 (+15%)")
            elif profit_ratio is not None and profit_ratio >= 0.08:
                score += 18
                reasons.append("수익 구간에서 선제 현금화 유리")
            elif profit_ratio is not None and profit_ratio > 0:
                score += 8
                reasons.append("소폭 수익 구간")
            if profit_ratio is not None and profit_ratio <= -0.05:
                score += 10
                reasons.append("손실 확대 전 리스크 축소 필요")
            if (
                profit_ratio is not None
                and profit_ratio > 0
                and final_stage in {"REDUCE_1", "REDUCE_2", "EXIT_ALL"}
            ):
                winner_priority_count += 1
                score += 15
                reasons.append("현금 확보는 수익 종목 우선")
            if instrument_profile["is_etf_like"] and final_stage in {"REDUCE_1", "REDUCE_2"}:
                score += 8
                reasons.append("ETF/레버리지 계열은 회전이 빨라 선제 축소")

            suggested_ratio = {
                "HOLD": 0.0,
                "REDUCE_1": 0.25,
                "REDUCE_2": 0.50,
                "EXIT_ALL": 1.0,
            }.get(final_stage, 0.0)
            if profit_ratio is not None and profit_ratio >= 0.08 and final_stage == "REDUCE_1":
                suggested_ratio = max(suggested_ratio, 0.30)
            if profit_ratio is not None and profit_ratio >= 0.12 and final_stage == "REDUCE_2":
                suggested_ratio = max(suggested_ratio, 0.60)
            if (
                instrument_profile["is_etf_like"]
                and profit_ratio is not None
                and profit_ratio > 0
                and final_stage == "REDUCE_1"
            ):
                suggested_ratio = max(suggested_ratio, 0.35)
            if (
                instrument_profile["is_leveraged_etf_like"]
                and profit_ratio is not None
                and profit_ratio > 0
                and final_stage == "REDUCE_2"
            ):
                suggested_ratio = max(suggested_ratio, 0.70)
            if score >= 90 and suggested_ratio < 1.0:
                suggested_ratio = max(suggested_ratio, 0.70)
            elif score >= 60 and suggested_ratio < 0.50:
                suggested_ratio = max(suggested_ratio, 0.50)

            action = "보유 유지"
            if suggested_ratio >= 1.0:
                action = "전량 현금화"
            elif suggested_ratio >= 0.50:
                action = "강한 비중 축소"
            elif suggested_ratio > 0:
                action = "선제 비중 축소"

            note = None
            if profit_ratio is not None and profit_ratio >= 0.15:
                note = "수익 종목은 고점 경고 시 현금 창출원으로 우선 활용"
            elif profit_ratio is not None and profit_ratio >= 0.08:
                note = "수익 보호 단계: 현금이 필요하면 먼저 줄일 후보"
            elif profit_ratio is not None and profit_ratio <= -0.08:
                note = "기존 손실 보전 기대보다 자본 보전 우선"
            elif instrument_profile["is_leveraged_etf_like"] and final_stage in {
                "REDUCE_1",
                "REDUCE_2",
            }:
                note = "레버리지/인버스 계열은 일반 종목보다 더 빠르게 이익 보호"
            elif instrument_profile["is_etf_like"] and final_stage in {"REDUCE_1", "REDUCE_2"}:
                note = "ETF 계열은 수익 구간에서 선제 현금화 기준을 강화"

            non_negative_score = max(score, 0.0)
            scored_actions.append(
                PortfolioCashActionDTO(
                    symbol=getattr(item, "symbol"),
                    name=getattr(item, "name", None),
                    priority=0,
                    action=action,
                    sell_stage=final_stage,
                    suggested_sell_ratio=round(suggested_ratio, 2),
                    urgency_score=round(non_negative_score, 2),
                    profit_ratio=round(profit_ratio, 4) if profit_ratio is not None else None,
                    reasons=list(dict.fromkeys(reasons))[:6],
                    note=note,
                )
            )
            total_score += non_negative_score

        scored_actions.sort(key=lambda x: x.urgency_score, reverse=True)
        for idx, action in enumerate(scored_actions, start=1):
            action.priority = idx

        active_count = len(scored_actions)
        avg_score = round(total_score / active_count, 2) if active_count else 0.0
        cash_gap_ratio = None
        if avg_score >= 70:
            heat_level = "HIGH"
            portfolio_action = "신규 진입 중단 + 상위 위험 종목 중심 현금화"
        elif avg_score >= 45:
            heat_level = "ELEVATED"
            portfolio_action = "신규 진입 축소 + REDUCE 단계 종목 우선 정리"
        else:
            heat_level = "NORMAL"
            portfolio_action = "보유 유지 가능, 다만 경고 종목은 선별 감축"

        summary = [
            f"활성 추적 종목 {active_count}개 기준 포트폴리오 위험 점수는 {avg_score:.1f}점",
            f"시장 과열 단계는 {heat_level}로 판단",
            f"목표 현금 비중은 {target_cash_ratio * 100:.0f}%",
        ]
        if current_cash_ratio is not None:
            cash_gap_ratio = round(target_cash_ratio - current_cash_ratio, 4)
            if cash_gap_ratio > 0:
                summary.append(
                    f"현재 현금 비중이 목표보다 {cash_gap_ratio * 100:.1f}%p 낮아 선제 현금화 필요"
                )
            else:
                summary.append("현재 현금 비중은 목표 이상으로 방어 가능")
        if winner_priority_count > 0:
            summary.append(
                f"현금 확보는 수익 구간 종목 {winner_priority_count}개를 " f"우선 활용하도록 정렬"
            )
        if scored_actions:
            top = scored_actions[0]
            summary.append(f"최우선 정리 후보는 {top.symbol}{' ' + top.name if top.name else ''}")

        return PortfolioCashPlanDTO(
            analyzed_at=datetime.now(),
            active_sell_count=active_count,
            target_cash_ratio=target_cash_ratio,
            current_cash_ratio=current_cash_ratio,
            cash_gap_ratio=cash_gap_ratio,
            market_heat_level=heat_level,
            market_risk_score=avg_score,
            portfolio_action=portfolio_action,
            summary=summary,
            actions=scored_actions,
        )
