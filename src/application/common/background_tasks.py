# -*- coding: utf-8 -*-
"""
Background Tasks - 백그라운드 작업 관리

애플리케이션 백그라운드에서 실행되는 비동기 작업들
"""

import asyncio
from datetime import datetime

from src.adapters.external.kis_api.auth import format_token_expires_in, get_kis_auth
from src.settings.config import settings


class TokenRefreshTask:
    """
    토큰 자동 갱신 백그라운드 태스크

    KIS API 토큰을 주기적으로 체크하고 만료 1시간 전에 자동 갱신
    """

    def __init__(self) -> None:
        self.kis_auth = get_kis_auth()
        self.is_running = False
        self.task: asyncio.Task | None = None

    async def start(self) -> None:
        """백그라운드 태스크 시작"""
        if self.is_running:
            print("⚠️  Token refresh task is already running")
            return

        self.is_running = True
        self.task = asyncio.create_task(self._run())
        print("✅ Token refresh background task started")

    async def stop(self) -> None:
        """백그라운드 태스크 중지"""
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        print("✅ Token refresh background task stopped")

    async def _run(self) -> None:
        """
        메인 루프: 주기적으로 토큰 체크 및 갱신

        - 1시간마다 토큰 상태 확인
        - 만료 1시간 전이면 자동 갱신
        """
        check_interval = 3600  # 1시간마다 체크

        while self.is_running:
            try:
                token_info = self.kis_auth.token_info

                if token_info:
                    remaining = token_info.remaining_seconds
                    hours_remaining = remaining / 3600
                    should_refresh = token_info.is_expired or hours_remaining < 1.0

                    # 만료 1시간 전이면 갱신
                    if should_refresh:
                        minutes_remaining = max(int(hours_remaining * 60), 0)
                        print(
                            f"🔄 Token will expire in {minutes_remaining} minutes. Refreshing..."
                        )
                        await self.kis_auth.refresh_token()
                        refreshed_expires_in = format_token_expires_in(self.kis_auth.token_info)
                        print(
                            f"✅ Token refreshed successfully (expires in {refreshed_expires_in})"
                        )
                    else:
                        print(
                            f"✓ Token is valid (expires in {int(hours_remaining)} hours)"
                        )
                else:
                    # 토큰이 없으면 발급
                    print("⚠️  No token found. Requesting new token...")
                    await self.kis_auth.get_access_token(force_refresh=True)
                    issued_expires_in = format_token_expires_in(self.kis_auth.token_info)
                    print(
                        f"✅ Token issued successfully (expires in {issued_expires_in})"
                    )

            except Exception as e:
                print(f"❌ Token refresh error: {e}")

            # 다음 체크까지 대기
            await asyncio.sleep(check_interval)


# ==================== 싱글톤 인스턴스 ====================

_token_refresh_task: TokenRefreshTask | None = None


def get_token_refresh_task() -> TokenRefreshTask:
    """
    TokenRefreshTask 싱글톤 인스턴스 반환

    Returns:
        TokenRefreshTask: 토큰 갱신 태스크 인스턴스
    """
    global _token_refresh_task
    if _token_refresh_task is None:
        _token_refresh_task = TokenRefreshTask()
    return _token_refresh_task
