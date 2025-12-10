# -*- coding: utf-8 -*-
"""
KIS API Client Metrics 테스트

SLO/모니터링 기능 테스트:
- p95 레이턴시 추적
- 에러율 추적
- 경고 출력
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from collections import deque

from src.adapters.external.kis_api.client import KISAPIClient


class TestKISClientMetrics:
    """KISAPIClient 메트릭스 테스트"""

    @pytest.fixture
    def client(self):
        """테스트용 KIS 클라이언트 (auth 모킹)"""
        with patch("src.adapters.external.kis_api.client.get_kis_auth") as mock_auth:
            mock_auth.return_value = MagicMock()
            mock_auth.return_value.get_auth_headers = AsyncMock(return_value={
                "authorization": "Bearer test_token",
                "appkey": "test_appkey",
                "appsecret": "test_appsecret",
            })
            client = KISAPIClient()
            return client

    def test_initial_metrics_state(self, client):
        """초기 메트릭스 상태"""
        assert len(client._events) == 0
        assert client._metrics_window_seconds == 300  # 5분
        assert client._p95_target_seconds == 2.5
        assert client._error_rate_target == 0.03  # 3%
        assert client._slo_min_events == 20

    @pytest.mark.asyncio
    async def test_record_metrics_success(self, client):
        """성공 메트릭 기록"""
        await client._record_metrics(duration=0.5, success=True)

        assert len(client._events) == 1
        _, duration, success = client._events[0]
        assert duration == 0.5
        assert success is True

    @pytest.mark.asyncio
    async def test_record_metrics_failure(self, client):
        """실패 메트릭 기록"""
        await client._record_metrics(duration=1.0, success=False)

        assert len(client._events) == 1
        _, duration, success = client._events[0]
        assert duration == 1.0
        assert success is False

    @pytest.mark.asyncio
    async def test_metrics_window_cleanup(self, client):
        """5분 윈도우 외 이벤트 정리"""
        loop = asyncio.get_event_loop()
        old_time = loop.time() - 400  # 5분(300초) 넘은 시간

        # 오래된 이벤트 직접 추가
        client._events.append((old_time, 0.5, True))
        client._events.append((old_time, 0.6, True))

        # 새 이벤트 추가 시 오래된 것 정리됨
        await client._record_metrics(duration=0.3, success=True)

        # 오래된 2개는 제거되고, 새 1개만 남음
        assert len(client._events) == 1

    @pytest.mark.asyncio
    async def test_slo_check_skipped_below_min_events(self, client, capsys):
        """최소 이벤트 미달 시 SLO 체크 스킵"""
        # 19개 이벤트 추가 (최소 20개 미달)
        for _ in range(19):
            await client._record_metrics(duration=5.0, success=True)  # 높은 지연

        captured = capsys.readouterr()
        assert "⚠️" not in captured.out  # 경고 없음

    @pytest.mark.asyncio
    async def test_p95_latency_warning(self, client, capsys):
        """p95 레이턴시 경고"""
        # 20개 이벤트 추가 (모두 높은 지연)
        for _ in range(20):
            await client._record_metrics(duration=3.0, success=True)  # 2.5초 초과

        captured = capsys.readouterr()
        assert "KIS REST latency p95" in captured.out
        assert "> 2.5s" in captured.out

    @pytest.mark.asyncio
    async def test_error_rate_warning(self, client, capsys):
        """에러율 경고"""
        # 20개 이벤트 중 5개 실패 (25% 에러율 > 3%)
        for i in range(20):
            success = i >= 5  # 처음 5개 실패
            await client._record_metrics(duration=0.5, success=success)

        captured = capsys.readouterr()
        assert "KIS REST error rate" in captured.out
        assert "exceeds" in captured.out

    @pytest.mark.asyncio
    async def test_no_warning_when_within_slo(self, client, capsys):
        """SLO 내 정상 동작 시 경고 없음"""
        # 20개 성공 이벤트 (낮은 지연)
        for _ in range(20):
            await client._record_metrics(duration=0.5, success=True)  # 2.5초 미만

        captured = capsys.readouterr()
        assert "⚠️" not in captured.out

    def test_percentile_calculation(self, client):
        """퍼센타일 계산 정확도"""
        # 단순 케이스
        data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        p50 = client._percentile(data, 0.50)
        p95 = client._percentile(data, 0.95)

        assert p50 == pytest.approx(5.5, rel=0.01)
        assert p95 == pytest.approx(9.55, rel=0.01)

    def test_percentile_empty_data(self, client):
        """빈 데이터 퍼센타일"""
        result = client._percentile([], 0.95)
        assert result == 0.0

    def test_percentile_single_element(self, client):
        """단일 요소 퍼센타일"""
        result = client._percentile([5.0], 0.95)
        assert result == 5.0

    @pytest.mark.asyncio
    async def test_metrics_thread_safety(self, client):
        """메트릭 기록 동시성 테스트"""
        async def record_batch(n: int, duration: float, success: bool):
            for _ in range(n):
                await client._record_metrics(duration=duration, success=success)

        # 동시에 여러 태스크 실행
        await asyncio.gather(
            record_batch(10, 0.5, True),
            record_batch(10, 0.6, True),
            record_batch(10, 0.7, False),
        )

        # 모든 이벤트가 기록되어야 함
        assert len(client._events) == 30

    @pytest.mark.asyncio
    async def test_mixed_success_failure_metrics(self, client, capsys):
        """혼합 성공/실패 메트릭"""
        # 정확히 3% 에러율 (20개 중 1개 실패 = 5%)
        for i in range(20):
            success = i != 0  # 첫 번째만 실패
            await client._record_metrics(duration=0.5, success=success)

        captured = capsys.readouterr()
        # 5% > 3%이므로 경고 발생
        assert "error rate" in captured.out


class TestKISClientBackoff:
    """KISAPIClient 백오프 로직 테스트"""

    @pytest.fixture
    def client(self):
        """테스트용 KIS 클라이언트"""
        with patch("src.adapters.external.kis_api.client.get_kis_auth") as mock_auth:
            mock_auth.return_value = MagicMock()
            client = KISAPIClient()
            return client

    @pytest.mark.asyncio
    async def test_reset_backoff(self, client):
        """백오프 리셋"""
        # 백오프 상태 설정
        client._consecutive_backoff_errors = 5
        client._backoff_stage = 2
        client._backoff_cycles = 1

        await client._reset_backoff()

        assert client._consecutive_backoff_errors == 0
        assert client._backoff_stage == 0
        assert client._backoff_cycles == 0


class TestSlidingWindowRateLimiter:
    """SlidingWindowRateLimiter 테스트"""

    @pytest.mark.asyncio
    async def test_rate_limiter_capacity(self):
        """Rate Limiter 용량 테스트"""
        from src.adapters.external.kis_api.client import SlidingWindowRateLimiter

        limiter = SlidingWindowRateLimiter(capacity=5, window_seconds=1)

        # 5개 요청은 즉시 통과
        for _ in range(5):
            await limiter.acquire()

        assert len(limiter.timestamps) == 5

    @pytest.mark.asyncio
    async def test_rate_limiter_window_cleanup(self):
        """Rate Limiter 윈도우 정리"""
        from src.adapters.external.kis_api.client import SlidingWindowRateLimiter

        limiter = SlidingWindowRateLimiter(capacity=5, window_seconds=1)

        # 윈도우보다 오래된 타임스탬프는 정리됨
        loop = asyncio.get_event_loop()
        old_time = loop.time() - 2  # 2초 전
        limiter.timestamps.append(old_time)

        await limiter.acquire()

        # 오래된 것은 제거되고 새 것만 남음
        assert len(limiter.timestamps) == 1
