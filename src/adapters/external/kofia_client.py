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

from src.adapters.database.connection import get_async_session
from src.adapters.database.repositories.market_credit_snapshot_repository import (
    MarketCreditSnapshotRepository,
)


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

    MARKET_LABELS: tuple[str, ...] = ("전체", "유가증권", "코스닥")

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

    async def _fetch_and_cache_snapshots(
        self,
        start_date: str,
        end_date: str,
    ) -> dict[str, list[dict[str, Any]]]:
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

        data = await self._post_json(payload)
        rows = data.get("ds1") or []
        grouped: dict[str, list[dict[str, Any]]] = {}
        valid_labels = set(self.MARKET_LABELS)
        for row in rows:
            label = row.get("TMPV2")
            biz_date = str(row.get("TMPV1") or "")
            if not label or label not in valid_labels:
                continue
            if not biz_date.isdigit():
                continue
            grouped.setdefault(label, []).append(row)

        async with get_async_session() as session:
            repo = MarketCreditSnapshotRepository(session)
            for label, label_rows in grouped.items():
                for row in label_rows:
                    await repo.upsert_snapshot(
                        market_label=label,
                        biz_date=str(row.get("TMPV1")),
                        trading_volume=self._to_int(row.get("TMPV3")),
                        balance_million=self._to_int(row.get("TMPV5")),
                        short_balance_million=self._to_int(row.get("TMPV6")),
                        session=session,
                    )
        return grouped

    async def _load_recent_rows(self, market_label: str) -> list[dict[str, Any]]:
        async with get_async_session() as session:
            repo = MarketCreditSnapshotRepository(session)
            snapshots = await repo.get_recent_by_market(market_label=market_label, limit=5, session=session)
            return [
                {
                    "TMPV1": snapshot.biz_date,
                    "TMPV2": snapshot.market_label,
                    "TMPV3": snapshot.trading_volume,
                    "TMPV5": snapshot.balance_million,
                    "TMPV6": snapshot.short_balance_million,
                }
                for snapshot in snapshots
            ]

    async def get_market_credit_trend(
        self,
        start_date: str,
        end_date: str,
        market_label: str = "전체",
    ) -> MarketCreditTrendData | None:
        rows = await self._load_recent_rows(market_label)
        latest_cached_date = rows[0].get("TMPV1") if rows else None
        should_refresh = len(rows) < 2 or latest_cached_date != end_date

        if should_refresh:
            try:
                await self._fetch_and_cache_snapshots(start_date, end_date)
            except Exception:
                pass
            rows = await self._load_recent_rows(market_label)
            if len(rows) < 2 and market_label != "전체":
                rows = await self._load_recent_rows("전체")
                market_label = "전체"
            if len(rows) < 2:
                return None
        filtered_rows = [row for row in rows if row.get("TMPV2") == market_label]
        resolved_market_label = market_label
        if len(filtered_rows) < 2 and market_label != "전체":
            filtered_rows = [row for row in rows if row.get("TMPV2") == "전체"]
            resolved_market_label = "전체"
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
            market_label=resolved_market_label,
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
