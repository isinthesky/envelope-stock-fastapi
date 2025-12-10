# -*- coding: utf-8 -*-
"""
News Analyzer - 뉴스 분석 및 종목 매핑 모듈

Phase 1 (Task 6) + process_improvement_and_checklist.md 기반:
- 뉴스 이벤트 타입 분류
- 뉴스 스코어링 (영향도 + 신선도 + 확산도)
- 뉴스-종목 매핑
"""

import re
from datetime import datetime, time, timedelta
from typing import Any

from src.application.domain.news_trading.dto import (
    NewsEventType,
    NewsItemDTO,
    NewsScoreDTO,
    NewsAnalysisRequestDTO,
    NewsAnalysisResultDTO,
)


# ==================== 키워드 사전 ====================


# 이벤트 유형별 키워드
EVENT_TYPE_KEYWORDS: dict[NewsEventType, list[str]] = {
    NewsEventType.POLICY_REGULATION: [
        "규제", "완화", "강화", "정책", "정부", "지원", "세제", "보조금",
        "인허가", "승인", "허가", "법안", "개정", "시행령", "금융위",
        "공정위", "산업부", "국토부", "환경부", "기재부",
    ],
    NewsEventType.EARNINGS: [
        "실적", "어닝", "매출", "영업이익", "순이익", "흑자", "적자",
        "서프라이즈", "쇼크", "가이던스", "전망", "컨센서스", "상향",
        "하향", "분기", "반기", "연간", "잠정", "확정",
    ],
    NewsEventType.CORPORATE_ACTION: [
        "인수", "합병", "M&A", "수주", "계약", "납품", "공급", "자사주",
        "매입", "소각", "배당", "증자", "감자", "분할", "IPO", "상장",
        "MOU", "협약", "제휴", "투자", "신사업",
    ],
    NewsEventType.SECTOR_THEME: [
        "2차전지", "전기차", "배터리", "AI", "인공지능", "반도체", "메모리",
        "바이오", "신약", "임상", "승인", "로봇", "자율주행", "수소",
        "태양광", "풍력", "원전", "SMR", "방산", "우주", "게임",
        "엔터", "플랫폼", "클라우드", "데이터센터", "전력", "그리드",
    ],
    NewsEventType.GLOBAL_MACRO: [
        "금리", "연준", "Fed", "FOMC", "인플레이션", "CPI", "환율",
        "달러", "엔화", "위안화", "유가", "유럽", "중국", "미국",
        "경기", "침체", "회복", "성장률", "GDP", "고용", "실업",
    ],
    NewsEventType.POLITICAL: [
        "대선", "총선", "선거", "정권", "여당", "야당", "국회", "청와대",
        "대통령", "장관", "북한", "한미", "한중", "한일", "전쟁", "분쟁",
    ],
}

# 영향도 증폭 키워드 (가중치 상향)
HIGH_IMPACT_KEYWORDS: list[str] = [
    "최대", "사상 최고", "역대 최대", "최초", "신기록", "돌파", "급등",
    "급락", "폭등", "폭락", "대규모", "초대형", "메가", "수조원",
    "사상 최저", "역대급", "블록버스터", "빅딜", "게임체인저",
]

# 종목 코드-키워드 매핑 (예시, 실제로는 DB에서 로드)
SYMBOL_KEYWORD_MAPPING: dict[str, list[str]] = {
    "005930": ["삼성전자", "삼전", "반도체", "메모리", "HBM", "파운드리"],
    "000660": ["SK하이닉스", "하이닉스", "메모리", "HBM", "DRAM"],
    "373220": ["LG에너지솔루션", "LG엔솔", "배터리", "2차전지", "전기차"],
    "006400": ["삼성SDI", "SDI", "배터리", "2차전지", "ESS"],
    "051910": ["LG화학", "LG화학", "배터리", "2차전지", "석유화학"],
    "035420": ["NAVER", "네이버", "AI", "검색", "플랫폼", "클라우드"],
    "035720": ["카카오", "카카오", "플랫폼", "모빌리티", "금융"],
    "105560": ["KB금융", "KB", "은행", "금융", "금리"],
    "055550": ["신한지주", "신한", "은행", "금융", "금리"],
    "012330": ["현대모비스", "모비스", "자율주행", "전장", "부품"],
    "207940": ["삼성바이오로직스", "삼바", "바이오", "CMO", "CDMO"],
    "068270": ["셀트리온", "셀트리온", "바이오", "바이오시밀러", "신약"],
    "247540": ["에코프로비엠", "에코프로", "2차전지", "양극재", "배터리"],
    "086520": ["에코프로", "에코프로", "2차전지", "양극재"],
    "003670": ["포스코퓨처엠", "포스코", "2차전지", "양극재", "음극재"],
}

