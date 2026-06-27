# -*- coding: utf-8 -*-
"""
KOFIA Client - 금융투자협회 통계 API 클라이언트

FreeSIS 화면에서 사용하는 메타/실데이터 조회 패턴을 그대로 따라
시장 신용공여 잔고 추이를 조회합니다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.adapters.database.connection import get_async_session
from src.adapters.database.repositories.market_credit_snapshot_repository import (
    MarketCreditSnapshotRepository,
)


@dataclass(frozen=True)
class KofiaServiceMeta:
    """FreeSIS 서비스 메타데이터"""

    service_id: str
    obj_name: str
    unit_value: str
    latest_daily_date: str | None


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
    PAGE_URL_TEMPLATE = (
        "https://freesis.kofia.or.kr/stat/FreeSIS.do?parentDivId=MSIS10000000000000&serviceId={service_id}"
    )
    META_URL = "https://freesis.kofia.or.kr/meta/getSrvData.do"
    DATA_URL = "https://freesis.kofia.or.kr/meta/getMetaDataList.do"
    MARKET_CREDIT_SERVICE_ID = "STATSCU0100000070"

    MARKET_LABELS: tuple[str, ...] = ("전체", "유가증권", "코스닥")
    CACHE_MIN_ROWS = 2
    BACKFILL_CHUNK_DAYS = 180
    DEFAULT_UNIT_SCALE = "1"
    DEFAULT_UNIT_FLAG = "1"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()
        self._page_prime_lock = asyncio.Lock()
        self._service_meta_lock = asyncio.Lock()
        self._rate_limit = asyncio.Semaphore(2)
        self._primed_service_ids: set[str] = set()
        self._service_meta_cache: dict[str, KofiaServiceMeta] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        timeout=15.0,
                        headers={"User-Agent": "Mozilla/5.0"},
                        follow_redirects=True,
                    )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._primed_service_ids.clear()
        self._service_meta_cache.clear()

    @staticmethod
    def _build_page_url(service_id: str) -> str:
        return KofiaClient.PAGE_URL_TEMPLATE.format(service_id=service_id)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        referer: str | None = None,
    ) -> dict[str, Any]:
        async with self._rate_limit:
            client = await self._get_client()
            headers = {"Content-Type": "application/json; charset=UTF-8"}
            if referer:
                headers["Referer"] = referer
                headers["Origin"] = "https://freesis.kofia.or.kr"
                headers["X-Requested-With"] = "XMLHttpRequest"

            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            try:
                return response.json()
            except ValueError as exc:
                snippet = response.text[:300].replace("\n", " ")
                raise RuntimeError(f"KOFIA JSON 응답 파싱 실패: {snippet}") from exc

    async def _prime_service_page(self, service_id: str) -> str:
        page_url = self._build_page_url(service_id)
        if service_id in self._primed_service_ids:
            return page_url

        async with self._page_prime_lock:
            if service_id in self._primed_service_ids:
                return page_url

            client = await self._get_client()
            async with self._rate_limit:
                response = await client.get(page_url)
                response.raise_for_status()
            self._primed_service_ids.add(service_id)
            return page_url

    async def _get_service_meta(self, service_id: str) -> KofiaServiceMeta:
        cached = self._service_meta_cache.get(service_id)
        if cached is not None:
            return cached

        async with self._service_meta_lock:
            cached = self._service_meta_cache.get(service_id)
            if cached is not None:
                return cached

            page_url = await self._prime_service_page(service_id)
            payload = {
                "dmSearchData": {
                    "strSvrId": service_id,
                    "app_peron_yn": "Y",
                    "language_gb": "KOR",
                    "strGetCode": "Y",
                }
            }
            data = await self._post_json(self.META_URL, payload, referer=page_url)

            grid_servlet = data.get("dsGridServlet") or []
            grid_sql = data.get("dsGridSQL") or []
            grid_info = data.get("dsGridInfo") or []
            search_cd_list = data.get("dsSearchCdList") or []
            list_app_dates = data.get("dsListAppDt") or []

            obj_name = (
                (grid_servlet[0].get("OBJ_NM") if grid_servlet else None)
                or (grid_sql[0].get("OBJ_NM") if grid_sql else None)
            )
            if not obj_name:
                raise RuntimeError(f"KOFIA OBJ_NM 조회 실패: service_id={service_id}")

            basic_unit = grid_info[0].get("BASIC_UNIT") if grid_info else None
            unit_value = self._resolve_unit_value(basic_unit, search_cd_list)
            latest_daily_date = list_app_dates[0].get("TMPV1") if list_app_dates else None

            meta = KofiaServiceMeta(
                service_id=service_id,
                obj_name=str(obj_name),
                unit_value=unit_value,
                latest_daily_date=str(latest_daily_date) if latest_daily_date else None,
            )
            self._service_meta_cache[service_id] = meta
            return meta

    @classmethod
    def _resolve_unit_value(
        cls,
        basic_unit: str | None,
        search_cd_list: list[dict[str, Any]],
    ) -> str:
        if not basic_unit:
            return cls.DEFAULT_UNIT_SCALE

        group_cd, _, common_cd = basic_unit.partition("^")
        if not group_cd or not common_cd:
            return cls.DEFAULT_UNIT_SCALE

        for row in search_cd_list:
            if row.get("GROUP_CD") == group_cd and row.get("COMMON_CD") == common_cd:
                resolved = row.get("CODE_ENGNM") or row.get("CODE_NM")
                if resolved not in (None, ""):
                    return str(resolved)
        return cls.DEFAULT_UNIT_SCALE

    async def _fetch_service_rows(
        self,
        service_id: str,
        start_date: str,
        end_date: str,
        cycle: str = "D",
    ) -> list[dict[str, Any]]:
        page_url = await self._prime_service_page(service_id)
        meta = await self._get_service_meta(service_id)

        payload = {
            "dmSearch": {
                "OBJ_NM": meta.obj_name,
                "tmpV40": meta.unit_value,
                "tmpV41": self.DEFAULT_UNIT_FLAG,
                "tmpV1": cycle,
                "tmpV45": start_date,
                "tmpV46": end_date,
            }
        }
        data = await self._post_json(self.DATA_URL, payload, referer=page_url)
        rows = data.get("ds1") or []
        return rows if isinstance(rows, list) else []

    @classmethod
    def _build_market_credit_snapshots(
        cls,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        mapped_rows: list[dict[str, Any]] = []
        column_map = {
            "전체": ("TMPV2", "TMPV5"),
            "유가증권": ("TMPV3", "TMPV6"),
            "코스닥": ("TMPV4", "TMPV7"),
        }

        for row in rows:
            biz_date = str(row.get("TMPV1") or "")
            if not biz_date.isdigit():
                continue

            for market_label, (balance_col, short_col) in column_map.items():
                balance_million = cls._to_int(row.get(balance_col))
                short_balance_million = cls._to_int(row.get(short_col))
                if balance_million is None and short_balance_million is None:
                    continue

                mapped_rows.append(
                    {
                        "market_label": market_label,
                        "biz_date": biz_date,
                        "trading_volume": None,
                        "balance_million": balance_million,
                        "short_balance_million": short_balance_million,
                    }
                )

        return mapped_rows

    async def _fetch_and_cache_snapshots(
        self,
        start_date: str,
        end_date: str,
    ) -> dict[str, int]:
        rows = await self._fetch_service_rows(
            service_id=self.MARKET_CREDIT_SERVICE_ID,
            start_date=start_date,
            end_date=end_date,
            cycle="D",
        )
        snapshot_rows = self._build_market_credit_snapshots(rows)

        counts = {label: 0 for label in self.MARKET_LABELS}
        async with get_async_session() as session:
            repo = MarketCreditSnapshotRepository(session)
            await repo.delete_invalid_labels(list(self.MARKET_LABELS), session=session)
            for snapshot in snapshot_rows:
                await repo.upsert_snapshot(
                    market_label=snapshot["market_label"],
                    biz_date=snapshot["biz_date"],
                    trading_volume=snapshot["trading_volume"],
                    balance_million=snapshot["balance_million"],
                    short_balance_million=snapshot["short_balance_million"],
                    session=session,
                )
                counts[snapshot["market_label"]] = counts.get(snapshot["market_label"], 0) + 1

        return {label: count for label, count in counts.items() if count > 0}

    @staticmethod
    def _iter_date_chunks(
        start_date: str,
        end_date: str,
        chunk_days: int,
    ) -> list[tuple[str, str]]:
        start = datetime.strptime(start_date, "%Y%m%d").date()
        end = datetime.strptime(end_date, "%Y%m%d").date()
        chunks: list[tuple[str, str]] = []

        current = start
        while current <= end:
            chunk_end = min(current + timedelta(days=chunk_days - 1), end)
            chunks.append((current.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")))
            current = chunk_end + timedelta(days=1)

        return chunks

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
        should_refresh = len(rows) < self.CACHE_MIN_ROWS or latest_cached_date != end_date

        if should_refresh:
            try:
                await self.refresh_market_credit_cache(start_date, end_date)
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

    async def refresh_market_credit_cache(
        self,
        start_date: str,
        end_date: str,
    ) -> dict[str, int]:
        totals: dict[str, int] = {}
        for chunk_start, chunk_end in self._iter_date_chunks(
            start_date=start_date,
            end_date=end_date,
            chunk_days=self.BACKFILL_CHUNK_DAYS,
        ):
            counts = await self._fetch_and_cache_snapshots(chunk_start, chunk_end)
            for label, count in counts.items():
                totals[label] = totals.get(label, 0) + count
        return totals

    async def backfill_market_credit_cache(
        self,
        years: int = 2,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        resolved_end = end_date or date.today().strftime("%Y%m%d")
        start = datetime.strptime(resolved_end, "%Y%m%d").date() - timedelta(days=365 * years)
        resolved_start = start.strftime("%Y%m%d")
        counts = await self.refresh_market_credit_cache(resolved_start, resolved_end)
        return {
            "start_date": resolved_start,
            "end_date": resolved_end,
            "years": years,
            "rows_by_market": counts,
        }

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
