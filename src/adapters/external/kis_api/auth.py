# -*- coding: utf-8 -*-
"""
KIS API Auth Module - 인증 및 토큰 관리

한국투자증권 Open API OAuth2 토큰 발급/갱신 모듈
"""

import asyncio
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import httpx
import yaml

from src.settings.config import settings

logger = logging.getLogger(__name__)

# KIS가 내려주는 만료 시각(`access_token_token_expired`)은 KST 벽시계 시각이다. 컨테이너 TZ(UTC)와 무관하게
# 비교되도록 모든 만료 시각을 KST aware datetime으로 다룬다. 한국은 DST가 없어 고정 오프셋으로 충분하다.
KST = timezone(timedelta(hours=9), "KST")

# 토큰 캐시 파일명: KIS{발급일 KST YYYYMMDD}. 디렉터리 안의 이 패턴 파일만 토큰 캐시로 취급한다.
TOKEN_CACHE_FILE_PATTERN = re.compile(r"^KIS\d{8}$")
EXPIRY_BUFFER = timedelta(minutes=5)

TokenSource = Literal["memory", "cache", "issued"]


def _as_kst(value: datetime) -> datetime:
    """naive(레거시 파일/KIS 응답, KST 벽시계)면 KST로 해석하고, aware면 KST로 변환한다."""
    if value.tzinfo is None:
        return value.replace(tzinfo=KST)
    return value.astimezone(KST)


def _now_kst() -> datetime:
    return datetime.now(KST)


@dataclass
class TokenInfo:
    """토큰 정보 (expires_at은 항상 KST aware로 정규화된다)"""

    access_token: str
    token_type: str
    expires_at: datetime

    def __post_init__(self) -> None:
        self.expires_at = _as_kst(self.expires_at)

    @property
    def is_expired(self) -> bool:
        """토큰 만료 여부 (5분 버퍼)"""
        return _now_kst() >= self.expires_at - EXPIRY_BUFFER

    @property
    def is_valid(self) -> bool:
        """토큰 유효 여부"""
        return not self.is_expired

    @property
    def remaining_seconds(self) -> int:
        """토큰 남은 시간 (초)"""
        delta = self.expires_at - _now_kst()
        return max(0, int(delta.total_seconds()))

    def has_at_least(self, seconds: int) -> bool:
        """만료 버퍼(5분)를 넘어 최소 seconds 이상 남았는지"""
        return self.is_valid and self.remaining_seconds >= seconds


def format_token_expires_in(token_info: TokenInfo | None) -> str:
    """토큰 만료까지 남은 시간을 로그 출력용 문자열로 포맷."""
    if token_info is None:
        return "unknown"

    remaining_seconds = getattr(token_info, "remaining_seconds", None)
    if remaining_seconds is None:
        return "unknown"

    try:
        remaining = int(remaining_seconds)
    except (TypeError, ValueError):
        return "unknown"

    return f"{max(0, remaining)}s"


