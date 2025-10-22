"""
WebSocket Adapter - 실시간 시세 WebSocket 연결 관리
"""

from src.adapters.external.websocket.kis_websocket import (
    KISWebSocket,
    get_kis_websocket,
)

__all__ = [
    "KISWebSocket",
    "get_kis_websocket",
]
