# -*- coding: utf-8 -*-
"""
KOFIA Client - 금융투자협회 통계 API 클라이언트

현재는 신용공여 잔고 추이 조회에 필요한 최소 기능만 제공합니다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


@dataclass
class MarketCreditTrendData:
    """시장 신용공여 잔고 추이 데이터"""

    market_label: str
    latest_date: str | None
    latest_balance_million: int | None
    prev_balance_million: int | None
    balance_change_million: int | None
    balance_change_ratio: float | None
    recent_5d_high_ratio: float | None
    is_overheated: bool
    reasons: list[str]


class KofiaClient:
    BASE_URL = "https://freesis.kofia.or.kr/meta/getMetaDataList.do"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()
        self._rate_limit = asyncio.Semaphore(2)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        timeout=15.0,
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._rate_limit:
            client = await self._get_client()
            response = await client.post(
                self.BASE_URL,
                json=payload,
                headers={"Content-Type": "application/json; charset=UTF-8"},
            )
            response.raise_for_status()
            return response.json()

    async def get_market_credit_trend(
        self,
        start_date: str,
        end_date: str,
        market_label: str = "전체",
    ) -> MarketCreditTrendData | None:
        payload = {
            "dmSearch": {
                "OBJ_NM": "STATSCU0100000140BO",
                "tmpV1": "D",
                "tmpV40": "1000000",
                "tmpV41": "1",
                "tmpV45": start_date,
                "tmpV46": end_date,
                "tmpV72": "",
            }
        }

        try:
            data = await self._post_json(payload)
        except Exception:
            return None

        rows = data.get("ds1") or []
        filtered_rows = [row for row in rows if row.get("TMPV2") == market_label]
        if len(filtered_rows) < 2:
            return None

        latest = filtered_rows[0]
        prev = filtered_rows[1]
        latest_balance = self._to_int(latest.get("TMPV5"))
        prev_balance = self._to_int(prev.get("TMPV5"))
        latest_volume = self._to_int(latest.get("TMPV3"))

        balance_change = None
        balance_change_ratio = None
        if latest_balance is not None and prev_balance is not None:
            balance_change = latest_balance - prev_balance
            if prev_balance > 0:
                balance_change_ratio = balance_change / prev_balance

        recent_balances = [self._to_int(row.get("TMPV5")) for row in filtered_rows[:5]]
        recent_balances = [value for value in recent_balances if value is not None]
        recent_5d_high_ratio = None
        if latest_balance is not None and recent_balances:
            recent_5d_high = max(recent_balances)
            if recent_5d_high > 0:
                recent_5d_high_ratio = latest_balance / recent_5d_high

        reasons: list[str] = []
        if balance_change_ratio is not None and balance_change_ratio >= 0.01:
            reasons.append(f"시장 신용잔고 일간 증가율 높음 ({balance_change_ratio * 100:.2f}%)")
        if balance_change is not None and balance_change >= 10000:
            reasons.append(f"시장 신용잔고 증가폭 큼 (+{balance_change:,}백만)")
        if recent_5d_high_ratio is not None and recent_5d_high_ratio >= 0.995:
            reasons.append("시장 신용잔고가 최근 5일 고점권")
        if latest_volume is not None and latest_volume >= 70000000:
            reasons.append(f"시장 거래량 과열 ({latest_volume:,})")

        return MarketCreditTrendData(
            market_label=market_label,
            latest_date=latest.get("TMPV1"),
            latest_balance_million=latest_balance,
            prev_balance_million=prev_balance,
            balance_change_million=balance_change,
            balance_change_ratio=balance_change_ratio,
            recent_5d_high_ratio=recent_5d_high_ratio,
            is_overheated=len(reasons) >= 2,
            reasons=reasons,
        )

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value in (None, "", "-"):
            return None
        try:
            return int(str(value).replace(",", ""))
        except ValueError:
            return None


_kofia_client_instance: KofiaClient | None = None


def get_kofia_client() -> KofiaClient:
    global _kofia_client_instance
    if _kofia_client_instance is None:
        _kofia_client_instance = KofiaClient()
    return _kofia_client_instance
