# -*- coding: utf-8 -*-
"""
KIS API Client - REST API 호출 클라이언트

한국투자증권 Open API REST 호출 추상화 및 에러 처리
"""

import asyncio
from collections import deque
import math
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.adapters.external.kis_api.auth import get_kis_auth
from src.adapters.external.kis_api.exceptions import (
    KISAPIError,
    KISAuthError,
    KISRateLimitError,
)
from src.settings.config import settings


class SlidingWindowRateLimiter:
    """초당 요청 제한을 위한 슬라이딩 윈도우 Rate Limiter

    - capacity/window_seconds: 윈도우당 최대 허용 요청 수 (버스트 상한)
    - min_interval: 연속 요청 간 최소 간격 (초). 0이면 간격 페이싱 없이
      윈도우 상한만 적용. 간격을 주면 윈도우 시작 시점에 capacity만큼
      몰아서 나가는 버스트를 균등 페이싱으로 완화한다.
    """

    def __init__(
        self,
        capacity: int,
        window_seconds: float = 1,
        min_interval: float = 0.0,
    ) -> None:
        self.capacity = capacity
        self.window_seconds = window_seconds
        self.min_interval = max(min_interval, 0.0)
        self.timestamps: deque[float] = deque()
        # 마지막 허용 시각. timestamps는 window 경과 시 evict되므로
        # min_interval > window_seconds 설정에서도 간격 페이싱이 유지되도록
        # evict와 무관한 별도 변수로 관리한다.
        self._last_grant: float | None = None
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        """허용량/최소 간격을 만족할 때까지 대기"""
        loop = asyncio.get_event_loop()
        while True:
            async with self.lock:
                now = loop.time()
                while self.timestamps and now - self.timestamps[0] >= self.window_seconds:
                    self.timestamps.popleft()

                spacing_ok = (
                    self._last_grant is None
                    or now - self._last_grant >= self.min_interval
                )
                if len(self.timestamps) < self.capacity and spacing_ok:
                    self.timestamps.append(now)
                    self._last_grant = now
                    return

                if len(self.timestamps) >= self.capacity:
                    sleep_for = self.window_seconds - (now - self.timestamps[0])
                else:
                    sleep_for = self.min_interval - (now - self._last_grant)

            await asyncio.sleep(max(sleep_for, 0.001))


