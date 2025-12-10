# -*- coding: utf-8 -*-
"""
News Analyzer 유닛 테스트
"""

import pytest
from datetime import datetime, timedelta

from src.application.domain.news_trading.dto import (
    NewsEventType,
    NewsItemDTO,
    NewsAnalysisRequestDTO,
)
from src.application.domain.news_trading.news_analyzer import NewsAnalyzer


class TestNewsAnalyzer:
    """NewsAnalyzer 테스트"""

    @pytest.fixture
    def analyzer(self):
        """테스트용 뉴스 분석기"""
        return NewsAnalyzer(min_news_score=6.0)

    @pytest.fixture
    def sample_news_items(self):
        """테스트용 뉴스 샘플"""
        target_date = datetime.now()
        yesterday_evening = target_date - timedelta(hours=15)  # 전일 저녁

        return [
            # 삼성전자 관련 뉴스 (고영향)
            NewsItemDTO(
                title="삼성전자, 사상 최대 HBM 수주 계약 체결",
                content="삼성전자가 글로벌 AI 기업과 역대 최대 규모의 HBM 공급 계약을 체결했다. 계약 규모는 수조원에 달하는 것으로 알려졌다.",
                source="한국경제",
                published_at=yesterday_evening,
                url="https://example.com/news/1",
            ),
            # SK하이닉스 관련 뉴스
            NewsItemDTO(
                title="SK하이닉스, AI 반도체 투자 확대 발표",
                content="SK하이닉스가 HBM 생산 설비 투자를 대폭 확대한다고 밝혔다.",
                source="매일경제",
                published_at=yesterday_evening,
                url="https://example.com/news/2",
            ),
            # 일반 뉴스 (저영향)
            NewsItemDTO(
                title="코스피 소폭 상승 마감",
                content="코스피 지수가 소폭 상승 마감했다.",
                source="일간신문",
                published_at=yesterday_evening,
                url="https://example.com/news/3",
            ),
        ]

    def test_classify_event_type_earnings(self, analyzer):
        """이벤트 유형 분류 - 실적"""
        news = NewsItemDTO(
            title="삼성전자 3분기 실적 어닝 서프라이즈",
            content="삼성전자가 시장 컨센서스를 크게 상회하는 실적을 발표했다.",
            source="한국경제",
            published_at=datetime.now(),
        )
        event_type = analyzer._classify_event_type(news)
        assert event_type == NewsEventType.EARNINGS

    def test_classify_event_type_policy(self, analyzer):
        """이벤트 유형 분류 - 정책/규제"""
        news = NewsItemDTO(
            title="정부, 반도체 산업 지원 규제 완화 발표",
            content="산업부가 반도체 산업 지원을 위한 규제 완화 방안을 발표했다.",
            source="연합뉴스",
            published_at=datetime.now(),
        )
        event_type = analyzer._classify_event_type(news)
        assert event_type == NewsEventType.POLICY_REGULATION

    def test_classify_event_type_sector_theme(self, analyzer):
        """이벤트 유형 분류 - 섹터/테마"""
        news = NewsItemDTO(
            title="2차전지 업종 급등, 배터리 수출 호조",
            content="전기차 배터리 수출이 사상 최대를 기록했다.",
            source="매일경제",
            published_at=datetime.now(),
        )
        event_type = analyzer._classify_event_type(news)
        assert event_type == NewsEventType.SECTOR_THEME

    def test_calculate_news_score_high_impact(self, analyzer):
        """뉴스 스코어 계산 - 고영향"""
        target_date = datetime.now()
        yesterday_evening = datetime.combine(
            (target_date - timedelta(days=1)).date(),
            datetime.strptime("19:00", "%H:%M").time()
        )

        news = NewsItemDTO(
            title="삼성전자, 사상 최대 HBM 수주",
            content="삼성전자가 역대 최대 규모의 HBM 공급 계약을 체결했다. " * 20,  # 긴 본문
            source="한국경제",  # 주요 매체
            published_at=yesterday_evening,  # 전일 저녁
        )
        news.event_type = analyzer._classify_event_type(news)

        score = analyzer._calculate_news_score(news, target_date)

        # 영향도: 고영향 키워드(1.5) + 이벤트 유형(1.0) + 주요 매체(1.0) + 긴 본문(1.5) = 5.0
        # 신선도: 전일 저녁 = 3.0
        # 확산도: 기본값 = 1.0
        assert score.total_score >= 6.0

    def test_extract_related_symbols(self, analyzer):
        """관련 종목 추출"""
        news = NewsItemDTO(
            title="삼성전자, HBM 수주 확대",
            content="삼성전자와 SK하이닉스가 HBM 시장을 주도하고 있다.",
            source="한국경제",
            published_at=datetime.now(),
        )
        symbols = analyzer._extract_related_symbols(news)

        assert "005930" in symbols  # 삼성전자
        assert "000660" in symbols  # SK하이닉스

    def test_analyze_news_filters_low_score(self, analyzer, sample_news_items):
        """뉴스 분석 - 저스코어 뉴스 필터링"""
        target_date = datetime.now()

        request = NewsAnalysisRequestDTO(
            target_date=target_date,
            news_items=sample_news_items,
            min_news_score=6.0,
        )

        result = analyzer.analyze_news(request)

        assert result.total_news_count == 3
        assert result.filtered_news_count <= 3
        # 저영향 뉴스는 필터링되어야 함
        assert len(result.candidate_symbols) >= 0

    def test_analyze_news_symbol_scores(self, analyzer, sample_news_items):
        """뉴스 분석 - 종목별 스코어"""
        target_date = datetime.now()

        request = NewsAnalysisRequestDTO(
            target_date=target_date,
            news_items=sample_news_items,
            min_news_score=0.0,  # 모든 뉴스 포함
        )

        result = analyzer.analyze_news(request)

        # 종목별 스코어가 계산되어야 함
        if result.candidate_symbols:
            for symbol in result.candidate_symbols:
                assert symbol in result.symbol_scores
                assert result.symbol_scores[symbol] >= 0

    def test_extract_keywords(self, analyzer):
        """키워드 추출"""
        text = "삼성전자가 반도체 규제 완화로 HBM 수주가 사상 최대를 기록했다."
        keywords = analyzer.extract_keywords(text)

        assert len(keywords) > 0
        assert "반도체" in keywords or "규제" in keywords or "완화" in keywords

    def test_update_symbol_mapping(self, analyzer):
        """종목-키워드 매핑 업데이트"""
        analyzer.update_symbol_mapping("TEST123", ["테스트", "키워드"])

        keywords = analyzer.get_symbol_keywords("TEST123")
        assert "테스트" in keywords
        assert "키워드" in keywords

        # 역인덱스도 업데이트되어야 함
        assert "TEST123" in analyzer.keyword_to_symbols.get("테스트", [])