# 주요 뉴스 매체 (가중치 상향)
MAJOR_NEWS_SOURCES: list[str] = [
    "한국경제", "매일경제", "조선비즈", "연합뉴스", "이데일리", "머니투데이",
    "서울경제", "헤럴드경제", "아시아경제", "파이낸셜뉴스", "블룸버그", "로이터",
]


class NewsAnalyzer:
    """
    뉴스 분석기

    주요 기능:
    1. 뉴스 이벤트 유형 분류
    2. 뉴스 스코어 계산 (영향도 + 신선도 + 확산도)
    3. 관련 종목 매핑
    """

    def __init__(
        self,
        symbol_keyword_mapping: dict[str, list[str]] | None = None,
        min_news_score: float = 6.0,
    ):
        """
        Args:
            symbol_keyword_mapping: 종목-키워드 매핑 (None이면 기본값 사용)
            min_news_score: 최소 뉴스 스코어 임계값
        """
        self.symbol_mapping = symbol_keyword_mapping or SYMBOL_KEYWORD_MAPPING
        self.min_news_score = min_news_score
        self._build_keyword_index()

    def _build_keyword_index(self) -> None:
        """키워드 역인덱스 생성 (키워드 → 종목코드 목록)"""
        self.keyword_to_symbols: dict[str, list[str]] = {}
        for symbol, keywords in self.symbol_mapping.items():
            for keyword in keywords:
                keyword_lower = keyword.lower()
                if keyword_lower not in self.keyword_to_symbols:
                    self.keyword_to_symbols[keyword_lower] = []
                self.keyword_to_symbols[keyword_lower].append(symbol)

    def analyze_news(self, request: NewsAnalysisRequestDTO) -> NewsAnalysisResultDTO:
        """
        뉴스 분석 실행

        Args:
            request: 뉴스 분석 요청 DTO

        Returns:
            NewsAnalysisResultDTO: 분석 결과
        """
        analyzed_news: list[NewsItemDTO] = []
        symbol_scores: dict[str, float] = {}
        event_type_counts: dict[str, int] = {}

        for news in request.news_items:
            # 1. 이벤트 유형 분류
            news.event_type = self._classify_event_type(news)

            # 2. 뉴스 스코어 계산
            score_dto = self._calculate_news_score(news, request.target_date)

            # 3. 관련 종목 추출
            news.related_symbols = self._extract_related_symbols(news)

            # 필터링: 최소 스코어 이상 & 관련 종목 존재
            if score_dto.total_score >= request.min_news_score and news.related_symbols:
                analyzed_news.append(news)

                # 종목별 스코어 누적
                for symbol in news.related_symbols:
                    current_score = symbol_scores.get(symbol, 0.0)
                    symbol_scores[symbol] = max(current_score, score_dto.total_score)

                # 이벤트 유형 카운트
                if news.event_type:
                    event_key = news.event_type.value
                    event_type_counts[event_key] = event_type_counts.get(event_key, 0) + 1

        # 스코어 기준 상위 종목 추출
        sorted_symbols = sorted(
            symbol_scores.keys(),
            key=lambda s: symbol_scores[s],
            reverse=True,
        )

        return NewsAnalysisResultDTO(
            analysis_date=request.target_date,
            total_news_count=len(request.news_items),
            filtered_news_count=len(analyzed_news),
            candidate_symbols=sorted_symbols,
            symbol_scores=symbol_scores,
            event_type_distribution=event_type_counts,
        )

    def _classify_event_type(self, news: NewsItemDTO) -> NewsEventType | None:
        """
        뉴스 이벤트 유형 분류

        Args:
            news: 뉴스 아이템

        Returns:
            분류된 이벤트 유형 (없으면 None)
        """
        text = (news.title + " " + (news.content or "")).lower()

        event_scores: dict[NewsEventType, int] = {}

        for event_type, keywords in EVENT_TYPE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw.lower() in text)
            if score > 0:
                event_scores[event_type] = score

        if not event_scores:
            return None

        # 가장 높은 스코어의 이벤트 유형 반환
        return max(event_scores, key=lambda e: event_scores[e])

    def _calculate_news_score(
        self, news: NewsItemDTO, target_date: datetime
    ) -> NewsScoreDTO:
        """
        뉴스 스코어 계산

        스코어 구성:
        - 영향도 (0~5): 헤드라인 키워드, 본문 길이, 주요 매체 여부
        - 신선도 (0~3): 발생 시점 가중치
        - 확산도 (0~2): 현재는 단일 뉴스 기준으로 고정값

        Args:
            news: 뉴스 아이템
            target_date: 분석 대상 날짜

        Returns:
            NewsScoreDTO: 계산된 스코어
        """
        # 1. 영향도 점수 (0~5)
        impact_score = self._calculate_impact_score(news)

        # 2. 신선도 점수 (0~3)
        freshness_score = self._calculate_freshness_score(news, target_date)

        # 3. 확산도 점수 (0~2) - 단일 뉴스 기준
        spread_score = 1.0  # 기본값, 향후 동일 이벤트 기사 수로 계산

        return NewsScoreDTO(
            impact_score=min(5.0, impact_score),
            freshness_score=min(3.0, freshness_score),
            spread_score=min(2.0, spread_score),
        )

    def _calculate_impact_score(self, news: NewsItemDTO) -> float:
        """
        영향도 점수 계산 (0~5)

        요소:
        - 고영향 키워드 포함 여부 (+1.5)
        - 이벤트 유형 존재 (+1.0)
        - 주요 매체 여부 (+1.0)
        - 본문 길이 (0~1.5)
        """
        score = 0.0
        text = (news.title + " " + (news.content or "")).lower()

        # 고영향 키워드 체크
        has_high_impact = any(kw.lower() in text for kw in HIGH_IMPACT_KEYWORDS)
        if has_high_impact:
            score += 1.5

        # 이벤트 유형 존재
        if news.event_type:
            score += 1.0

        # 주요 매체 여부
        if any(source in news.source for source in MAJOR_NEWS_SOURCES):
            score += 1.0

        # 본문 길이 (300자 이상이면 추가 점수)
        content_length = len(news.content or "")
        if content_length >= 500:
            score += 1.5
        elif content_length >= 300:
            score += 1.0
        elif content_length >= 100:
            score += 0.5

        return score

    def _calculate_freshness_score(
        self, news: NewsItemDTO, target_date: datetime
    ) -> float:
        """
        신선도 점수 계산 (0~3)

        전일 저녁(18~22시)에 발생한 뉴스가 가장 높은 점수
        """
        news_time = news.published_at

        # 전일 저녁 18:00 ~ 22:00
        target_evening_start = datetime.combine(
            (target_date - timedelta(days=1)).date(), time(18, 0)
        )
        target_evening_end = datetime.combine(
            (target_date - timedelta(days=1)).date(), time(22, 0)
        )

        # 당일 프리마켓 (06:00 ~ 09:00)
        target_premarket_start = datetime.combine(target_date.date(), time(6, 0))
        target_premarket_end = datetime.combine(target_date.date(), time(9, 0))

        if target_evening_start <= news_time <= target_evening_end:
            # 전일 저녁: 최고 점수
            return 3.0
        elif target_premarket_start <= news_time <= target_premarket_end:
            # 당일 프리마켓: 높은 점수
            return 2.5
        elif news_time.date() == (target_date - timedelta(days=1)).date():
            # 전일 기타 시간
            return 1.5
        elif news_time.date() == target_date.date():
            # 당일
            return 2.0
        else:
            # 그 외 (오래된 뉴스)
            return 0.5

    def _extract_related_symbols(self, news: NewsItemDTO) -> list[str]:
        """
        뉴스에서 관련 종목 추출

        1. 제목과 본문에서 종목명/키워드 매칭
        2. 기존 related_symbols와 병합
        """
        text = (news.title + " " + (news.content or "")).lower()
        found_symbols: set[str] = set(news.related_symbols)

        # 키워드 매칭
        for keyword, symbols in self.keyword_to_symbols.items():
            if keyword in text:
                found_symbols.update(symbols)

        return list(found_symbols)

    def extract_keywords(self, text: str) -> list[str]:
        """텍스트에서 키워드 추출"""
        keywords: list[str] = []

        # 이벤트 유형 키워드
        for event_type, kw_list in EVENT_TYPE_KEYWORDS.items():
            for kw in kw_list:
                if kw.lower() in text.lower():
                    keywords.append(kw)

        # 고영향 키워드
        for kw in HIGH_IMPACT_KEYWORDS:
            if kw.lower() in text.lower():
                keywords.append(kw)

        return list(set(keywords))

    def update_symbol_mapping(self, symbol: str, keywords: list[str]) -> None:
        """종목-키워드 매핑 업데이트"""
        self.symbol_mapping[symbol] = keywords
        self._build_keyword_index()

    def get_symbol_keywords(self, symbol: str) -> list[str]:
        """종목의 키워드 목록 조회"""
        return self.symbol_mapping.get(symbol, [])