class KISAPIClient:
    """
    KIS Open API REST 클라이언트

    인증, 재시도, 에러 처리, Rate Limiting 자동 관리
    커넥션 풀링을 통한 성능 최적화
    """

    def __init__(self) -> None:
        self.auth = get_kis_auth()
        self.base_url = settings.kis_base_url
        self.rate_limit_semaphore = asyncio.Semaphore(settings.kis_api_rate_limit)
        # 연속 호출 최소 간격: 명시 설정(ms)이 있으면 사용, 없으면 window/capacity 균등 분배
        if settings.kis_api_rate_min_interval_ms > 0:
            min_interval = settings.kis_api_rate_min_interval_ms / 1000.0
        else:
            min_interval = settings.kis_api_rate_window_seconds / max(
                settings.kis_api_rate_limit, 1
            )
        self.rate_limiter = SlidingWindowRateLimiter(
            capacity=settings.kis_api_rate_limit,
            window_seconds=settings.kis_api_rate_window_seconds,
            min_interval=min_interval,
        )
        self._backoff_lock = asyncio.Lock()
        self._consecutive_backoff_errors = 0
        self._backoff_stage = 0
        self._backoff_cycles = 0
        self._metrics_lock = asyncio.Lock()
        self._events: deque[tuple[float, float, bool]] = deque()
        self._metrics_window_seconds = 300  # 5분
        self._p95_target_seconds = 2.5
        self._error_rate_target = 0.03
        self._slo_min_events = 20

        # 커넥션 풀링을 위한 공유 httpx.AsyncClient
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        """
        httpx.AsyncClient 인스턴스 반환 (Lazy 초기화, 커넥션 풀링)

        Returns:
            httpx.AsyncClient: 공유 HTTP 클라이언트
        """
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        timeout=settings.kis_api_timeout,
                        limits=httpx.Limits(
                            max_keepalive_connections=20,
                            max_connections=50,
                            keepalive_expiry=30.0,
                        ),
                    )
        return self._client

    async def aclose(self) -> None:
        """
        httpx.AsyncClient 리소스 정리

        애플리케이션 종료 시 호출 필요
        """
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ==================== HTTP 메서드 ====================

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        GET 요청

        Args:
            path: API 경로 (예: /uapi/domestic-stock/v1/quotations/inquire-price)
            params: 쿼리 파라미터
            headers: 추가 헤더
            timeout: 요청 타임아웃 (초), None이면 기본값 사용

        Returns:
            dict[str, Any]: API 응답 데이터

        Raises:
            KISAPIError: API 호출 실패
        """
        async with self.rate_limit_semaphore:
            loop = asyncio.get_event_loop()
            started_at = loop.time()
            url = f"{self.base_url}{path}"
            client = await self._get_client()

            token_refreshed = False
            rate_limit_retries = 0

            while True:
                # 헤더(토큰) 확보를 먼저 하고, 실제 HTTP 호출 직전에 acquire.
                # 반대로 하면 콜드 토큰 갱신 시 auth lock에 대기하던 요청들이
                # 이미 rate limit 슬롯을 쥔 채 갱신 직후 일제히 나가 버스트가 됨.
                auth_headers = await self.auth.get_auth_headers(force_refresh=False)
                if headers:
                    auth_headers.update(headers)

                await self.rate_limiter.acquire()
                try:
                    response = await client.get(
                        url,
                        params=params,
                        headers=auth_headers,
                        timeout=timeout,  # None이면 클라이언트 기본값 사용
                    )
                    data = self._handle_response(response)
                    await self._record_metrics(loop.time() - started_at, success=True)
                    await self._reset_backoff()
                    return data
                except httpx.HTTPStatusError as e:
                    mapped_error = self._map_http_error(e)
                    if self._should_retry_with_token_refresh(
                        mapped_error, attempt=1 if token_refreshed else 0
                    ):
                        token_refreshed = True
                        await self.auth.refresh_token()
                        continue
                    if self._should_retry_rate_limited(mapped_error, rate_limit_retries):
                        await asyncio.sleep(self._rate_limit_backoff_seconds(rate_limit_retries))
                        rate_limit_retries += 1
                        continue
                    await self._record_metrics(loop.time() - started_at, success=False)
                    await self._handle_backoff(mapped_error)
                    raise mapped_error
                except KISAPIError as e:
                    if self._should_retry_with_token_refresh(
                        e, attempt=1 if token_refreshed else 0
                    ):
                        token_refreshed = True
                        await self.auth.refresh_token()
                        continue
                    if self._should_retry_rate_limited(e, rate_limit_retries):
                        await asyncio.sleep(self._rate_limit_backoff_seconds(rate_limit_retries))
                        rate_limit_retries += 1
                        continue
                    await self._record_metrics(loop.time() - started_at, success=False)
                    await self._handle_backoff(e)
                    raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        retry_transport_errors: bool = True,
    ) -> dict[str, Any]:
        """
        POST 요청

        Args:
            path: API 경로
            json: JSON 바디
            headers: 추가 헤더
            timeout: 요청 타임아웃 (초), None이면 기본값 사용
            retry_transport_errors: True면 타임아웃/네트워크 오류를 재시도

        Returns:
            dict[str, Any]: API 응답 데이터

        Raises:
            KISAPIError: API 호출 실패
        """
        async with self.rate_limit_semaphore:
            loop = asyncio.get_event_loop()
            started_at = loop.time()
            url = f"{self.base_url}{path}"
            client = await self._get_client()

            token_refreshed = False
            rate_limit_retries = 0

            while True:
                # 헤더(토큰) 확보를 먼저 하고, 실제 HTTP 호출 직전에 acquire.
                # 반대로 하면 콜드 토큰 갱신 시 auth lock에 대기하던 요청들이
                # 이미 rate limit 슬롯을 쥔 채 갱신 직후 일제히 나가 버스트가 됨.
                auth_headers = await self.auth.get_auth_headers(force_refresh=False)
                if headers:
                    auth_headers.update(headers)

                await self.rate_limiter.acquire()
                try:
                    response = await client.post(
                        url,
                        json=json,
                        headers=auth_headers,
                        timeout=timeout,  # None이면 클라이언트 기본값 사용
                    )
                    data = self._handle_response(response)
                    await self._record_metrics(loop.time() - started_at, success=True)
                    await self._reset_backoff()
                    return data
                except httpx.HTTPStatusError as e:
                    mapped_error = self._map_http_error(e)
                    if self._should_retry_with_token_refresh(
                        mapped_error, attempt=1 if token_refreshed else 0
                    ):
                        token_refreshed = True
                        await self.auth.refresh_token()
                        continue
                    if self._should_retry_rate_limited(mapped_error, rate_limit_retries):
                        await asyncio.sleep(self._rate_limit_backoff_seconds(rate_limit_retries))
                        rate_limit_retries += 1
                        continue
                    await self._record_metrics(loop.time() - started_at, success=False)
                    await self._handle_backoff(mapped_error)
                    raise mapped_error
                except KISAPIError as e:
                    if self._should_retry_with_token_refresh(
                        e, attempt=1 if token_refreshed else 0
                    ):
                        token_refreshed = True
                        await self.auth.refresh_token()
                        continue
                    if self._should_retry_rate_limited(e, rate_limit_retries):
                        await asyncio.sleep(self._rate_limit_backoff_seconds(rate_limit_retries))
                        rate_limit_retries += 1
                        continue
                    await self._record_metrics(loop.time() - started_at, success=False)
                    await self._handle_backoff(e)
                    raise
                except (httpx.TimeoutException, httpx.NetworkError) as e:
                    await self._record_metrics(loop.time() - started_at, success=False)
                    if retry_transport_errors:
                        raise
                    raise KISAPIError(
                        message=(
                            "POST request outcome is unknown after transport error; "
                            "not retrying non-idempotent request"
                        ),
                        error_code="POST_OUTCOME_UNKNOWN",
                    ) from e

    # ==================== 응답 처리 ====================

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """
        API 응답 처리

        Args:
            response: HTTP 응답

        Returns:
            dict[str, Any]: 파싱된 응답 데이터

        Raises:
            KISAPIError: API 에러 응답
        """
        response.raise_for_status()
        data = response.json()

        # KIS API 응답 구조: {"rt_cd": "0", "msg_cd": "...", "msg1": "...", "output": {...}}
        rt_cd = data.get("rt_cd")
        msg_cd = data.get("msg_cd")
        msg1 = data.get("msg1", "")

        if rt_cd != "0":
            raise KISAPIError(
                message=f"KIS API Error: {msg1}",
                error_code=msg_cd,
                response_data=data,
            )

        return data

    def _should_retry_with_token_refresh(self, error: KISAPIError, attempt: int) -> bool:
        """토큰 만료(EGW00123/401) 계열 오류는 1회 강제 refresh 후 재시도"""
        if attempt >= 1:
            return False

        error_code = getattr(error, "error_code", None)
        response_data = getattr(error, "response_data", None) or {}
        msg_cd = response_data.get("msg_cd") if isinstance(response_data, dict) else None
        msg1 = response_data.get("msg1", "") if isinstance(response_data, dict) else ""

        return (
            isinstance(error, KISAuthError)
            or error_code in {"401", "EGW00123"}
            or msg_cd == "EGW00123"
            or "기간이 만료된 token" in msg1
        )

    def _should_retry_rate_limited(self, error: KISAPIError, retries_done: int) -> bool:
        """초당 거래건수 초과(EGW00201)는 지수 백오프로 최대 N회 재시도"""
        if retries_done >= settings.kis_api_rate_limit_max_retries:
            return False

        error_code = getattr(error, "error_code", None)
        response_data = getattr(error, "response_data", None) or {}
        msg_cd = response_data.get("msg_cd") if isinstance(response_data, dict) else None
        msg1 = response_data.get("msg1", "") if isinstance(response_data, dict) else ""
        return error_code == "EGW00201" or msg_cd == "EGW00201" or "초당 거래건수를 초과" in msg1

    def _rate_limit_backoff_seconds(self, retries_done: int) -> float:
        """EGW00201 재시도 지수 백오프 대기 시간 (기본 0.5 → 1.0 → 2.0초)"""
        return settings.kis_api_rate_limit_backoff_base_seconds * (2**retries_done)

    def _map_http_error(self, error: httpx.HTTPStatusError) -> KISAPIError:
        """
        HTTP 에러를 KIS 에러로 매핑

        Args:
            error: HTTP 에러

        Returns:
            KISAPIError: 매핑된 KIS 에러
        """
        status_code = error.response.status_code

        if status_code == 401:
            return KISAuthError("Authentication failed. Please check your API keys.")
        elif status_code == 429:
            return KISRateLimitError("Rate limit exceeded. Please try again later.")
        else:
            return KISAPIError(
                message=f"HTTP {status_code}: {error.response.text}",
                error_code=str(status_code),
                response_data=error.response.json() if error.response.text else {},
            )

    async def _handle_backoff(self, error: KISAPIError) -> None:
        """429/5xx 연속 발생 시 백오프 및 쿨다운 적용"""
        if not self._is_backoff_candidate(error):
            await self._reset_backoff()
            return

        delay = await self._register_backoff_delay()
        if delay > 0:
            await asyncio.sleep(delay)

    def _is_backoff_candidate(self, error: KISAPIError) -> bool:
        if isinstance(error, KISRateLimitError):
            return True

        if error.error_code and error.error_code.isdigit():
            return int(error.error_code) >= 500
        return False

    async def _register_backoff_delay(self) -> float:
        """연속 오류 수 기반으로 대기 시간 계산"""
        async with self._backoff_lock:
            backoff_seq = settings.kis_api_backoff_sequence
            self._consecutive_backoff_errors += 1
            if self._consecutive_backoff_errors % settings.kis_api_backoff_trigger_errors != 0:
                return 0.0

            delay = backoff_seq[min(self._backoff_stage, len(backoff_seq) - 1)]

            self._backoff_stage = min(self._backoff_stage + 1, len(backoff_seq) - 1)
            self._backoff_cycles += 1

            if self._backoff_cycles >= settings.kis_api_backoff_cycles_before_cooldown:
                self._consecutive_backoff_errors = 0
                self._backoff_stage = 0
                self._backoff_cycles = 0
                return float(settings.kis_api_cooldown_seconds)

            return float(delay)

    async def _reset_backoff(self) -> None:
        """성공 호출 시 백오프 상태 초기화"""
        async with self._backoff_lock:
            self._consecutive_backoff_errors = 0
            self._backoff_stage = 0
            self._backoff_cycles = 0

    # ==================== Metrics & SLO ====================

    async def _record_metrics(self, duration: float, success: bool) -> None:
        """호출 성능/오류율 기록 및 SLO 경고"""
        now = asyncio.get_event_loop().time()
        async with self._metrics_lock:
            self._events.append((now, duration, success))
            while self._events and now - self._events[0][0] > self._metrics_window_seconds:
                self._events.popleft()

            if len(self._events) < self._slo_min_events:
                return

            durations = [d for _, d, s in self._events if s]
            if durations:
                p95 = self._percentile(durations, 0.95)
                if p95 > self._p95_target_seconds:
                    print(
                        f"⚠️ KIS REST latency p95 {p95:.2f}s > {self._p95_target_seconds}s "
                        f"(last {len(durations)} successes)"
                    )

            total = len(self._events)
            failures = len([1 for _, _, s in self._events if not s])
            error_rate = failures / total if total else 0.0
            if error_rate > self._error_rate_target:
                print(
                    f"⚠️ KIS REST error rate {error_rate:.2%} exceeds "
                    f"{self._error_rate_target:.0%} over last {total} calls"
                )

    def _percentile(self, data: list[float], percentile: float) -> float:
        """단순 퍼센타일 계산"""
        if not data:
            return 0.0
        ordered = sorted(data)
        k = (len(ordered) - 1) * percentile
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return ordered[int(k)]
        d0 = ordered[int(f)] * (c - k)
        d1 = ordered[int(c)] * (k - f)
        return d0 + d1

    # ==================== Hash Key 발급 (주문용) ====================

    async def get_hashkey(self, json_data: dict[str, Any]) -> str:
        """
        주문 API용 Hash Key 발급

        Args:
            json_data: 주문 데이터

        Returns:
            str: Hash Key

        Raises:
            KISAPIError: Hash Key 발급 실패
        """
        path = "/uapi/hashkey"
        response = await self.post(path, json=json_data)
        return response.get("HASH", "")


# ==================== 싱글톤 인스턴스 ====================

_kis_client_instance: KISAPIClient | None = None


def get_kis_client() -> KISAPIClient:
    """
    KISAPIClient 싱글톤 인스턴스 반환

    Returns:
        KISAPIClient: API 클라이언트 인스턴스
    """
    global _kis_client_instance
    if _kis_client_instance is None:
        _kis_client_instance = KISAPIClient()
    return _kis_client_instance
