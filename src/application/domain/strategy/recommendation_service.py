# -*- coding: utf-8 -*-
"""
Recommendation Service - 골든크로스 추천 점수/랭킹 + 요약 오케스트레이션

StrategyService에서 분해한 추천 로직.
- RecommendationScorer: 순수 점수/랭킹/검증 (상태 없음)
- RecommendationService: 스캔→재무필터→점수→Top 요약 오케스트레이션

점수/순위/임계값은 원본과 100% 동일하게 유지한다.
"""

from src.application.common.exceptions import StrategyError
from src.application.domain.strategy.dto import (
    GoldenCrossRecommendationDTO,
    GoldenCrossScanItemDTO,
    GoldenCrossScanListDTO,
    IndustrySummaryDTO,
)
from src.application.domain.strategy.strategy_contract import (
    GOLDEN_CROSS_SCAN_STATE_ORDER,
    GoldenCrossScanState,
)
from src.settings.config import settings


class RecommendationScorer:
    """추천 점수/랭킹/검증 (순수)"""

    @staticmethod
    def validate_target_states(target_states: list[str]) -> list[str]:
        allowed_states = {state.value for state in GoldenCrossScanState}
        invalid = sorted(set(target_states) - allowed_states)
        if invalid:
            raise StrategyError(
                "Invalid target_states: "
                f"{', '.join(invalid)}. Allowed: {', '.join(sorted(allowed_states))}"
            )
        return target_states

    @staticmethod
    def state_rank(gc_state: str) -> int:
        # canonical scan-state 우선순위를 그대로 사용하되, FEAR_BUY를
        # OPTIMAL_BUY 바로 다음(랭크 1)에 삽입해 기존 순위를 보존한다.
        rank_order = (
            GoldenCrossScanState.OPTIMAL_BUY,
            GoldenCrossScanState.FEAR_BUY,
            *GOLDEN_CROSS_SCAN_STATE_ORDER[1:],
        )
        return {state: rank for rank, state in enumerate(rank_order)}.get(gc_state, 99)

    @staticmethod
    def passes_financial_filter(
        stock: GoldenCrossScanItemDTO,
        *,
        financial_filter_applied: bool,
    ) -> bool:
        if not financial_filter_applied:
            return True
        return stock.financial_filter_status in {"PASS", "TURNAROUND"}

    @staticmethod
    def financial_filter_has_any_success(
        scan: GoldenCrossScanListDTO,
        target_state_set: set[str],
    ) -> bool:
        return any(
            stock.gc_state in target_state_set
            and stock.financial_filter_status in {"PASS", "TURNAROUND", "FAIL"}
            for stock in scan.stocks
        )

    def attach_explainability(
        self,
        stock: GoldenCrossScanItemDTO,
        *,
        target_state_set: set[str],
        min_recommendation_score: float,
        financial_filter_applied: bool = False,
    ) -> GoldenCrossScanItemDTO:
        score, reasons, filter_reasons = self.score_candidate(stock)
        if stock.gc_state not in target_state_set:
            filter_reasons.append(f"대상 상태 제외 ({stock.gc_state})")
        if score < min_recommendation_score:
            filter_reasons.append(f"추천 점수 미달 ({score:.1f} < {min_recommendation_score:.1f})")
        if financial_filter_applied and stock.financial_filter_status not in {"PASS", "TURNAROUND"}:
            status = stock.financial_filter_status or "NOT_CHECKED"
            reason = f"재무 필터 제외 ({status})"
            if reason not in filter_reasons:
                filter_reasons.append(reason)
        return stock.model_copy(
            update={
                "recommendation_score": round(score, 2),
                "recommendation_reasons": reasons,
                "filter_reasons": filter_reasons,
            }
        )

    def score_candidate(
        self,
        stock: GoldenCrossScanItemDTO,
    ) -> tuple[float, list[str], list[str]]:
        reasons: list[str] = []
        filter_reasons: list[str] = []
        score = 0.0

        state_score = {
            GoldenCrossScanState.OPTIMAL_BUY: 55.0,
            GoldenCrossScanState.BUY_INTEREST: 42.0,
            GoldenCrossScanState.READY_TO_BUY: 32.0,
            GoldenCrossScanState.WAITING_FOR_PULLBACK: 16.0,
            GoldenCrossScanState.GC_ACTIVE: 8.0,
        }.get(stock.gc_state, 0.0)
        score += state_score
        if state_score:
            reasons.append(f"{stock.gc_state} 신호 단계 ({state_score:.0f}점)")

        screening = float(stock.screening_score or 0)
        screening_score = min(max(screening, 0.0), 100.0) * 0.2
        score += screening_score
        if screening_score:
            reasons.append(f"스크리닝 점수 반영 ({screening:.1f})")

        if 0 <= stock.ma_gap_ratio <= 8:
            score += 10.0
            reasons.append(f"MA 갭 건강 ({stock.ma_gap_ratio:.1f}%)")
        elif stock.ma_gap_ratio > 12:
            filter_reasons.append(f"MA 갭 과대 ({stock.ma_gap_ratio:.1f}%)")

        if stock.stoch_k >= 30 and stock.stoch_k > stock.stoch_d:
            score += 10.0
            reasons.append(f"Stoch 회복 우위 (K={stock.stoch_k:.1f} > D={stock.stoch_d:.1f})")
        elif stock.stoch_k < 30:
            reasons.append(f"과매도 관찰 구간 (K={stock.stoch_k:.1f})")

        financial_status = stock.financial_filter_status
        if financial_status == "PASS":
            score += 8.0
            reasons.append("재무 필터 통과")
        elif financial_status == "TURNAROUND":
            score += 5.0
            reasons.append("턴어라운드 후보")
        elif financial_status == "FAIL":
            score -= 12.0
            filter_reasons.append("재무 필터 미통과")
        elif financial_status == "ERROR":
            score -= 4.0
            filter_reasons.append("재무 데이터 확인 실패")
        elif financial_status == "PENDING":
            filter_reasons.append("재무 필터 미조회")

        return max(score, 0.0), reasons, filter_reasons


