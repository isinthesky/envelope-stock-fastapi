# -*- coding: utf-8 -*-
"""
DART API Client 테스트

재무 스크리닝 로직 및 데이터 검증 테스트
"""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from src.adapters.external.dart_api.client import DARTAPIClient
from src.adapters.external.dart_api.dto import (
    FinancialScreeningDTO,
    FinancialStatementDTO,
    PeriodFinancialDTO,
)
from src.adapters.external.dart_api.exceptions import DARTAPIError


class TestFinancialScreeningDTO:
    """FinancialScreeningDTO 테스트"""

    def test_filter_status_pass_when_all_conditions_met(self):
        """모든 조건 충족 시 PASS 반환"""
        dto = FinancialScreeningDTO(
            stock_code="005930",
            corp_code="00126380",
            corp_name="삼성전자",
            induty_code="26",
            periods=[],
            revenue_yoy=Decimal("10.5"),
            latest_operating_margin=Decimal("15.0"),
            is_consecutive_profit=True,
            is_turnaround=False,
            has_revenue_data=True,
            fs_type="CFS",
            passes_revenue_filter=True,
            passes_profit_filter=True,
        )

        assert dto.filter_status == "PASS"
        assert dto.passes_filter is True

    def test_filter_status_fail_when_no_revenue_data(self):
        """매출 데이터 없을 시 FAIL 반환"""
        dto = FinancialScreeningDTO(
            stock_code="005930",
            corp_code="00126380",
            corp_name="삼성전자",
            induty_code="26",
            periods=[],
            revenue_yoy=None,  # 데이터 없음
            latest_operating_margin=Decimal("15.0"),
            is_consecutive_profit=True,
            is_turnaround=False,
            has_revenue_data=False,  # 데이터 없음 표시
            fs_type="CFS",
            passes_revenue_filter=False,
            passes_profit_filter=True,
        )

        assert dto.filter_status == "FAIL"
        assert dto.has_revenue_data is False
        assert dto.revenue_yoy is None

    def test_filter_status_turnaround(self):
        """턴어라운드 종목은 TURNAROUND 반환"""
        dto = FinancialScreeningDTO(
            stock_code="005930",
            corp_code="00126380",
            corp_name="삼성전자",
            induty_code="26",
            periods=[],
            revenue_yoy=Decimal("5.0"),
            latest_operating_margin=Decimal("10.0"),
            is_consecutive_profit=False,
            is_turnaround=True,
            has_revenue_data=True,
            fs_type="CFS",
            passes_revenue_filter=True,
            passes_profit_filter=False,
        )

        assert dto.filter_status == "TURNAROUND"

    def test_filter_status_fail_when_revenue_negative(self):
        """매출 YoY 음수 시 FAIL 반환"""
        dto = FinancialScreeningDTO(
            stock_code="005930",
            corp_code="00126380",
            corp_name="삼성전자",
            induty_code="26",
            periods=[],
            revenue_yoy=Decimal("-5.0"),
            latest_operating_margin=Decimal("10.0"),
            is_consecutive_profit=True,
            is_turnaround=False,
            has_revenue_data=True,
            fs_type="CFS",
            passes_revenue_filter=False,  # 음수이므로 통과 못함
            passes_profit_filter=True,
        )

        assert dto.filter_status == "FAIL"

    def test_to_dict_with_none_revenue_yoy(self):
        """revenue_yoy가 None일 때 to_dict 정상 동작"""
        dto = FinancialScreeningDTO(
            stock_code="005930",
            corp_code="00126380",
            corp_name="삼성전자",
            induty_code="26",
            periods=[],
            revenue_yoy=None,
            latest_operating_margin=Decimal("10.0"),
            is_consecutive_profit=True,
            is_turnaround=False,
            has_revenue_data=False,
            fs_type="OFS",
        )

        result = dto.to_dict()
        assert result["revenue_yoy"] is None
        assert result["has_revenue_data"] is False
        assert result["fs_type"] == "OFS"


