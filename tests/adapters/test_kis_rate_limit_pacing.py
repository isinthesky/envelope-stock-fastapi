# -*- coding: utf-8 -*-
"""
KIS API Rate Limit 페이싱/재시도 테스트

- SlidingWindowRateLimiter: 윈도우 상한 + 연속 호출 최소 간격 페이싱
- EGW00201(초당 거래건수 초과) 응답 시 지수 백오프 재시도
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.adapters.external.kis_api.client import KISAPIClient, SlidingWindowRateLimiter
from src.adapters.external.kis_api.exceptions import KISAPIError
from src.settings.config import settings

EGW00201_BODY = {
    "rt_cd": "1",
    "msg_cd": "EGW00201",
    "msg1": "초당 거래건수를 초과하였습니다.",
}

OK_BODY = {"rt_cd": "0", "msg_cd": "OK", "msg1": "", "output": {}}


def _response(status_code: int, body: dict) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=body,
        request=httpx.Request("GET", "https://test.local/uapi/test"),
    )


class SequencedHTTPClient:
    """호출 순서대로 미리 정의된 응답을 반환하는 가짜 httpx 클라이언트"""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def get(self, *args, **kwargs) -> httpx.Response:
        _ = args, kwargs
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response

    async def post(self, *args, **kwargs) -> httpx.Response:
        _ = args, kwargs
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


def _make_client(monkeypatch: pytest.MonkeyPatch, http_client) -> KISAPIClient:
    client = KISAPIClient()
    client.auth = MagicMock()
    client.auth.get_auth_headers = AsyncMock(return_value={})
    client.auth.refresh_token = AsyncMock()
    client.rate_limiter = MagicMock()
    client.rate_limiter.acquire = AsyncMock()
    monkeypatch.setattr(client, "_get_client", AsyncMock(return_value=http_client))
    return client


class TestSlidingWindowPacing:
    """SlidingWindowRateLimiter 페이싱 동작 (실측 기반, 짧은 윈도우 사용)"""

    async def test_min_interval_spaces_consecutive_acquires(self) -> None:
        limiter = SlidingWindowRateLimiter(
            capacity=100, window_seconds=1, min_interval=0.05
        )
        loop = asyncio.get_event_loop()
        started = loop.time()
        for _ in range(4):
            await limiter.acquire()
        elapsed = loop.time() - started

        # 4회 호출 = 최소 3번의 간격 대기 (3 * 0.05 = 0.15s)
        assert elapsed >= 0.14

    async def test_window_capacity_still_enforced(self) -> None:
        limiter = SlidingWindowRateLimiter(
            capacity=2, window_seconds=0.3, min_interval=0.0
        )
        loop = asyncio.get_event_loop()
        started = loop.time()
        for _ in range(6):
            await limiter.acquire()
        elapsed = loop.time() - started

        # 2건/0.3초 윈도우 → 6건은 최소 2 윈도우(약 0.6초) 이상 소요
        assert elapsed >= 0.55

    async def test_no_min_interval_allows_burst_within_capacity(self) -> None:
        limiter = SlidingWindowRateLimiter(
            capacity=10, window_seconds=1, min_interval=0.0
        )
        loop = asyncio.get_event_loop()
        started = loop.time()
        for _ in range(10):
            await limiter.acquire()
        elapsed = loop.time() - started

        # 간격 페이싱이 없으면 capacity까지는 즉시 통과
        assert elapsed < 0.1

    async def test_min_interval_enforced_even_after_window_eviction(self) -> None:
        # min_interval > window_seconds 설정: 윈도우 경과로 timestamps가 전부
        # evict돼도 최소 간격 페이싱은 유지되어야 한다
        # (회귀 방지: timestamps[-1] 기반 spacing 검사는 evict 후 조기 통과했음)
        limiter = SlidingWindowRateLimiter(
            capacity=5, window_seconds=0.05, min_interval=0.2
        )
        loop = asyncio.get_event_loop()
        started = loop.time()
        await limiter.acquire()
        # 윈도우(0.05s)보다 길게 대기해 timestamps를 전부 비운다
        await asyncio.sleep(0.1)
        await limiter.acquire()
        elapsed = loop.time() - started

        # 두 번째 acquire는 min_interval(0.2s) 이전에 통과하면 안 된다
        assert elapsed >= 0.19

    def test_client_derives_min_interval_from_capacity(self) -> None:
        client = KISAPIClient()

        if settings.kis_api_rate_min_interval_ms > 0:
            expected = settings.kis_api_rate_min_interval_ms / 1000.0
        else:
            expected = (
                settings.kis_api_rate_window_seconds / settings.kis_api_rate_limit
            )
        assert client.rate_limiter.min_interval == pytest.approx(expected)


class TestAcquireOrdering:
    """auth 헤더 확보 → rate_limiter.acquire → HTTP 전송 순서 (M3 회귀 방지)

    순서가 반대면 콜드 토큰 갱신 대기 중 rate limit 슬롯을 쥔 요청들이
    갱신 직후 일제히 나가 버스트가 된다.
    """

    class _RecordingHTTPClient:
        def __init__(self, events: list[str]) -> None:
            self.events = events

        async def get(self, *args, **kwargs) -> httpx.Response:
            _ = args, kwargs
            self.events.append("http")
            return _response(200, OK_BODY)

        async def post(self, *args, **kwargs) -> httpx.Response:
            _ = args, kwargs
            self.events.append("http")
            return _response(200, OK_BODY)

    def _make_recording_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[KISAPIClient, list[str]]:
        events: list[str] = []
        client = _make_client(monkeypatch, self._RecordingHTTPClient(events))

        async def record_headers(*args, **kwargs) -> dict:
            _ = args, kwargs
            events.append("headers")
            return {}

        async def record_acquire(*args, **kwargs) -> None:
            _ = args, kwargs
            events.append("acquire")

        client.auth.get_auth_headers = AsyncMock(side_effect=record_headers)
        client.rate_limiter.acquire = AsyncMock(side_effect=record_acquire)
        return client, events

    async def test_get_acquires_headers_before_rate_limit_slot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, events = self._make_recording_client(monkeypatch)

        data = await client.get("/uapi/test")

        assert data["rt_cd"] == "0"
        assert events == ["headers", "acquire", "http"]

    async def test_post_acquires_headers_before_rate_limit_slot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, events = self._make_recording_client(monkeypatch)

        data = await client.post("/uapi/test", json={})

        assert data["rt_cd"] == "0"
        assert events == ["headers", "acquire", "http"]


class TestEGW00201Backoff:
    """EGW00201(HTTP 500) 응답에 대한 지수 백오프 재시도"""

    async def test_retries_with_exponential_backoff_then_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        http_client = SequencedHTTPClient(
            [
                _response(500, EGW00201_BODY),
                _response(500, EGW00201_BODY),
                _response(200, OK_BODY),
            ]
        )
        client = _make_client(monkeypatch, http_client)

        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(
            "src.adapters.external.kis_api.client.asyncio.sleep", fake_sleep
        )

        data = await client.get("/uapi/test")

        assert data["rt_cd"] == "0"
        assert http_client.calls == 3

        base = settings.kis_api_rate_limit_backoff_base_seconds
        assert sleeps == [base, base * 2]

        # 재시도마다 rate limiter를 다시 통과해야 한다 (페이싱 유지)
        assert client.rate_limiter.acquire.await_count == 3
        # EGW00201 재시도는 토큰 강제 갱신을 유발하지 않는다
        client.auth.refresh_token.assert_not_awaited()

    async def test_raises_after_max_retries_exhausted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        http_client = SequencedHTTPClient([_response(500, EGW00201_BODY)])
        client = _make_client(monkeypatch, http_client)

        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(
            "src.adapters.external.kis_api.client.asyncio.sleep", fake_sleep
        )

        with pytest.raises(KISAPIError):
            await client.get("/uapi/test")

        max_retries = settings.kis_api_rate_limit_max_retries
        base = settings.kis_api_rate_limit_backoff_base_seconds
        assert http_client.calls == max_retries + 1
        assert sleeps == [base * (2**i) for i in range(max_retries)]


class TestEGW00201BackoffPost:
    """POST 경로도 GET과 동일하게 EGW00201 지수 백오프 재시도를 수행해야 한다"""

    async def test_post_retries_then_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        http_client = SequencedHTTPClient(
            [
                _response(500, EGW00201_BODY),
                _response(500, EGW00201_BODY),
                _response(200, OK_BODY),
            ]
        )
        client = _make_client(monkeypatch, http_client)

        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(
            "src.adapters.external.kis_api.client.asyncio.sleep", fake_sleep
        )

        data = await client.post("/uapi/test", json={})

        assert data["rt_cd"] == "0"
        assert http_client.calls == 3

        base = settings.kis_api_rate_limit_backoff_base_seconds
        assert sleeps == [base, base * 2]

        # 재시도마다 rate limiter를 다시 통과해야 한다 (페이싱 유지)
        assert client.rate_limiter.acquire.await_count == 3
        # EGW00201 재시도는 토큰 강제 갱신을 유발하지 않는다
        client.auth.refresh_token.assert_not_awaited()

    async def test_post_raises_after_max_retries_exhausted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        http_client = SequencedHTTPClient([_response(500, EGW00201_BODY)])
        client = _make_client(monkeypatch, http_client)

        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(
            "src.adapters.external.kis_api.client.asyncio.sleep", fake_sleep
        )

        with pytest.raises(KISAPIError):
            await client.post("/uapi/test", json={})

        max_retries = settings.kis_api_rate_limit_max_retries
        base = settings.kis_api_rate_limit_backoff_base_seconds
        assert http_client.calls == max_retries + 1
        assert sleeps == [base * (2**i) for i in range(max_retries)]
