# -*- coding: utf-8 -*-
"""
Stock Selector - 종목 선별 및 랭킹 모듈

Phase 2 (Task 2) + process_improvement_and_checklist.md 기반:
- 복합 조건 필터링 (거래량, 상승률, 수급, 호가)
- 종목 랭킹 스코어 계산
- No-trade day 규칙
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from src.application.domain.news_trading.dto import (
    StockCandidateDTO,
    StockRankingDTO,
    StockSelectionConfigDTO,
    StockSelectionResultDTO,
)


class StockSelector:
    """
    종목 선별기

    주요 기능:
    1. 복합 조건 필터링 (거래량, 상승률, 수급, 호가)
    2. 랭킹 스코어 계산
    3. No-trade day 판정
    """

    def __init__(self, config: StockSelectionConfigDTO | None = None):
        """
        Args:
            config: 종목 선별 설정 (None이면 기본값 사용)
        """
        self.config = config or StockSelectionConfigDTO()

    def select_stocks(
        self,
        candidates: list[StockCandidateDTO],
        symbol_news_scores: dict[str, float] | None = None,
    ) -> StockSelectionResultDTO:
        """
        종목 선별 실행

        Args:
            candidates: 후보 종목 리스트
            symbol_news_scores: 종목별 뉴스 스코어 (뉴스 분석 결과)

        Returns:
            StockSelectionResultDTO: 선별 결과
        """
        symbol_news_scores = symbol_news_scores or {}
        selection_time = datetime.now()

        # 1. 뉴스 스코어 적용
        for candidate in candidates:
            if candidate.symbol in symbol_news_scores:
                candidate.news_score = symbol_news_scores[candidate.symbol]

        # 2. 복합 조건 필터링
        filtered_candidates = self._apply_filters(candidates)

        # 3. 랭킹 스코어 계산
        ranked_stocks = self._calculate_rankings(filtered_candidates)

        # 4. No-trade day 체크
        is_no_trade, no_trade_reason = self._check_no_trade_day(ranked_stocks)

        # 5. 최종 선정 (상위 N개)
        if is_no_trade:
            selected_symbols = []
        else:
            selected_symbols = [
                stock.symbol
                for stock in ranked_stocks[: self.config.max_candidates]
            ]

        return StockSelectionResultDTO(
            selection_time=selection_time,
            total_candidates=len(candidates),
            filtered_candidates=len(filtered_candidates),
            ranked_stocks=ranked_stocks,
            selected_symbols=selected_symbols,
            is_no_trade_day=is_no_trade,
            no_trade_reason=no_trade_reason,
        )

    def _apply_filters(
        self, candidates: list[StockCandidateDTO]
    ) -> list[StockCandidateDTO]:
        """
        복합 조건 필터링

        Phase 3 morphological_analysis.md 기준:
        - 거래량: 전일 대비 N배 이상
        - 상승률: 시가 대비 +N% 이상
        - 수급: 외인/기관 순매수
        - 호가: 매수잔량/매도잔량 비율
        - 시가총액: 최소 시가총액
        - 스프레드: 최대 호가 스프레드
        """
        filtered: list[StockCandidateDTO] = []

        for candidate in candidates:
            # 거래량 조건
            candidate.passes_volume_filter = (
                candidate.volume_ratio >= self.config.min_volume_ratio
            )

            # 상승률 조건
            candidate.passes_price_filter = (
                candidate.price_change_rate >= self.config.min_price_change_rate
            )

            # 수급 조건
            if self.config.require_foreign_net_buy:
                candidate.passes_supply_filter = candidate.foreign_net_buy > 0
            else:
                # 외인 또는 기관 순매수
                candidate.passes_supply_filter = (
                    candidate.foreign_net_buy > 0 or candidate.institution_net_buy > 0
                )

            # 호가 조건
            candidate.passes_orderbook_filter = (
                candidate.bid_ask_ratio >= self.config.min_bid_ask_ratio
            )

            # 시가총액 조건
            passes_market_cap = candidate.market_cap >= self.config.min_market_cap

            # 스프레드 조건
            passes_spread = candidate.spread_rate <= self.config.max_spread_rate

            # 모든 조건 통과 여부
            candidate.passes_all_filters = all([
                candidate.passes_volume_filter,
                candidate.passes_price_filter,
                candidate.passes_supply_filter,
                candidate.passes_orderbook_filter,
                passes_market_cap,
                passes_spread,
            ])

            if candidate.passes_all_filters:
                filtered.append(candidate)

        return filtered

    def _calculate_rankings(
        self, candidates: list[StockCandidateDTO]
    ) -> list[StockRankingDTO]:
        """
        랭킹 스코어 계산

        process_improvement_and_checklist.md 2.2 기준:
        rank_score = w1×news_score + w2×volume_ratio + w3×price_change + w4×bid_ask_ratio + w5×liquidity
        """
        if not candidates:
            return []

        # 정규화를 위한 min/max 계산
        stats = self._calculate_normalization_stats(candidates)

        rankings: list[StockRankingDTO] = []

        for candidate in candidates:
            # 각 요소 정규화 (0~1)
            norm_news = self._normalize(
                candidate.news_score, 0.0, 10.0
            )
            norm_volume = self._normalize(
                candidate.volume_ratio,
                stats["volume_min"],
                stats["volume_max"],
            )
            norm_price = self._normalize(
                candidate.price_change_rate,
                stats["price_min"],
                stats["price_max"],
            )
            norm_orderbook = self._normalize(
                candidate.bid_ask_ratio,
                stats["orderbook_min"],
                stats["orderbook_max"],
            )
            # 유동성: 시가총액 기준
            norm_liquidity = self._normalize(
                float(candidate.market_cap),
                float(stats["market_cap_min"]),
                float(stats["market_cap_max"]),
            )

            # 가중치 적용
            news_weighted = norm_news * self.config.news_weight
            volume_weighted = norm_volume * self.config.volume_weight
            price_weighted = norm_price * self.config.price_weight
            orderbook_weighted = norm_orderbook * self.config.orderbook_weight
            liquidity_weighted = norm_liquidity * self.config.liquidity_weight

            # 총 랭킹 스코어
            rank_score = (
                news_weighted
                + volume_weighted
                + price_weighted
                + orderbook_weighted
                + liquidity_weighted
            )

            rankings.append(
                StockRankingDTO(
                    symbol=candidate.symbol,
                    name=candidate.name,
                    rank=1,  # 임시값, 정렬 후 재설정
                    rank_score=round(rank_score, 4),
                    news_score_weighted=round(news_weighted, 4),
                    volume_score_weighted=round(volume_weighted, 4),
                    price_score_weighted=round(price_weighted, 4),
                    orderbook_score_weighted=round(orderbook_weighted, 4),
                    liquidity_score_weighted=round(liquidity_weighted, 4),
                    candidate=candidate,
                )
            )

        # 랭킹 스코어 기준 정렬 및 순위 부여
        rankings.sort(key=lambda x: x.rank_score, reverse=True)
        for i, ranking in enumerate(rankings):
            ranking.rank = i + 1

        return rankings

    def _calculate_normalization_stats(
        self, candidates: list[StockCandidateDTO]
    ) -> dict[str, Any]:
        """정규화를 위한 통계 계산"""
        if not candidates:
            return {
                "volume_min": 0.0,
                "volume_max": 1.0,
                "price_min": 0.0,
                "price_max": 1.0,
                "orderbook_min": 1.0,
                "orderbook_max": 2.0,
                "market_cap_min": Decimal("0"),
                "market_cap_max": Decimal("1"),
            }

        volumes = [c.volume_ratio for c in candidates]
        prices = [c.price_change_rate for c in candidates]
        orderbooks = [c.bid_ask_ratio for c in candidates]
        market_caps = [c.market_cap for c in candidates]

        return {
            "volume_min": min(volumes),
            "volume_max": max(volumes) if max(volumes) > min(volumes) else min(volumes) + 1,
            "price_min": min(prices),
            "price_max": max(prices) if max(prices) > min(prices) else min(prices) + 1,
            "orderbook_min": min(orderbooks),
            "orderbook_max": max(orderbooks) if max(orderbooks) > min(orderbooks) else min(orderbooks) + 1,
            "market_cap_min": min(market_caps),
            "market_cap_max": max(market_caps) if max(market_caps) > min(market_caps) else min(market_caps) + Decimal("1"),
        }

    @staticmethod
    def _normalize(value: float, min_val: float, max_val: float) -> float:
        """값을 0~1 범위로 정규화"""
        if max_val <= min_val:
            return 0.5
        return (value - min_val) / (max_val - min_val)

    def _check_no_trade_day(
        self, ranked_stocks: list[StockRankingDTO]
    ) -> tuple[bool, str | None]:
        """
        No-trade day 체크

        process_improvement_and_checklist.md 2.3 기준:
        - 상위 종목의 rank_score < 임계값
        - 상위 종목의 news_score < 임계값
        - 상위 종목의 volume_ratio < 3배
        """
        if not ranked_stocks:
            return True, "조건을 만족하는 종목이 없습니다"

        top_stock = ranked_stocks[0]

        # 랭킹 스코어 체크
        if top_stock.rank_score < self.config.min_top_rank_score:
            return True, f"상위 종목 랭킹 스코어 부족 ({top_stock.rank_score:.2f} < {self.config.min_top_rank_score})"

        # 뉴스 스코어 체크
        if top_stock.candidate.news_score < self.config.min_top_news_score:
            return True, f"상위 종목 뉴스 스코어 부족 ({top_stock.candidate.news_score:.2f} < {self.config.min_top_news_score})"

        # 거래량 배수 체크
        if top_stock.candidate.volume_ratio < self.config.min_volume_ratio:
            return True, f"상위 종목 거래량 부족 ({top_stock.candidate.volume_ratio:.1f}x < {self.config.min_volume_ratio}x)"

        return False, None

    def filter_by_single_condition(
        self,
        candidates: list[StockCandidateDTO],
        condition: str,
    ) -> list[StockCandidateDTO]:
        """
        단일 조건으로 필터링 (디버깅/분석용)

        Args:
            candidates: 후보 종목 리스트
            condition: 조건명 (volume, price, supply, orderbook, market_cap, spread)

        Returns:
            필터링된 종목 리스트
        """
        if condition == "volume":
            return [c for c in candidates if c.volume_ratio >= self.config.min_volume_ratio]
        elif condition == "price":
            return [c for c in candidates if c.price_change_rate >= self.config.min_price_change_rate]
        elif condition == "supply":
            if self.config.require_foreign_net_buy:
                return [c for c in candidates if c.foreign_net_buy > 0]
            return [c for c in candidates if c.foreign_net_buy > 0 or c.institution_net_buy > 0]
        elif condition == "orderbook":
            return [c for c in candidates if c.bid_ask_ratio >= self.config.min_bid_ask_ratio]
        elif condition == "market_cap":
            return [c for c in candidates if c.market_cap >= self.config.min_market_cap]
        elif condition == "spread":
            return [c for c in candidates if c.spread_rate <= self.config.max_spread_rate]
        else:
            return candidates

    def get_filter_summary(
        self, candidates: list[StockCandidateDTO]
    ) -> dict[str, int]:
        """
        필터링 결과 요약

        Returns:
            각 조건별 통과 종목 수
        """
        self._apply_filters(candidates)  # 필터 플래그 설정

        return {
            "total": len(candidates),
            "volume_passed": sum(1 for c in candidates if c.passes_volume_filter),
            "price_passed": sum(1 for c in candidates if c.passes_price_filter),
            "supply_passed": sum(1 for c in candidates if c.passes_supply_filter),
            "orderbook_passed": sum(1 for c in candidates if c.passes_orderbook_filter),
            "all_passed": sum(1 for c in candidates if c.passes_all_filters),
        }
