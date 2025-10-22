# -*- coding: utf-8 -*-
"""
WebSocket Router - 실시간 시세 WebSocket API 엔드포인트
"""

import json
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.adapters.external.websocket.websocket_manager import get_websocket_manager

router = APIRouter()


@router.websocket("/realtime")
async def websocket_realtime_endpoint(websocket: WebSocket) -> None:
    """
    실시간 시세 WebSocket 엔드포인트

    클라이언트 연결 후 메시지 형식:
    - 구독: {"action": "subscribe", "tr_id": "H0STCNT0", "tr_key": "005930"}
    - 구독 해지: {"action": "unsubscribe", "tr_id": "H0STCNT0", "tr_key": "005930"}
    """
    manager = get_websocket_manager()
    client_id = str(uuid.uuid4())

    try:
        # 클라이언트 연결
        await manager.connect(client_id, websocket)
        await manager.send_personal_message(
            client_id,
            {
                "type": "connection",
                "status": "connected",
                "client_id": client_id,
                "message": "WebSocket connection established",
            },
        )

        # 메시지 수신 루프
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            action = message.get("action")
            tr_id = message.get("tr_id")
            tr_key = message.get("tr_key")

            if action == "subscribe":
                # 실시간 데이터 구독
                if tr_id and tr_key:
                    await manager.subscribe(client_id, tr_id, tr_key)
                    await manager.send_personal_message(
                        client_id,
                        {
                            "type": "subscription",
                            "status": "subscribed",
                            "tr_id": tr_id,
                            "tr_key": tr_key,
                            "message": f"Subscribed to {tr_id}:{tr_key}",
                        },
                    )
                else:
                    await manager.send_personal_message(
                        client_id,
                        {
                            "type": "error",
                            "message": "Missing tr_id or tr_key",
                        },
                    )

            elif action == "unsubscribe":
                # 구독 해지
                if tr_id and tr_key:
                    await manager.unsubscribe(client_id, tr_id, tr_key)
                    await manager.send_personal_message(
                        client_id,
                        {
                            "type": "subscription",
                            "status": "unsubscribed",
                            "tr_id": tr_id,
                            "tr_key": tr_key,
                            "message": f"Unsubscribed from {tr_id}:{tr_key}",
                        },
                    )
                else:
                    await manager.send_personal_message(
                        client_id,
                        {
                            "type": "error",
                            "message": "Missing tr_id or tr_key",
                        },
                    )

            else:
                await manager.send_personal_message(
                    client_id,
                    {
                        "type": "error",
                        "message": f"Unknown action: {action}",
                    },
                )

    except WebSocketDisconnect:
        await manager.disconnect(client_id)
    except Exception as e:
        print(f"WebSocket error: {e}")
        await manager.disconnect(client_id)


@router.get("/info")
async def websocket_info() -> dict[str, Any]:
    """
    WebSocket 연결 정보 조회

    Returns:
        dict: 현재 WebSocket 연결 정보
    """
    manager = get_websocket_manager()

    return {
        "status": "running",
        "kis_connected": manager.is_kis_connected,
        "active_connections": len(manager.active_connections),
        "active_subscriptions": len(manager.subscriptions),
        "subscriptions": list(manager.subscriptions.keys()),
        "supported_tr_ids": {
            "H0STCNT0": "국내주식 체결 (실시간 체결가)",
            "H0STASP0": "국내주식 호가 (실시간 호가)",
            "H0STCNI0": "체결 통보 (내 주문 체결 알림)",
        },
    }
