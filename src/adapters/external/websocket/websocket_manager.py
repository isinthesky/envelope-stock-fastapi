# -*- coding: utf-8 -*-
"""
WebSocket Manager - WebSocket 연결 및 구독자 관리

클라이언트 연결 관리, 실시간 데이터 브로드캐스트
"""

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import WebSocket

from src.adapters.external.websocket.kis_websocket import get_kis_websocket


class WebSocketManager:
    """
    WebSocket 연결 관리자

    - 클라이언트 연결 관리
    - KIS WebSocket 연결 관리
    - 실시간 데이터 브로드캐스트
    """

    def __init__(self) -> None:
        self.active_connections: dict[str, WebSocket] = {}  # client_id -> WebSocket
        self.subscriptions: dict[str, set[str]] = {}  # tr_key -> {client_ids}
        self.kis_ws = get_kis_websocket()
        self.kis_listener_task: asyncio.Task | None = None
        self.is_kis_connected = False

    # ==================== 클라이언트 연결 관리 ====================

    async def connect(self, client_id: str, websocket: WebSocket) -> None:
        """
        클라이언트 연결

        Args:
            client_id: 클라이언트 ID
            websocket: WebSocket 연결
        """
        await websocket.accept()
        self.active_connections[client_id] = websocket

        # KIS WebSocket 연결 (첫 클라이언트 연결 시)
        if not self.is_kis_connected:
            await self._connect_kis_websocket()

    async def disconnect(self, client_id: str) -> None:
        """
        클라이언트 연결 해제

        Args:
            client_id: 클라이언트 ID
        """
        if client_id in self.active_connections:
            del self.active_connections[client_id]

        # 구독 제거
        for tr_key, clients in list(self.subscriptions.items()):
            if client_id in clients:
                clients.remove(client_id)
                # 구독자가 없으면 KIS WebSocket 구독 해지
                if not clients:
                    await self._unsubscribe_kis(tr_key)
                    del self.subscriptions[tr_key]

        # 모든 클라이언트 연결 해제 시 KIS WebSocket 종료
        if not self.active_connections and self.is_kis_connected:
            await self._disconnect_kis_websocket()

    # ==================== 구독 관리 ====================

    async def subscribe(self, client_id: str, tr_id: str, tr_key: str) -> None:
        """
        실시간 데이터 구독

        Args:
            client_id: 클라이언트 ID
            tr_id: Transaction ID (예: H0STCNT0)
            tr_key: Transaction Key (종목코드)
        """
        subscription_key = f"{tr_id}:{tr_key}"

        # 구독자 추가
        if subscription_key not in self.subscriptions:
            self.subscriptions[subscription_key] = set()
            # KIS WebSocket 구독 (첫 구독자)
            await self._subscribe_kis(tr_id, tr_key)

        self.subscriptions[subscription_key].add(client_id)

    async def unsubscribe(self, client_id: str, tr_id: str, tr_key: str) -> None:
        """
        실시간 데이터 구독 해지

        Args:
            client_id: 클라이언트 ID
            tr_id: Transaction ID
            tr_key: Transaction Key
        """
        subscription_key = f"{tr_id}:{tr_key}"

        if subscription_key in self.subscriptions:
            self.subscriptions[subscription_key].discard(client_id)

            # 구독자가 없으면 KIS WebSocket 구독 해지
            if not self.subscriptions[subscription_key]:
                await self._unsubscribe_kis(tr_key)
                del self.subscriptions[subscription_key]

    # ==================== KIS WebSocket 관리 ====================

    async def _connect_kis_websocket(self) -> None:
        """KIS WebSocket 연결"""
        try:
            await self.kis_ws.connect()
            self.is_kis_connected = True

            # 실시간 데이터 수신 시작
            self.kis_listener_task = asyncio.create_task(
                self.kis_ws.start_listening(self._on_kis_message)
            )
        except Exception as e:
            print(f"❌ KIS WebSocket connection failed: {e}")
            self.is_kis_connected = False

    async def _disconnect_kis_websocket(self) -> None:
        """KIS WebSocket 연결 해제"""
        self.is_kis_connected = False

        if self.kis_listener_task:
            self.kis_listener_task.cancel()
            try:
                await self.kis_listener_task
            except asyncio.CancelledError:
                pass

        await self.kis_ws.disconnect()

    async def _subscribe_kis(self, tr_id: str, tr_key: str) -> None:
        """
        KIS WebSocket 구독

        Args:
            tr_id: Transaction ID
            tr_key: Transaction Key
        """
        try:
            await self.kis_ws.subscribe(tr_id, tr_key)
        except Exception as e:
            print(f"❌ KIS WebSocket subscription failed: {e}")

    async def _unsubscribe_kis(self, tr_key: str) -> None:
        """
        KIS WebSocket 구독 해지

        Args:
            tr_key: Transaction Key (subscription_key)
        """
        # tr_key 형식: "tr_id:tr_key"
        if ":" in tr_key:
            tr_id, key = tr_key.split(":", 1)
            try:
                await self.kis_ws.unsubscribe(tr_id, key)
            except Exception as e:
                print(f"❌ KIS WebSocket unsubscribe failed: {e}")

    # ==================== 메시지 브로드캐스트 ====================

    async def _on_kis_message(self, tr_id: str, data: dict[str, Any]) -> None:
        """
        KIS WebSocket 메시지 수신 콜백

        Args:
            tr_id: Transaction ID
            data: 실시간 데이터
        """
        # 구독자에게 브로드캐스트
        tr_key = data.get("tr_key", "")
        subscription_key = f"{tr_id}:{tr_key}"

        if subscription_key in self.subscriptions:
            subscribers = self.subscriptions[subscription_key]
            await self._broadcast(subscribers, data)

    async def _broadcast(self, client_ids: set[str], message: dict[str, Any]) -> None:
        """
        클라이언트들에게 메시지 브로드캐스트

        Args:
            client_ids: 클라이언트 ID 목록
            message: 전송할 메시지
        """
        disconnected_clients = []

        for client_id in client_ids:
            if client_id in self.active_connections:
                try:
                    await self.active_connections[client_id].send_json(message)
                except Exception:
                    disconnected_clients.append(client_id)

        # 연결이 끊긴 클라이언트 정리
        for client_id in disconnected_clients:
            await self.disconnect(client_id)

    async def send_personal_message(self, client_id: str, message: dict[str, Any]) -> None:
        """
        특정 클라이언트에게 개인 메시지 전송

        Args:
            client_id: 클라이언트 ID
            message: 전송할 메시지
        """
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_json(message)
            except Exception:
                await self.disconnect(client_id)


# ==================== 싱글톤 인스턴스 ====================

_websocket_manager_instance: WebSocketManager | None = None


def get_websocket_manager() -> WebSocketManager:
    """
    WebSocketManager 싱글톤 인스턴스 반환

    Returns:
        WebSocketManager: WebSocket 관리자 인스턴스
    """
    global _websocket_manager_instance
    if _websocket_manager_instance is None:
        _websocket_manager_instance = WebSocketManager()
    return _websocket_manager_instance
