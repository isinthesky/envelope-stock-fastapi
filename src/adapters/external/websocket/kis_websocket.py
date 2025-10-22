# -*- coding: utf-8 -*-
"""
KIS WebSocket Client - 실시간 시세 WebSocket 연결 관리

한국투자증권 Open API WebSocket 연결 및 실시간 데이터 수신
"""

import asyncio
import json
from base64 import b64decode
from collections.abc import Callable
from typing import Any

import websockets
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from src.adapters.external.kis_api.auth import get_kis_auth
from src.adapters.external.kis_api.exceptions import KISWebSocketError
from src.settings.config import settings


class KISWebSocket:
    """
    KIS WebSocket 클라이언트

    실시간 시세 데이터 구독 및 수신
    """

    def __init__(self) -> None:
        self.auth = get_kis_auth()
        self.ws_url = settings.kis_ws_url
        self.connection: websockets.WebSocketClientProtocol | None = None
        self.subscriptions: dict[str, dict[str, Any]] = {}
        self.decrypt_keys: dict[str, tuple[str, str]] = {}  # tr_id -> (iv, key)
        self.on_message_callback: Callable[[str, dict[str, Any]], None] | None = None
        self.is_running = False

    # ==================== 연결 관리 ====================

    async def connect(self) -> None:
        """WebSocket 연결"""
        try:
            approval_key = await self.auth.get_approval_key()
            self.connection = await websockets.connect(
                self.ws_url,
                ping_interval=settings.ws_ping_interval,
                ping_timeout=settings.ws_ping_timeout,
            )
            self.is_running = True
        except Exception as e:
            raise KISWebSocketError(f"WebSocket connection failed: {e}")

    async def disconnect(self) -> None:
        """WebSocket 연결 종료"""
        self.is_running = False
        if self.connection:
            await self.connection.close()
            self.connection = None

    # ==================== 구독 관리 ====================

    async def subscribe(
        self,
        tr_id: str,
        tr_key: str,
        tr_type: str = "1",
    ) -> None:
        """
        실시간 데이터 구독

        Args:
            tr_id: Transaction ID (예: H0STCNT0 - 국내주식 체결)
            tr_key: Transaction Key (종목코드 등)
            tr_type: Transaction Type ("1": 구독, "2": 구독 해지)

        Raises:
            KISWebSocketError: 구독 실패
        """
        if not self.connection:
            raise KISWebSocketError("WebSocket is not connected")

        approval_key = await self.auth.get_approval_key()

        message = {
            "header": {
                "approval_key": approval_key,
                "custtype": "P",
                "tr_type": tr_type,
                "content-type": "utf-8",
            },
            "body": {"input": {"tr_id": tr_id, "tr_key": tr_key}},
        }

        await self.connection.send(json.dumps(message))
        self.subscriptions[f"{tr_id}:{tr_key}"] = {"tr_id": tr_id, "tr_key": tr_key}

        # Rate Limiting
        await asyncio.sleep(settings.smart_sleep)

    async def unsubscribe(self, tr_id: str, tr_key: str) -> None:
        """
        구독 해지

        Args:
            tr_id: Transaction ID
            tr_key: Transaction Key
        """
        await self.subscribe(tr_id, tr_key, tr_type="2")
        subscription_key = f"{tr_id}:{tr_key}"
        if subscription_key in self.subscriptions:
            del self.subscriptions[subscription_key]

    # ==================== 메시지 수신 ====================

    async def start_listening(
        self, on_message: Callable[[str, dict[str, Any]], None]
    ) -> None:
        """
        메시지 수신 시작

        Args:
            on_message: 메시지 수신 콜백 (tr_id, data)

        Raises:
            KISWebSocketError: 수신 실패
        """
        if not self.connection:
            raise KISWebSocketError("WebSocket is not connected")

        self.on_message_callback = on_message

        try:
            async for message in self.connection:
                await self._handle_message(message)
        except websockets.exceptions.ConnectionClosed:
            self.is_running = False
        except Exception as e:
            raise KISWebSocketError(f"Message listening failed: {e}")

    async def _handle_message(self, raw_message: str) -> None:
        """
        수신 메시지 처리

        Args:
            raw_message: 원본 메시지
        """
        # 실시간 데이터 (0|1로 시작)
        if raw_message[0] in ("0", "1"):
            await self._handle_realtime_data(raw_message)
        # 시스템 메시지 (JSON)
        else:
            await self._handle_system_message(raw_message)

    async def _handle_realtime_data(self, raw_message: str) -> None:
        """
        실시간 데이터 처리

        Format: 0|tr_id|tr_key|encrypted_data
        """
        parts = raw_message.split("|")
        if len(parts) < 4:
            return

        tr_id = parts[1]
        encrypted_data = parts[3]

        # 복호화
        if tr_id in self.decrypt_keys:
            iv, key = self.decrypt_keys[tr_id]
            decrypted_data = self._decrypt_aes(key, iv, encrypted_data)
        else:
            decrypted_data = encrypted_data

        # 파싱 및 콜백 호출
        data = self._parse_realtime_data(tr_id, decrypted_data)
        if self.on_message_callback:
            await asyncio.create_task(self.on_message_callback(tr_id, data))

    async def _handle_system_message(self, raw_message: str) -> None:
        """
        시스템 메시지 처리

        Args:
            raw_message: JSON 형식 시스템 메시지
        """
        try:
            message = json.loads(raw_message)
            header = message.get("header", {})
            body = message.get("body", {})

            tr_id = header.get("tr_id")

            # PINGPONG 처리
            if tr_id == "PINGPONG":
                await self.connection.pong(raw_message)
                return

            # 암호화 키 저장
            if "output" in body:
                output = body["output"]
                iv = output.get("iv")
                key = output.get("key")
                if iv and key:
                    self.decrypt_keys[tr_id] = (iv, key)

        except json.JSONDecodeError:
            pass

    # ==================== 유틸리티 ====================

    def _decrypt_aes(self, key: str, iv: str, cipher_text: str) -> str:
        """
        AES CBC 복호화

        Args:
            key: 암호화 키
            iv: Initialization Vector
            cipher_text: Base64 인코딩된 암호문

        Returns:
            str: 복호화된 평문
        """
        cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, iv.encode("utf-8"))
        decrypted = cipher.decrypt(b64decode(cipher_text))
        return bytes.decode(unpad(decrypted, AES.block_size))

    def _parse_realtime_data(self, tr_id: str, data: str) -> dict[str, Any]:
        """
        실시간 데이터 파싱 (CSV to dict)

        Args:
            tr_id: Transaction ID
            data: CSV 형식 데이터

        Returns:
            dict[str, Any]: 파싱된 데이터
        """
        # TR ID별 파싱 로직
        if tr_id == "H0STCNT0":
            return self._parse_stock_trade(data)
        elif tr_id == "H0STASP0":
            return self._parse_stock_orderbook(data)
        elif tr_id == "H0STCNI0":
            return self._parse_order_execution(data)
        else:
            # 기본: raw data 반환
            return {"tr_id": tr_id, "raw_data": data}

    def _parse_stock_trade(self, data: str) -> dict[str, Any]:
        """
        국내주식 체결 (H0STCNT0) 파싱

        Args:
            data: CSV 형식 체결 데이터

        Returns:
            dict[str, Any]: 파싱된 체결 데이터
        """
        fields = data.split("^")
        if len(fields) < 30:
            return {"tr_id": "H0STCNT0", "raw_data": data}

        return {
            "tr_id": "H0STCNT0",
            "symbol": fields[0],  # 종목코드
            "current_price": int(fields[2]),  # 현재가
            "change": fields[3],  # 전일 대비 부호
            "change_price": int(fields[4]),  # 전일 대비
            "change_rate": float(fields[5]),  # 등락률
            "volume": int(fields[7]),  # 체결 거래량
            "accumulated_volume": int(fields[8]),  # 누적 거래량
            "accumulated_amount": int(fields[9]),  # 누적 거래대금
            "open_price": int(fields[10]),  # 시가
            "high_price": int(fields[11]),  # 고가
            "low_price": int(fields[12]),  # 저가
            "ask_price": int(fields[13]),  # 매도호가1
            "bid_price": int(fields[14]),  # 매수호가1
            "trade_time": fields[1],  # 체결 시간 (HHMMSS)
        }

    def _parse_stock_orderbook(self, data: str) -> dict[str, Any]:
        """
        국내주식 호가 (H0STASP0) 파싱

        Args:
            data: CSV 형식 호가 데이터

        Returns:
            dict[str, Any]: 파싱된 호가 데이터
        """
        fields = data.split("^")
        if len(fields) < 80:
            return {"tr_id": "H0STASP0", "raw_data": data}

        # 호가 10단계
        asks = []
        bids = []
        for i in range(10):
            ask_idx = 3 + i * 4
            bid_idx = 43 + i * 4
            asks.append(
                {
                    "price": int(fields[ask_idx]) if fields[ask_idx] else 0,
                    "volume": int(fields[ask_idx + 1]) if fields[ask_idx + 1] else 0,
                }
            )
            bids.append(
                {
                    "price": int(fields[bid_idx]) if fields[bid_idx] else 0,
                    "volume": int(fields[bid_idx + 1]) if fields[bid_idx + 1] else 0,
                }
            )

        return {
            "tr_id": "H0STASP0",
            "symbol": fields[0],  # 종목코드
            "time": fields[1],  # 호가 시간 (HHMMSS)
            "asks": asks,  # 매도 호가 (낮은 가격부터)
            "bids": bids,  # 매수 호가 (높은 가격부터)
            "total_ask_volume": int(fields[23]) if fields[23] else 0,  # 총 매도 잔량
            "total_bid_volume": int(fields[24]) if fields[24] else 0,  # 총 매수 잔량
        }

    def _parse_order_execution(self, data: str) -> dict[str, Any]:
        """
        체결 통보 (H0STCNI0) 파싱

        Args:
            data: CSV 형식 체결 통보 데이터

        Returns:
            dict[str, Any]: 파싱된 체결 통보 데이터
        """
        fields = data.split("^")
        if len(fields) < 20:
            return {"tr_id": "H0STCNI0", "raw_data": data}

        return {
            "tr_id": "H0STCNI0",
            "account_no": fields[0],  # 계좌번호
            "order_no": fields[1],  # 주문번호
            "symbol": fields[2],  # 종목코드
            "order_type": fields[3],  # 주문구분 (매수/매도)
            "order_status": fields[4],  # 체결구분
            "order_quantity": int(fields[5]) if fields[5] else 0,  # 주문수량
            "order_price": int(fields[6]) if fields[6] else 0,  # 주문가격
            "execution_quantity": int(fields[7]) if fields[7] else 0,  # 체결수량
            "execution_price": int(fields[8]) if fields[8] else 0,  # 체결가격
            "execution_time": fields[9],  # 체결시간
            "remaining_quantity": int(fields[10]) if fields[10] else 0,  # 미체결수량
        }


# ==================== 싱글톤 인스턴스 ====================

_kis_websocket_instance: KISWebSocket | None = None


def get_kis_websocket() -> KISWebSocket:
    """
    KISWebSocket 싱글톤 인스턴스 반환

    Returns:
        KISWebSocket: WebSocket 클라이언트 인스턴스
    """
    global _kis_websocket_instance
    if _kis_websocket_instance is None:
        _kis_websocket_instance = KISWebSocket()
    return _kis_websocket_instance