class TestDARTAPIClientFinancialScreening:
    """DART API Client 재무 스크리닝 테스트"""

    @pytest.fixture
    def dart_client(self):
        """DART 클라이언트 fixture"""
        client = DARTAPIClient()
        client._cache_loaded = True
        client._corp_code_cache = {
            "005930": MagicMock(corp_code="00126380"),
        }
        return client

    @pytest.mark.asyncio
    async def test_get_financial_screening_with_valid_data(self, dart_client):
        """정상 데이터로 재무 스크리닝"""
        # Mock 재무제표 데이터
        mock_statements = [
            MagicMock(
                account_nm="매출액",
                thstrm_amount=Decimal("1000000000000"),
            ),
            MagicMock(
                account_nm="영업이익",
                thstrm_amount=Decimal("150000000000"),
            ),
            MagicMock(
                account_nm="당기순이익",
                thstrm_amount=Decimal("100000000000"),
            ),
        ]

        with patch.object(dart_client, "get_financial_statements", new_callable=AsyncMock) as mock_fs:
            with patch.object(dart_client, "get_company_info", new_callable=AsyncMock) as mock_ci:
                mock_fs.return_value = mock_statements
                mock_ci.return_value = MagicMock(corp_name="삼성전자", induty_code="26")

                result = await dart_client.get_financial_screening("005930")

                assert result is not None
                assert result.stock_code == "005930"
                assert result.has_revenue_data is True

    @pytest.mark.asyncio
    async def test_get_financial_screening_with_zero_revenue(self, dart_client):
        """매출액이 0인 경우 데이터 부족 처리"""
        # 매출액이 0인 재무제표
        mock_statements = [
            MagicMock(
                account_nm="매출액",
                thstrm_amount=Decimal("0"),  # 매출액 0
            ),
            MagicMock(
                account_nm="영업이익",
                thstrm_amount=Decimal("150000000000"),
            ),
        ]

        with patch.object(dart_client, "get_financial_statements", new_callable=AsyncMock) as mock_fs:
            with patch.object(dart_client, "get_company_info", new_callable=AsyncMock) as mock_ci:
                mock_fs.return_value = mock_statements
                mock_ci.return_value = MagicMock(corp_name="테스트기업", induty_code="26")

                result = await dart_client.get_financial_screening("005930")

                # 매출액이 0이면 has_revenue_data가 False
                if result:
                    assert result.has_revenue_data is False
                    assert result.revenue_yoy is None

    @pytest.mark.asyncio
    async def test_get_financial_screening_ofs_fallback(self, dart_client):
        """CFS 없을 시 OFS로 fallback"""
        mock_statements_ofs = [
            MagicMock(
                account_nm="매출액",
                thstrm_amount=Decimal("500000000000"),
            ),
            MagicMock(
                account_nm="영업이익",
                thstrm_amount=Decimal("50000000000"),
            ),
        ]

        call_count = 0

        async def mock_get_fs(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            fs_div = kwargs.get("fs_div", "CFS")

            if fs_div == "CFS":
                return []  # CFS 데이터 없음
            else:
                return mock_statements_ofs  # OFS 데이터 있음

        with patch.object(dart_client, "get_financial_statements", side_effect=mock_get_fs):
            with patch.object(dart_client, "get_company_info", new_callable=AsyncMock) as mock_ci:
                mock_ci.return_value = MagicMock(corp_name="테스트기업", induty_code="26")

                result = await dart_client.get_financial_screening("005930")

                # OFS로 fallback 되었는지 확인
                if result:
                    assert result.fs_type == "OFS"


class TestDARTAPIClientCorpCode:
    """DART API Client 고유번호 조회 테스트"""

    @pytest.mark.asyncio
    async def test_load_corp_codes_validates_zip_response(self):
        """ZIP 응답 검증 테스트"""
        client = DARTAPIClient()

        # JSON 에러 응답 mock
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"status": "020", "message": "한도 초과"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get_client:
            mock_http_client = AsyncMock()
            mock_http_client.get.return_value = mock_response
            mock_get_client.return_value = mock_http_client

            with pytest.raises(DARTAPIError):
                await client.load_corp_codes()

    @pytest.mark.asyncio
    async def test_load_corp_codes_validates_zip_magic_bytes(self):
        """ZIP 파일 매직 바이트 검증 테스트"""
        client = DARTAPIClient()

        # 잘못된 바이너리 응답 mock
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "application/octet-stream"}
        mock_response.content = b"not a zip file"
        mock_response.raise_for_status = MagicMock()

        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get_client:
            mock_http_client = AsyncMock()
            mock_http_client.get.return_value = mock_response
            mock_get_client.return_value = mock_http_client

            with pytest.raises(DARTAPIError, match="ZIP 파일이 아닙니다"):
                await client.load_corp_codes()


class TestPeriodFinancialDTO:
    """PeriodFinancialDTO 테스트"""

    def test_period_financial_dto_creation(self):
        """PeriodFinancialDTO 생성 테스트"""
        dto = PeriodFinancialDTO(
            period="2024ANNUAL",
            period_type="ANNUAL",
            revenue=Decimal("1000000000000"),
            operating_profit=Decimal("150000000000"),
            operating_margin=Decimal("15.0"),
            net_income=Decimal("100000000000"),
        )

        assert dto.period == "2024ANNUAL"
        assert dto.period_type == "ANNUAL"
        assert dto.revenue == Decimal("1000000000000")
        assert dto.operating_margin == Decimal("15.0")
