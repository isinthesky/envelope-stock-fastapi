# -*- coding: utf-8 -*-
"""
Buy Strategy Service - 재무 필터 테스트

재무 스크리닝 필터 적용 로직 테스트
"""

import pytest
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from src.application.domain.strategy.buy_strategy_service import BuyStrategyService
from src.application.domain.strategy.dto import (
    GoldenCrossScanItemDTO,
    GoldenCrossScanListDTO,
)
from src.adapters.external.dart_api.dto import FinancialScreeningDTO


class TestFinancialFilterStatistics:
    """재무 필터 통계 분리 테스트"""

    @pytest.fixture
    def scan_result(self):
        """스캔 결과 fixture"""
        stocks = [
            GoldenCrossScanItemDTO(
                symbol="005930",
                name="삼성전자",
                market="KOSPI",
                current_price=Decimal("70000"),
                ma_short=Decimal("68000"),
                ma_long=Decimal("65000"),
                ma_gap_ratio=4.6,
                stoch_k=25.0,
                stoch_d=28.0,
                is_gc_active=True,
                gc_state="OPTIMAL_BUY",
            ),
            GoldenCrossScanItemDTO(
                symbol="000660",
                name="SK하이닉스",
                market="KOSPI",
                current_price=Decimal("150000"),
                ma_short=Decimal("145000"),
                ma_long=Decimal("140000"),
                ma_gap_ratio=3.5,
                stoch_k=28.0,
                stoch_d=30.0,
                is_gc_active=True,
                gc_state="BUY_INTEREST",
            ),
            GoldenCrossScanItemDTO(
                symbol="035720",
                name="카카오",
                market="KOSPI",
                current_price=Decimal("50000"),
                ma_short=Decimal("48000"),
                ma_long=Decimal("46000"),
                ma_gap_ratio=4.3,
                stoch_k=22.0,
                stoch_d=25.0,
                is_gc_active=True,
                gc_state="READY_TO_BUY",
            ),
            GoldenCrossScanItemDTO(
                symbol="068270",
                name="셀트리온",
                market="KOSPI",
                current_price=Decimal("180000"),
                ma_short=Decimal("175000"),
                ma_long=Decimal("170000"),
                ma_gap_ratio=2.9,
                stoch_k=45.0,
                stoch_d=42.0,
                is_gc_active=True,
                gc_state="WAITING_FOR_PULLBACK",
            ),
        ]

        return GoldenCrossScanListDTO(
            stocks=stocks,
            total_scanned=100,
            gc_active_count=50,
            pullback_waiting_count=20,
            buy_interest_count=2,
            ready_to_buy_count=1,
            optimal_buy_count=1,
            scan_time=datetime.now(),
        )

    @pytest.mark.asyncio
    async def test_error_and_fail_counted_separately(self, scan_result):
        """ERROR와 FAIL이 별도로 카운트되는지 테스트"""
        service = BuyStrategyService()

        # Mock screening results - 일부 성공, 일부 실패
        mock_screening_pass = FinancialScreeningDTO(
            stock_code="005930",
            corp_code="00126380",
            corp_name="삼성전자",
            induty_code="26",
            periods=[],
            revenue_yoy=Decimal("10.0"),
            latest_operating_margin=Decimal("15.0"),
            is_consecutive_profit=True,
            is_turnaround=False,
            has_revenue_data=True,
            fs_type="CFS",
            passes_revenue_filter=True,
            passes_profit_filter=True,
        )

        mock_screening_fail = FinancialScreeningDTO(
            stock_code="000660",
            corp_code="00164779",
            corp_name="SK하이닉스",
            induty_code="26",
            periods=[],
            revenue_yoy=Decimal("-5.0"),  # 매출 감소
            latest_operating_margin=Decimal("10.0"),
            is_consecutive_profit=True,
            is_turnaround=False,
            has_revenue_data=True,
            fs_type="CFS",
            passes_revenue_filter=False,
            passes_profit_filter=True,
        )

        # 035720(카카오)는 조회 실패 - ERROR로 처리되어야 함

        with patch("src.application.domain.strategy.buy_strategy_service.get_dart_client") as mock_dart:
            mock_client = AsyncMock()
            mock_dart.return_value = mock_client
            mock_client.load_corp_codes = AsyncMock()

            async def mock_screening(symbol):
                if symbol == "005930":
                    return mock_screening_pass
                elif symbol == "000660":
                    return mock_screening_fail
                else:
                    return None  # 조회 실패

            mock_client.get_financial_screening = mock_screening

            result = await service.apply_financial_filter(scan_result)

            # 통계 검증
            assert result.financial_pass_count == 1  # 삼성전자
            assert result.financial_fail_count == 1  # SK하이닉스 (조건 불충족)
            assert result.financial_error_count == 1  # 카카오 (조회 실패)
            assert result.financial_pending_count == 1  # 셀트리온 (필터 대상 아님)

    @pytest.mark.asyncio
    async def test_revenue_yoy_none_handling(self, scan_result):
        """revenue_yoy가 None인 경우 처리 테스트"""
        service = BuyStrategyService()

        # 매출 데이터 없는 스크리닝 결과
        mock_screening_no_revenue = FinancialScreeningDTO(
            stock_code="005930",
            corp_code="00126380",
            corp_name="삼성전자",
            induty_code="26",
            periods=[],
            revenue_yoy=None,  # 매출 데이터 없음
            latest_operating_margin=Decimal("15.0"),
            is_consecutive_profit=True,
            is_turnaround=False,
            has_revenue_data=False,
            fs_type="CFS",
            passes_revenue_filter=False,
            passes_profit_filter=True,
        )

        with patch("src.application.domain.strategy.buy_strategy_service.get_dart_client") as mock_dart:
            mock_client = AsyncMock()
            mock_dart.return_value = mock_client
            mock_client.load_corp_codes = AsyncMock()
            mock_client.get_financial_screening = AsyncMock(return_value=mock_screening_no_revenue)

            result = await service.apply_financial_filter(scan_result)

            # 삼성전자의 재무 필터 상태 확인
            samsung = next((s for s in result.stocks if s.symbol == "005930"), None)
            assert samsung is not None
            assert samsung.financial_filter_status == "FAIL"  # 매출 데이터 없으면 FAIL
            assert samsung.revenue_yoy is None


class TestGoldenCrossScanListDTO:
    """GoldenCrossScanListDTO 테스트"""

    def test_financial_error_count_field_exists(self):
        """financial_error_count 필드 존재 확인"""
        dto = GoldenCrossScanListDTO(
            stocks=[],
            total_scanned=100,
            gc_active_count=50,
            pullback_waiting_count=20,
            ready_to_buy_count=10,
            scan_time=datetime.now(),
            financial_pass_count=5,
            financial_fail_count=3,
            financial_error_count=2,  # 새로 추가된 필드
            turnaround_count=1,
            financial_pending_count=10,
        )

        assert dto.financial_error_count == 2
        assert dto.financial_fail_count == 3

    def test_default_values(self):
        """기본값 확인"""
        dto = GoldenCrossScanListDTO(
            stocks=[],
            total_scanned=100,
            gc_active_count=50,
            pullback_waiting_count=20,
            ready_to_buy_count=10,
            scan_time=datetime.now(),
        )

        assert dto.financial_error_count == 0
        assert dto.financial_fail_count == 0
        assert dto.financial_pass_count == 0
