# -*- coding: utf-8 -*-
"""
Stock Selector 유닛 테스트
"""

import pytest
from datetime import datetime
from decimal import Decimal

from src.application.domain.news_trading.dto import (
    StockCandidateDTO,
    StockSelectionConfigDTO,
    StockSelectionResultDTO,
)
from src.application.domain.news_trading.stock_selector import StockSelector


class TestStockSelector:
    """StockSelector 테스트"""

    @pytest.fixture
    def selector(self):
        """테스트용 종목 선별기"""
        config = StockSelectionConfigDTO(
            min_volume_ratio=2.0,
            min_price_change_rate=2.0,
            max_spread_rate=0.5,
            min_market_cap=Decimal("1000"),
            min_bid_ask_ratio=1.2,
            max_candidates=5,
        )
        return StockSelector(config)

    @pytest.fixture
    def sample_candidates(self):
        """테스트용 후보 종목"""
        return [
            StockCandidateDTO(
                symbol="005930",
                name="삼성전자",
                current_price=Decimal("70000"),
                open_price=Decimal("68000"),
                prev_close=Decimal("67000"),
                news_score=8.0,
                volume_ratio=3.5,
                price_change_rate=3.5,
                foreign_net_buy=1000000000,
                institution_net_buy=500000000,
                bid_ask_ratio=1.5,
                market_cap=Decimal("300000"),  # 시총 OK
                spread_rate=0.2,
            ),
            StockCandidateDTO(
                symbol="000660",
                name="SK하이닉스",
                current_price=Decimal("150000"),
                open_price=Decimal("145000"),
                prev_close=Decimal("143000"),
                news_score=7.5,
                volume_ratio=4.0,
                price_change_rate=4.5,
                foreign_net_buy=800000000,
                institution_net_buy=300000000,
                bid_ask_ratio=1.3,
                market_cap=Decimal("80000"),
                spread_rate=0.3,
            ),
            StockCandidateDTO(
                symbol="035720",
                name="카카오",
                current_price=Decimal("50000"),
                open_price=Decimal("48000"),
                prev_close=Decimal("47000"),
                news_score=6.0,
                volume_ratio=2.5,
                price_change_rate=2.5,
                foreign_net_buy=200000000,
                institution_net_buy=100000000,
                bid_ask_ratio=1.25,
                market_cap=Decimal("30000"),
                spread_rate=0.4,
            ),
            StockCandidateDTO(
                symbol="TEST01",
                name="테스트저조",
                current_price=Decimal("10000"),
                open_price=Decimal("9900"),
                prev_close=Decimal("9800"),
                news_score=3.0,  # 낮은 뉴스 스코어
                volume_ratio=1.5,  # 거래량 미달
                price_change_rate=1.0,  # 등락률 미달
                foreign_net_buy=0,
                institution_net_buy=0,
                bid_ask_ratio=0.8,  # 호가 비율 미달
                market_cap=Decimal("5000"),
                spread_rate=0.8,  # 스프레드 초과
            ),
        ]

    def test_apply_filters_volume_ratio(self, selector, sample_candidates):
        """필터링 - 거래량 비율"""
        filtered = selector._apply_filters(sample_candidates)

        # 거래량 비율 미달 종목 필터링 확인
        symbols = [c.symbol for c in filtered]
        assert "TEST01" not in symbols  # 거래량 비율 1.5 < 2.0

    def test_apply_filters_price_change(self, selector, sample_candidates):
        """필터링 - 등락률"""
        filtered = selector._apply_filters(sample_candidates)

        # 등락률 미달 종목 필터링 확인
        symbols = [c.symbol for c in filtered]
        assert "TEST01" not in symbols  # 등락률 1% < 2%

    def test_apply_filters_orderbook(self, selector, sample_candidates):
        """필터링 - 호가 비율"""
        filtered = selector._apply_filters(sample_candidates)

        # 호가 비율 미달 종목 필터링 확인
        symbols = [c.symbol for c in filtered]
        assert "TEST01" not in symbols  # 호가 비율 0.8 < 1.2

    def test_apply_filters_spread(self, selector, sample_candidates):
        """필터링 - 스프레드"""
        filtered = selector._apply_filters(sample_candidates)

        # 스프레드 초과 종목 필터링 확인
        symbols = [c.symbol for c in filtered]
        assert "TEST01" not in symbols  # 스프레드 0.8 > 0.5

    def test_calculate_rankings(self, selector, sample_candidates):
        """순위 계산"""
        filtered = selector._apply_filters(sample_candidates)
        rankings = selector._calculate_rankings(filtered)

        assert len(rankings) <= selector.config.max_candidates

        # 순위가 스코어 기준으로 정렬되어야 함
        if len(rankings) >= 2:
            assert rankings[0].rank_score >= rankings[1].rank_score

    def test_select_stocks_returns_result(self, selector, sample_candidates):
        """종목 선별 결과 반환"""
        result = selector.select_stocks(sample_candidates)

        assert isinstance(result, StockSelectionResultDTO)
        assert result.total_candidates == len(sample_candidates)
        assert result.filtered_candidates <= result.total_candidates
        assert len(result.selected_symbols) <= selector.config.max_candidates

    def test_select_stocks_max_candidates(self, selector, sample_candidates):
        """최대 후보 수 제한"""
        result = selector.select_stocks(sample_candidates)

        assert len(result.selected_symbols) <= selector.config.max_candidates

    def test_check_no_trade_day_empty(self, selector):
        """노트레이드 데이 - 빈 후보"""
        result = selector.select_stocks([])

        assert result.is_no_trade_day
        assert result.no_trade_reason is not None

    def test_filter_summary(self, selector, sample_candidates):
        """필터링 결과 요약"""
        summary = selector.get_filter_summary(sample_candidates)

        assert summary["total"] == len(sample_candidates)
        assert "volume_passed" in summary
        assert "price_passed" in summary
        assert "supply_passed" in summary
        assert "orderbook_passed" in summary
        assert "all_passed" in summary

    def test_filter_by_single_condition(self, selector, sample_candidates):
        """단일 조건 필터링"""
        # 거래량 조건만
        volume_filtered = selector.filter_by_single_condition(sample_candidates, "volume")
        assert all(c.volume_ratio >= selector.config.min_volume_ratio for c in volume_filtered)

        # 가격 조건만
        price_filtered = selector.filter_by_single_condition(sample_candidates, "price")
        assert all(c.price_change_rate >= selector.config.min_price_change_rate for c in price_filtered)
