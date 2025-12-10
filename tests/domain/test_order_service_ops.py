# -*- coding: utf-8 -*-
"""
Order Service Ops 테스트

주문 흐름 운영 관련 기능 테스트:
- 주문 간격 강제 (order pacing)
- 정정/취소 횟수 제한
- 타임아웃 및 재시도 로직
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.adapters.external.kis_api.exceptions import KISAPIError, KISRateLimitError
from src.application.common.exceptions import OrderError
from src.application.domain.order.service import OrderService


class TestOrderPacing:
    """주문 간격 강제 테스트"""

    @pytest.fixture
    def service(self):
        """테스트용 OrderService (모킹)"""
        mock_kis_client = MagicMock()
        service = OrderService(kis_client=mock_kis_client, session=None)
        return service

    @pytest.mark.asyncio
    async def test_first_order_no_delay(self, service):
        """첫 주문은 대기 없이 즉시 처리"""
        loop = asyncio.get_event_loop()
        start = loop.time()

        await service._enforce_order_pacing("005930")

        elapsed = loop.time() - start
        # 첫 주문은 즉시 통과 (10ms 이내)
        assert elapsed < 0.01

    @pytest.mark.asyncio
    async def test_global_min_interval(self, service):
        """전역 최소 간격(150ms) 적용"""
        # 첫 주문
        await service._enforce_order_pacing("005930")

        loop = asyncio.get_event_loop()
        start = loop.time()

        # 두 번째 주문 (다른 종목)
        await service._enforce_order_pacing("000660")

        elapsed = loop.time() - start
        # 최소 150ms 대기 (설정 값: order_min_interval_ms = 150)
        assert elapsed >= 0.14  # 약간의 여유

    @pytest.mark.asyncio
    async def test_same_symbol_interval(self, service):
        """동일 종목 간격(300ms) 적용"""
        symbol = "005930"

        # 첫 주문
        await service._enforce_order_pacing(symbol)

        loop = asyncio.get_event_loop()
        start = loop.time()

        # 동일 종목 두 번째 주문
        await service._enforce_order_pacing(symbol)

        elapsed = loop.time() - start
        # 동일 종목은 300ms 대기 (설정 값: order_same_symbol_interval_ms = 300)
        assert elapsed >= 0.29  # 약간의 여유

    @pytest.mark.asyncio
    async def test_concurrent_orders_sequenced(self, service):
        """동시 주문 요청이 순차적으로 처리됨"""
        results = []

        async def order_task(symbol: str, task_id: int):
            await service._enforce_order_pacing(symbol)
            results.append(task_id)

        # 동시에 3개 주문 시작
        await asyncio.gather(
            order_task("005930", 1),
            order_task("000660", 2),
            order_task("035720", 3),
        )

        # 모든 주문이 처리됨
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_timestamps_updated(self, service):
        """타임스탬프가 정상 업데이트됨"""
        assert service._last_order_at is None
        assert len(service._last_order_at_by_symbol) == 0

        await service._enforce_order_pacing("005930")

        assert service._last_order_at is not None
        assert "005930" in service._last_order_at_by_symbol


class TestAmendLimit:
    """정정/취소 횟수 제한 테스트"""

    @pytest.fixture
    def service(self):
        """테스트용 OrderService"""
        mock_kis_client = MagicMock()
        return OrderService(kis_client=mock_kis_client, session=None)

    def test_first_amend_allowed(self, service):
        """첫 정정 시도 허용"""
        # 예외 없이 통과
        service._enforce_amend_limit("ORDER_001")
        assert service._amend_counts["ORDER_001"] == 1

    def test_multiple_amends_within_limit(self, service):
        """한도 내 여러 번 정정 허용 (최대 5회)"""
        order_id = "ORDER_002"

        for i in range(5):
            service._enforce_amend_limit(order_id)
            assert service._amend_counts[order_id] == i + 1

    def test_exceed_amend_limit_raises_error(self, service):
        """한도 초과 시 OrderError 발생"""
        order_id = "ORDER_003"

        # 5회까지 허용
        for _ in range(5):
            service._enforce_amend_limit(order_id)

        # 6번째 시도에서 예외 발생
        with pytest.raises(OrderError, match="Amendment/cancel limit exceeded"):
            service._enforce_amend_limit(order_id)

    def test_separate_order_counts(self, service):
        """주문별로 개별 카운트"""
        service._enforce_amend_limit("ORDER_A")
        service._enforce_amend_limit("ORDER_A")
        service._enforce_amend_limit("ORDER_B")

        assert service._amend_counts["ORDER_A"] == 2
        assert service._amend_counts["ORDER_B"] == 1


class TestPostWithRetry:
    """타임아웃 및 재시도 로직 테스트"""

    @pytest.fixture
    def service(self):
        """테스트용 OrderService"""
        mock_kis_client = MagicMock()
        mock_kis_client.post = AsyncMock()
        return OrderService(kis_client=mock_kis_client, session=None)

    @pytest.mark.asyncio
    async def test_success_no_retry(self, service):
        """성공 시 재시도 없음"""
        expected_result = {"rt_cd": "0", "output": {"ODNO": "12345"}}
        service.kis_client.post.return_value = expected_result

        result = await service._post_with_retry(
            "/api/order", {"symbol": "005930"}, {"tr_id": "TTTC0802U"}
        )

        assert result == expected_result
        assert service.kis_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_timeout_retry_success(self, service):
        """타임아웃 후 재시도 성공"""
        expected_result = {"rt_cd": "0", "output": {"ODNO": "12345"}}
        service.kis_client.post.side_effect = [
            asyncio.TimeoutError(),
            expected_result,
        ]

        with patch("src.application.domain.order.service.settings") as mock_settings:
            mock_settings.order_response_timeout = 2.5
            mock_settings.order_retry_delay_seconds = 0.01  # 테스트용 짧은 대기

            result = await service._post_with_retry(
                "/api/order", {"symbol": "005930"}, {"tr_id": "TTTC0802U"}
            )

        assert result == expected_result
        assert service.kis_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_httpx_timeout_retry(self, service):
        """httpx 타임아웃 재시도"""
        expected_result = {"rt_cd": "0"}
        service.kis_client.post.side_effect = [
            httpx.TimeoutException("Connection timeout"),
            expected_result,
        ]

        with patch("src.application.domain.order.service.settings") as mock_settings:
            mock_settings.order_response_timeout = 2.5
            mock_settings.order_retry_delay_seconds = 0.01

            result = await service._post_with_retry(
                "/api/order", {}, {}
            )

        assert result == expected_result
        assert service.kis_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_rate_limit_retry(self, service):
        """Rate Limit(429) 에러 재시도"""
        expected_result = {"rt_cd": "0"}
        service.kis_client.post.side_effect = [
            KISRateLimitError("Too many requests"),
            expected_result,
        ]

        with patch("src.application.domain.order.service.settings") as mock_settings:
            mock_settings.order_response_timeout = 2.5
            mock_settings.order_retry_delay_seconds = 0.01

            result = await service._post_with_retry(
                "/api/order", {}, {}
            )

        assert result == expected_result

    @pytest.mark.asyncio
    async def test_server_error_retry(self, service):
        """서버 에러(5xx) 재시도"""
        expected_result = {"rt_cd": "0"}
        service.kis_client.post.side_effect = [
            KISAPIError(message="Internal Server Error", error_code="500"),
            expected_result,
        ]

        with patch("src.application.domain.order.service.settings") as mock_settings:
            mock_settings.order_response_timeout = 2.5
            mock_settings.order_retry_delay_seconds = 0.01

            result = await service._post_with_retry(
                "/api/order", {}, {}
            )

        assert result == expected_result

    @pytest.mark.asyncio
    async def test_non_retryable_error_no_retry(self, service):
        """재시도 불가 에러는 즉시 예외 발생"""
        service.kis_client.post.side_effect = KISAPIError(
            message="Invalid parameter", error_code="400"
        )

        with pytest.raises(KISAPIError):
            await service._post_with_retry("/api/order", {}, {})

        # 재시도 없이 1회만 호출
        assert service.kis_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_also_fails(self, service):
        """재시도도 실패하면 예외 발생"""
        service.kis_client.post.side_effect = [
            asyncio.TimeoutError(),
            asyncio.TimeoutError(),
        ]

        with patch("src.application.domain.order.service.settings") as mock_settings:
            mock_settings.order_response_timeout = 2.5
            mock_settings.order_retry_delay_seconds = 0.01

            with pytest.raises(asyncio.TimeoutError):
                await service._post_with_retry("/api/order", {}, {})

        # 최초 1회 + 재시도 1회 = 2회
        assert service.kis_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_parameter_passed(self, service):
        """타임아웃 파라미터가 정상 전달됨"""
        service.kis_client.post.return_value = {"rt_cd": "0"}

        with patch("src.application.domain.order.service.settings") as mock_settings:
            mock_settings.order_response_timeout = 2.5
            mock_settings.order_retry_delay_seconds = 5.0

            await service._post_with_retry(
                "/api/order", {"data": "test"}, {"header": "value"}
            )

        # timeout 파라미터 확인
        call_kwargs = service.kis_client.post.call_args
        assert call_kwargs.kwargs["timeout"] == 2.5


class TestIsRetryableOrderError:
    """재시도 가능 오류 판정 테스트"""

    @pytest.fixture
    def service(self):
        """테스트용 OrderService"""
        mock_kis_client = MagicMock()
        return OrderService(kis_client=mock_kis_client, session=None)

    def test_asyncio_timeout_is_retryable(self, service):
        """asyncio.TimeoutError는 재시도 가능"""
        error = asyncio.TimeoutError()
        assert service._is_retryable_order_error(error) is True

    def test_httpx_timeout_is_retryable(self, service):
        """httpx.TimeoutException은 재시도 가능"""
        error = httpx.TimeoutException("timeout")
        assert service._is_retryable_order_error(error) is True

    def test_rate_limit_error_is_retryable(self, service):
        """KISRateLimitError는 재시도 가능"""
        error = KISRateLimitError("rate limit")
        assert service._is_retryable_order_error(error) is True

    def test_server_error_500_is_retryable(self, service):
        """500 에러는 재시도 가능"""
        error = KISAPIError(message="Internal Error", error_code="500")
        assert service._is_retryable_order_error(error) is True

    def test_server_error_503_is_retryable(self, service):
        """503 에러는 재시도 가능"""
        error = KISAPIError(message="Service Unavailable", error_code="503")
        assert service._is_retryable_order_error(error) is True

    def test_error_code_429_is_retryable(self, service):
        """429 에러 코드는 재시도 가능"""
        error = KISAPIError(message="Too Many Requests", error_code="429")
        assert service._is_retryable_order_error(error) is True

    def test_client_error_400_not_retryable(self, service):
        """400 에러는 재시도 불가"""
        error = KISAPIError(message="Bad Request", error_code="400")
        assert service._is_retryable_order_error(error) is False

    def test_client_error_401_not_retryable(self, service):
        """401 에러는 재시도 불가"""
        error = KISAPIError(message="Unauthorized", error_code="401")
        assert service._is_retryable_order_error(error) is False

    def test_generic_exception_not_retryable(self, service):
        """일반 예외는 재시도 불가"""
        error = ValueError("some error")
        assert service._is_retryable_order_error(error) is False

    def test_kis_api_error_without_code_not_retryable(self, service):
        """에러 코드 없는 KISAPIError는 재시도 불가"""
        error = KISAPIError(message="Unknown error", error_code=None)
        assert service._is_retryable_order_error(error) is False


class TestOrderServiceInitialization:
    """OrderService 초기화 테스트"""

    def test_initial_state(self):
        """초기 상태 확인"""
        mock_kis_client = MagicMock()
        service = OrderService(kis_client=mock_kis_client, session=None)

        assert service._last_order_at is None
        assert service._last_order_at_by_symbol == {}
        assert service._amend_counts == {}
        assert isinstance(service._order_lock, asyncio.Lock)
