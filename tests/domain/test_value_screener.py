# -*- coding: utf-8 -*-
"""
Value Stock Screener 테스트

네이버 API 클라이언트 및 가치주 스크리닝 기능 테스트
"""

import pytest

from src.adapters.external.naver.stock_client import NaverStockClient, get_naver_stock_client
from src.application.domain.screener.dto import (
    ValueScreenerCriteria,
    ValueStockItemDTO,
)


class TestNaverStockClient:
    """네이버 주식 API 클라이언트 테스트"""

    @pytest.fixture
    def client(self):
        """NaverStockClient 인스턴스 - 각 테스트마다 새로 생성"""
        return NaverStockClient()

    @pytest.mark.asyncio
    async def test_get_integration(self, client):
        """종목 통합 정보 조회 테스트"""
        # 삼성전자 조회
        result = await client.get_integration("005930")

        assert result is not None
        assert "stockName" in result
        assert result["stockName"] == "삼성전자"
        assert "totalInfos" in result

    @pytest.mark.asyncio
    async def test_get_finance_annual(self, client):
        """연간 재무 정보 조회 테스트"""
        # 삼성전자 조회 - 통합 데이터 사용
        result = await client.get_stock_financial_data("005930")

        assert result is not None
        assert result.retention_ratio is not None

    @pytest.mark.asyncio
    async def test_get_stock_financial_data(self, client):
        """종목 재무 데이터 통합 조회 테스트"""
        # 삼성전자 조회
        result = await client.get_stock_financial_data("005930")

        assert result is not None
        assert result.symbol == "005930"
        assert result.name == "삼성전자"
        assert result.market_cap > 0  # 시가총액이 양수
        assert result.retention_ratio is not None  # 유보율 존재

    @pytest.mark.asyncio
    async def test_get_stock_financial_data_other_stock(self, client):
        """다른 종목 재무 데이터 조회 테스트"""
        # NAVER 조회
        result = await client.get_stock_financial_data("035420")

        assert result is not None
        assert result.symbol == "035420"
        assert result.name == "NAVER"
        assert result.market_cap > 0

    @pytest.mark.asyncio
    async def test_get_stock_financial_data_invalid_symbol(self, client):
        """존재하지 않는 종목 조회 테스트"""
        result = await client.get_stock_financial_data("999999")

        # 존재하지 않는 종목은 None 반환
        assert result is None

    def test_market_cap_parsing(self, client):
        """시가총액 파싱 테스트"""
        # "821조 538억" 형태
        result = client._parse_market_cap("821조 538억")
        assert result == 821_053_800_000_000

        # "5,000억" 형태 -> 5000억 = 500,000,000,000 (5천억)
        result = client._parse_market_cap("5,000억")
        assert result == 500_000_000_000

        # "1조" 형태
        result = client._parse_market_cap("1조")
        assert result == 1_000_000_000_000

        # "-" 처리
        result = client._parse_market_cap("-")
        assert result == 0

        # "3,500억" 형태 -> 3500억
        result = client._parse_market_cap("3,500억")
        assert result == 350_000_000_000


class TestValueScreenerCriteria:
    """스크리닝 조건 DTO 테스트"""

    def test_default_criteria(self):
        """기본 조건 테스트"""
        criteria = ValueScreenerCriteria()

        assert criteria.max_market_cap == 1_000_000_000_000  # 1조원
        assert criteria.min_retention_ratio == 0
        assert criteria.min_quick_ratio == 0
        assert criteria.max_debt_ratio is None

    def test_custom_criteria(self):
        """사용자 정의 조건 테스트"""
        criteria = ValueScreenerCriteria(
            max_market_cap=500_000_000_000,
            min_retention_ratio=1000,
            min_quick_ratio=150,
            max_debt_ratio=50,
        )

        assert criteria.max_market_cap == 500_000_000_000
        assert criteria.min_retention_ratio == 1000
        assert criteria.min_quick_ratio == 150
        assert criteria.max_debt_ratio == 50


class TestValueStockItemDTO:
    """스크리닝 결과 항목 DTO 테스트"""

    def test_format_market_cap_trillion(self):
        """시가총액 표시 - 조 단위"""
        result = ValueStockItemDTO.format_market_cap(821_053_800_000_000)
        assert "조" in result

    def test_format_market_cap_billion(self):
        """시가총액 표시 - 억 단위"""
        result = ValueStockItemDTO.format_market_cap(500_000_000_000)
        assert "억" in result

    def test_format_market_cap_small(self):
        """시가총액 표시 - 원 단위"""
        result = ValueStockItemDTO.format_market_cap(50_000_000)
        assert "원" in result


class TestValueScreenerIntegration:
    """가치주 스크리닝 통합 테스트"""

    @pytest.fixture
    def client(self):
        """NaverStockClient 인스턴스 - 각 테스트마다 새로 생성"""
        return NaverStockClient()

    @pytest.mark.asyncio
    async def test_screening_large_cap_excluded(self, client):
        """대형주 제외 테스트"""
        # 삼성전자는 시가총액 800조 이상이므로 1조 조건에서 제외되어야 함
        data = await client.get_stock_financial_data("005930")

        assert data is not None
        criteria = ValueScreenerCriteria(max_market_cap=1_000_000_000_000)

        # 시가총액이 1조를 초과하므로 조건 불충족
        assert data.market_cap > criteria.max_market_cap

    @pytest.mark.asyncio
    async def test_screening_multiple_stocks(self, client):
        """복수 종목 스크리닝 테스트"""
        symbols = ["005930", "035420"]  # 삼성전자, NAVER
        results = []

        for symbol in symbols:
            data = await client.get_stock_financial_data(symbol)
            if data:
                results.append(data)

        # 모든 종목 조회 성공
        assert len(results) == 2

        # 모든 종목에 재무 데이터 존재
        for result in results:
            assert result.market_cap > 0
            assert result.retention_ratio is not None

    @pytest.mark.asyncio
    async def test_screening_criteria_filter(self, client):
        """스크리닝 조건 필터 테스트"""
        # 매우 관대한 조건
        criteria = ValueScreenerCriteria(
            max_market_cap=1_000_000_000_000_000,  # 1000조
            min_retention_ratio=0,
            min_quick_ratio=0,
        )

        data = await client.get_stock_financial_data("005930")

        assert data is not None
        # 관대한 조건에서는 삼성전자도 통과
        assert data.market_cap <= criteria.max_market_cap
        assert data.retention_ratio >= criteria.min_retention_ratio
        if data.quick_ratio is not None:
            assert data.quick_ratio >= criteria.min_quick_ratio
