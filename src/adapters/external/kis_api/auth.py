# -*- coding: utf-8 -*-
"""
KIS API Auth Module - 인증 및 토큰 관리

한국투자증권 Open API OAuth2 토큰 발급/갱신 모듈
"""

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import yaml

from src.settings.config import settings


@dataclass
class TokenInfo:
    """토큰 정보"""

    access_token: str
    token_type: str
    expires_at: datetime

    @property
    def is_expired(self) -> bool:
        """토큰 만료 여부 (5분 버퍼)"""
        return datetime.now() >= self.expires_at - timedelta(minutes=5)

    @property
    def is_valid(self) -> bool:
        """토큰 유효 여부"""
        return not self.is_expired

    @property
    def remaining_seconds(self) -> int:
        """토큰 남은 시간 (초)"""
        delta = self.expires_at - datetime.now()
        return max(0, int(delta.total_seconds()))


class KISAuth:
    """
    KIS API 인증 관리 클래스

    OAuth2 토큰 발급, 갱신, 저장, 로드 기능 제공
    커넥션 풀링을 통한 성능 최적화
    """

    def __init__(self) -> None:
        self.token_info: TokenInfo | None = None
        self.token_cache_dir = Path.home() / "KIS" / "config"
        self.token_cache_file = self.token_cache_dir / f"KIS{datetime.now().strftime('%Y%m%d')}"

        # 토큰 캐시 디렉토리 생성
        self.token_cache_dir.mkdir(parents=True, exist_ok=True)

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

    async def refresh_token(self) -> TokenInfo:
        """
        토큰 갱신 (저장된 토큰 확인 후 재발급)

        Returns:
            TokenInfo: 갱신된 토큰 정보
        """
        # 1. 저장된 토큰 확인
        saved_token = await self._load_token_from_file()
        if saved_token and saved_token.is_valid:
            self.token_info = saved_token
            return saved_token

        # 2. 새 토큰 발급
        self.token_info = await self._request_new_token()
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
            expires_at=datetime.strptime(
                data["access_token_token_expired"], "%Y-%m-%d %H:%M:%S"
            ),
        )

    # ==================== 토큰 파일 저장/로드 ====================

    async def _save_token_to_file(self, token_info: TokenInfo) -> None:
        """
        토큰을 파일에 저장 (비동기)

        Args:
            token_info: 저장할 토큰 정보
        """
        data = {
            "token": token_info.access_token,
            "valid-date": token_info.expires_at,
        }

        def _sync_write() -> None:
            with open(self.token_cache_file, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True)

        await asyncio.to_thread(_sync_write)

    async def _load_token_from_file(self) -> TokenInfo | None:
        """
        파일에서 토큰 로드 (비동기)

        Returns:
            TokenInfo | None: 로드된 토큰 정보 또는 None
        """
        file_exists = await asyncio.to_thread(self.token_cache_file.exists)
        if not file_exists:
            return None

        def _sync_read() -> dict | None:
            try:
                with open(self.token_cache_file, encoding="utf-8") as f:
                    return yaml.safe_load(f)
            except Exception:
                return None

        data = await asyncio.to_thread(_sync_read)

        if data is None or "token" not in data or "valid-date" not in data:
            return None

        token_info = TokenInfo(
            access_token=data["token"],
            token_type="Bearer",
            expires_at=data["valid-date"],
        )

        # 만료된 토큰은 None 반환
        if not token_info.is_valid:
            return None

        return token_info

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

    async def get_auth_headers(self) -> dict[str, str]:
        """
        인증된 HTTP 헤더 반환

        Returns:
            dict[str, str]: 인증 헤더
        """
        token = await self.get_access_token()
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