class KISAuth:
    """
    KIS API 인증 관리 클래스

    OAuth2 토큰 발급, 갱신, 저장, 로드 기능 제공
    커넥션 풀링을 통한 성능 최적화
    """

    def __init__(self) -> None:
        self.token_info: TokenInfo | None = None
        # 마지막으로 토큰을 확보한 경로 (운영 로그/검증용: cache=파일 재사용, issued=KIS 신규 발급)
        self.last_token_source: TokenSource | None = None
        self.token_cache_dir = Path.home() / "KIS" / "config"

        # 토큰 캐시 디렉토리 생성
        self.token_cache_dir.mkdir(parents=True, exist_ok=True)

        # 커넥션 풀링을 위한 공유 httpx.AsyncClient
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

        # 토큰 재발급 동시성 제어(동일 프로세스 내)
        self._token_refresh_lock = asyncio.Lock()

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
                            max_keepalive_connections=5,
                            max_connections=10,
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

    # ==================== 토큰 발급 ====================

    async def get_access_token(self, force_refresh: bool = False) -> str:
        """
        액세스 토큰 반환 (자동 갱신)

        Args:
            force_refresh: 강제 재발급 여부

        Returns:
            str: 액세스 토큰
        """
        if force_refresh or self.token_info is None or not self.token_info.is_valid:
            await self.refresh_token()

        if self.token_info is None:
            raise RuntimeError("Failed to obtain access token")

        return self.token_info.access_token

    async def refresh_token(
        self,
        rejected_token: str | None = None,
        min_valid_seconds: int = 0,
    ) -> TokenInfo:
        """
        토큰 확보: 메모리 → 캐시 파일 → KIS 신규 발급 순으로 재사용한다(1일 1회 발급 원칙).

        동시 요청(예: universe refresh에서 다수 코루틴)이 몰릴 때 여러 번 발급되지 않도록
        단일 프로세스 내에서 lock으로 보호하고, lock 안에서 재확인한다.

        Args:
            rejected_token: KIS가 방금 거부한 토큰(EGW00123 등). 메모리/파일에 같은 토큰이 있어도
                재사용하지 않는다 — 거부된 토큰을 다시 집어 재시도가 계속 실패하는 것을 막는다.
            min_valid_seconds: 재사용 후보가 최소 이만큼 남아 있어야 한다(선제 갱신용).

        Returns:
            TokenInfo: 확보한 토큰 정보
        """
        async with self._token_refresh_lock:

            def _reusable(candidate: TokenInfo | None) -> bool:
                return (
                    candidate is not None
                    and candidate.access_token != rejected_token
                    and candidate.has_at_least(min_valid_seconds)
                )

            # 1. 다른 코루틴이 lock 대기 중에 이미 갱신했을 수 있다.
            if _reusable(self.token_info):
                assert self.token_info is not None
                self.last_token_source = "memory"
                return self.token_info

            # 2. 캐시 디렉터리에서 가장 늦게 만료되는 유효 토큰 (파일명 날짜와 무관)
            saved_token = await self._load_token_from_file(exclude_token=rejected_token)
            if _reusable(saved_token):
                assert saved_token is not None
                self.token_info = saved_token
                self.last_token_source = "cache"
                return saved_token

            # 3. 새 토큰 발급
            if rejected_token is not None:
                logger.warning("[KISAuth] cached token rejected by KIS; issuing a new token")
            self.token_info = await self._request_new_token()
            self.last_token_source = "issued"
            await self._save_token_to_file(self.token_info)
            return self.token_info

    async def _request_new_token(self) -> TokenInfo:
        """
        새 토큰 발급 API 호출

        Returns:
            TokenInfo: 발급된 토큰 정보

        Raises:
            httpx.HTTPStatusError: API 호출 실패
        """
        url = f"{settings.kis_base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": settings.current_kis_app_key,
            "appsecret": settings.current_kis_app_secret,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        client = await self._get_client()
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()

        data = response.json()
        return TokenInfo(
            access_token=data["access_token"],
            token_type=data["token_type"],
            # KST 벽시계 문자열 → TokenInfo가 KST aware로 정규화
            expires_at=datetime.strptime(data["access_token_token_expired"], "%Y-%m-%d %H:%M:%S"),
        )

    # ==================== 토큰 파일 저장/로드 ====================

    def _cache_file_for(self, issued_at: datetime) -> Path:
        return self.token_cache_dir / f"KIS{issued_at.astimezone(KST).strftime('%Y%m%d')}"

    async def _save_token_to_file(self, token_info: TokenInfo) -> None:
        """
        토큰을 발급일(KST) 기준 파일 `KIS{YYYYMMDD}`에 원자적으로 저장한다.

        임시 파일에 0600으로 쓴 뒤 os.replace로 교체하므로, 동시에 읽는 쪽이
        반쯤 쓰인 파일을 보거나 권한이 잠깐 열려 있는 순간이 없다.
        """
        data = {
            "token": token_info.access_token,
            # ISO 8601 + 오프셋으로 저장해 TZ 해석이 모호하지 않게 한다.
            "valid-date": token_info.expires_at.isoformat(),
        }
        target = self._cache_file_for(_now_kst())

        def _sync_write() -> None:
            fd, tmp_path = tempfile.mkstemp(dir=self.token_cache_dir, prefix=".kis-token-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    yaml.safe_dump(data, f, allow_unicode=True)
                os.chmod(tmp_path, 0o600)
                os.replace(tmp_path, target)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except FileNotFoundError:
                    pass
                raise

        await asyncio.to_thread(_sync_write)

    @staticmethod
    def _parse_cache_file(path: Path) -> TokenInfo | None:
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            return None
        if not isinstance(data, dict) or "token" not in data or "valid-date" not in data:
            return None

        expires_at = data["valid-date"]
        if isinstance(expires_at, str):
            try:
                expires_at = datetime.fromisoformat(expires_at)
            except ValueError:
                return None
        if not isinstance(expires_at, datetime):
            return None

        # 레거시 파일은 naive KST 벽시계 시각이다 → TokenInfo가 KST로 해석한다.
        return TokenInfo(
            access_token=str(data["token"]), token_type="Bearer", expires_at=expires_at
        )

    async def _load_token_from_file(self, exclude_token: str | None = None) -> TokenInfo | None:
        """
        캐시 디렉터리의 모든 `KIS{YYYYMMDD}` 파일 중 아직 유효하고 가장 늦게 만료되는 토큰을 반환한다.

        파일명(날짜)은 신뢰하지 않는다 — 장기 실행 프로세스가 갱신한 토큰이 이전 날짜 파일에 남아 있을 수 있다.

        Args:
            exclude_token: 후보에서 제외할 토큰(KIS가 거부한 토큰)
        """

        def _sync_scan() -> TokenInfo | None:
            best: TokenInfo | None = None
            try:
                paths = [
                    p
                    for p in self.token_cache_dir.iterdir()
                    if p.is_file() and TOKEN_CACHE_FILE_PATTERN.match(p.name)
                ]
            except FileNotFoundError:
                return None
            for path in paths:
                token = self._parse_cache_file(path)
                if token is None or not token.is_valid or token.access_token == exclude_token:
                    continue
                if best is None or token.expires_at > best.expires_at:
                    best = token
            return best

        return await asyncio.to_thread(_sync_scan)

    # ==================== WebSocket 인증 ====================

    async def get_approval_key(self) -> str:
        """
        WebSocket 연결용 approval_key 발급

        Returns:
            str: WebSocket approval_key

        Raises:
            httpx.HTTPStatusError: API 호출 실패
        """
        url = f"{settings.kis_base_url}/oauth2/Approval"
        payload = {
            "grant_type": "client_credentials",
            "appkey": settings.current_kis_app_key,
            "secretkey": settings.current_kis_app_secret,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        client = await self._get_client()
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()

        data = response.json()
        return data["approval_key"]

    # ==================== 헤더 생성 ====================

    async def get_auth_headers(self, force_refresh: bool = False) -> dict[str, str]:
        """
        인증된 HTTP 헤더 반환

        Args:
            force_refresh: True면 토큰을 강제 재발급 후 헤더 생성

        Returns:
            dict[str, str]: 인증 헤더
        """
        token = await self.get_access_token(force_refresh=force_refresh)
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": settings.current_kis_app_key,
            "appsecret": settings.current_kis_app_secret,
        }


# ==================== 싱글톤 인스턴스 ====================

_kis_auth_instance: KISAuth | None = None


def get_kis_auth() -> KISAuth:
    """
    KISAuth 싱글톤 인스턴스 반환

    Returns:
        KISAuth: 인증 관리 인스턴스
    """
    global _kis_auth_instance
    if _kis_auth_instance is None:
        _kis_auth_instance = KISAuth()
    return _kis_auth_instance