class RecommendationService:
    """골든크로스 추천 요약 오케스트레이션 (스캔 위임 + 점수/랭킹)"""

    def __init__(self, session) -> None:
        self._session = session
        self.scorer = RecommendationScorer()

    async def recommend(
        self,
        *,
        market: str | None = None,
        stoch_threshold: float = 30.0,
        gc_only: bool = True,
        include_etf: bool = True,
        limit: int = 1000,
        max_concurrent: int | None = None,
        top_n: int = 5,
        top_industries_n: int = 3,
        target_states: list[str] | None = None,
        min_recommendation_score: float = 0.0,
        apply_financial_filter: bool = False,
        financial_filter_max_concurrent: int = 3,
    ) -> GoldenCrossRecommendationDTO:
        """골든크로스 추천 요약 (Top 종목 + Top 업종)

        - Top 종목: 대상 상태 후보 중 추천 점수 상위 N개
        - Top 업종: 대상 상태 후보에서 업종별 count 상위 N개
        """
        from collections import Counter

        from src.application.domain.strategy.buy_strategy_service import BuyStrategyService

        buy_service = BuyStrategyService(session=self._session)
        if target_states is None:
            target_states = ["OPTIMAL_BUY"]
            # [#2/#3] fear-buy 알림 opt-in: 켜져 있으면 FEAR_BUY 후보도 추천/알림에 포함
            if getattr(settings, "fear_buy_notify_enabled", False) and getattr(
                settings, "fear_buy_window_enabled", False
            ):
                target_states = target_states + ["FEAR_BUY"]
        target_states = self.scorer.validate_target_states(target_states)
        target_state_set = set(target_states)

        scan = await buy_service.scan_golden_cross_candidates(
            market=market,
            stoch_threshold=stoch_threshold,
            gc_only=gc_only,
            include_etf=include_etf,
            limit=limit,
            max_concurrent=max_concurrent,
        )
        financial_filter_applied = False
        if apply_financial_filter:
            scan_before_financial_filter = scan
            try:
                scan = await buy_service.apply_financial_filter(
                    scan,
                    target_states=target_states,
                    max_concurrent=financial_filter_max_concurrent,
                )
                if self.scorer.financial_filter_has_any_success(scan, target_state_set):
                    financial_filter_applied = True
                else:
                    errors = list(scan_before_financial_filter.errors)
                    errors.append(
                        "Financial filter skipped: all target financial screenings failed"
                    )
                    scan = scan_before_financial_filter.model_copy(update={"errors": errors})
            except Exception as exc:
                errors = list(scan_before_financial_filter.errors)
                errors.append(f"Financial filter skipped: {exc}")
                scan = scan_before_financial_filter.model_copy(update={"errors": errors})

        explained_stocks = [
            self.scorer.attach_explainability(
                stock,
                target_state_set=target_state_set,
                min_recommendation_score=min_recommendation_score,
                financial_filter_applied=financial_filter_applied,
            )
            for stock in scan.stocks
        ]
        candidates = [
            stock
            for stock in explained_stocks
            if stock.gc_state in target_state_set
            and float(stock.recommendation_score or 0) >= min_recommendation_score
            and self.scorer.passes_financial_filter(
                stock,
                financial_filter_applied=financial_filter_applied,
            )
        ]
        candidates.sort(
            key=lambda s: (
                -float(s.recommendation_score or 0),
                self.scorer.state_rank(s.gc_state),
                s.symbol,
            )
        )
        top_stocks = candidates[:top_n]

        counter: Counter[str] = Counter([s.industry_code for s in candidates if s.industry_code])

        # code -> name (이미 scan 단계에서 industry_name attach 됨)
        code_to_name: dict[str, str | None] = {}
        for s in candidates:
            if s.industry_code and s.industry_code not in code_to_name:
                code_to_name[s.industry_code] = s.industry_name

        top_industries: list[IndustrySummaryDTO] = []
        for code, cnt in counter.most_common(top_industries_n):
            top_industries.append(
                IndustrySummaryDTO(
                    industry_code=code,
                    industry_name=code_to_name.get(code),
                    count=cnt,
                )
            )

        return GoldenCrossRecommendationDTO(
            top_stocks=top_stocks,
            top_industries=top_industries,
            buy_candidate_count=len(candidates),
            scan_time=scan.scan_time,
            errors=scan.errors,
            candidate_state_counts=dict(Counter(stock.gc_state for stock in candidates)),
            selected_state_counts=dict(Counter(stock.gc_state for stock in top_stocks)),
            financial_status_counts=dict(
                Counter(str(stock.financial_filter_status or "NOT_CHECKED") for stock in candidates)
            ),
            excluded_count=len(explained_stocks) - len(candidates),
            selection_criteria=[
                f"target_states={','.join(target_states)}",
                f"min_recommendation_score={min_recommendation_score:.1f}",
                (
                    "score = signal stage + screening score + MA gap health + "
                    "Stoch recovery + financial status"
                ),
                (
                    "financial_filter="
                    f"{'applied' if financial_filter_applied else 'requested_failed' if apply_financial_filter else 'disabled'}"
                ),
            ],
        )
