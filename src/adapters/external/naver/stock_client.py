# -*- coding: utf-8 -*-
"""
Naver Stock API Client

네이버 주식 모바일 API를 통해 종목 정보 조회
"""

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.adapters.database.connection import get_async_session
from src.adapters.database.repositories.personal_flow_snapshot_repository import (
    PersonalFlowSnapshotRepository,
)


@dataclass
class StockFinancialData:
    """종목 재무 데이터"""

    symbol: str
    name: str
    market_cap: int  # 시가총액 (원)
    retention_ratio: float | None  # 유보율 (%)
    quick_ratio: float | None  # 당좌비율 (%)
    debt_ratio: float | None  # 부채비율 (%)
    roe: float | None  # ROE (%)
    per: float | None  # PER
    pbr: float | None  # PBR
    industry_code: str | None = None  # 네이버 업종코드 (industryCode)


@dataclass
class StockPersonalFlowData:
    """개인 수급 데이터 (네이버 dealTrend 기반)"""

    symbol: str
    latest_date: str | None
    latest_individual_net_buy: int | None
    latest_close_price: int | None
    latest_volume: int | None
    days_positive_count: int
    recent_3d_net_buy: int
    recent_5d_net_buy: int
    recent_5d_buy_ratio_to_volume: float | None


class NaverStockClient:
    """
    네이버 주식 API 클라이언트

    모바일 API를 사용하여 종목 정보를 조회합니다.
    """

    PERSONAL_FLOW_CACHE_ROWS = 5
    PERSONAL_FLOW_BACKFILL_SIZE = 600

    BASE_URL = "https://m.stock.naver.com/api/stock"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()
        self._rate_limit = asyncio.Semaphore(5)  # 동시 요청 제한

    async def _get_client(self) -> httpx.AsyncClient:
        """httpx.AsyncClient 인스턴스 반환 (Lazy 초기화)"""
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        timeout=10.0,
                        headers={"User-Agent": "Mozilla/5.0"},
                        limits=httpx.Limits(
                            max_keepalive_connections=10,
                            max_connections=20,
                        ),
                    )
        return self._client

    async def aclose(self) -> None:
        """httpx.AsyncClient 리소스 정리"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def _get(self, url: str) -> dict[str, Any]:
        """GET 요청"""
        async with self._rate_limit:
            client = await self._get_client()
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

    async def get_integration(self, symbol: str) -> dict[str, Any]:
        """
        종목 통합 정보 조회

        Args:
            symbol: 종목코드 (예: 005930)

        Returns:
            통합 정보 딕셔너리
        """
        url = f"{self.BASE_URL}/{symbol}/integration"
        return await self._get(url)

    async def get_finance_annual(self, symbol: str) -> dict[str, Any]:
        """
        종목 연간 재무 정보 조회

        Args:
            symbol: 종목코드 (예: 005930)

        Returns:
            재무 정보 딕셔너리
        """
        url = f"{self.BASE_URL}/{symbol}/finance/annual"
        return await self._get(url)

    async def get_personal_flow_trend_list(
        self,
        symbol: str,
        size: int = PERSONAL_FLOW_BACKFILL_SIZE,
    ) -> list[dict[str, Any]]:
        """
        개인 수급 추이 조회.

        Naver 모바일 웹의 비공식 trend endpoint를 사용한다.
        """
        url = f"{self.BASE_URL}/{symbol}/investor/trend?size={size}"
        data = await self._get(url)

        for key in ("dealTrendInfos", "trendList", "items", "result"):
            rows = data.get(key)
            if isinstance(rows, list):
                return rows

        if isinstance(data, list):
            return data
        return []

    async def get_stock_financial_data(self, symbol: str) -> StockFinancialData | None:
        """
        종목 재무 데이터 조회 (통합)

        Args:
            symbol: 종목코드

        Returns:
            StockFinancialData 또는 None (조회 실패시)
        """
        try:
            # 두 API를 병렬로 호출
            integration_task = asyncio.create_task(self.get_integration(symbol))
            finance_task = asyncio.create_task(self.get_finance_annual(symbol))

            integration_data, finance_data = await asyncio.gather(
                integration_task, finance_task, return_exceptions=True
            )

            # 에러 처리
            if isinstance(integration_data, Exception):
                return None
            if isinstance(finance_data, Exception):
                finance_data = {}

            # 종목명 추출
            name = integration_data.get("stockName", "")

            # 업종코드 추출 (naver_industry_codes 매핑 테이블과 동일한 키)
            raw_industry = integration_data.get("industryCode") or integration_data.get("category", {}).get("industryCode")
            industry_code = str(raw_industry) if raw_industry else None

            # 시가총액 추출 (totalInfos에서 "시총" 찾기)
            market_cap = 0
            total_infos = integration_data.get("totalInfos", [])
            for info in total_infos:
                if info.get("key") == "시총":
                    # "821조 538억" 형태 → 정수 변환
                    market_cap = self._parse_market_cap(info.get("value", "0"))
                    break

            # 재무 지표 추출
            finance_info = finance_data.get("financeInfo", {})
            row_list = finance_info.get("rowList", [])

            retention_ratio = self._extract_latest_value(row_list, "유보율")
            quick_ratio = self._extract_latest_value(row_list, "당좌비율")
            debt_ratio = self._extract_latest_value(row_list, "부채비율")
            roe = self._extract_latest_value(row_list, "ROE")
            per = self._extract_latest_value(row_list, "PER")
            pbr = self._extract_latest_value(row_list, "PBR")

            return StockFinancialData(
                symbol=symbol,
                name=name,
                market_cap=market_cap,
                retention_ratio=retention_ratio,
                quick_ratio=quick_ratio,
                debt_ratio=debt_ratio,
                roe=roe,
                per=per,
                pbr=pbr,
                industry_code=industry_code,
            )

        except Exception:
            return None

    def _parse_market_cap(self, value: str) -> int:
        """
        시가총액 문자열을 정수로 변환

        Args:
            value: "821조 538억" 또는 "4,316억" 형태의 문자열

        Returns:
            시가총액 (원)
        """
        if not value or value == "-":
            return 0

        # 쉼표와 공백 제거
        value = value.replace(",", "").replace(" ", "")

        total = 0

        # "821조538억" 형태 파싱
        if "조" in value:
            parts = value.split("조")
            try:
                total += int(float(parts[0])) * 1_000_000_000_000
            except ValueError:
                pass
            if len(parts) > 1 and parts[1]:
                value = parts[1]  # 남은 부분 처리
            else:
                return total

        # "538억" 형태 파싱
        if "억" in value:
            value = value.replace("억", "")
            try:
                total += int(float(value)) * 100_000_000
            except ValueError:
                pass

        return total

    async def _load_recent_cached_personal_flow(self, symbol: str) -> list[dict[str, Any]]:
        async with get_async_session() as session:
            repo = PersonalFlowSnapshotRepository(session)
            rows = await repo.get_recent_by_symbol(symbol=symbol, limit=5, session=session)
            return [
                {
                    "bizdate": row.biz_date,
                    "individualPureBuyQuant": row.individual_net_buy,
                    "closePrice": row.close_price,
                    "accumulatedTradingVolume": row.trading_volume,
                }
                for row in rows
            ]

    @staticmethod
    def _parse_int(value: Any) -> int | None:
        if value in (None, "", "-"):
            return None
        try:
            return int(str(value).replace(",", "").replace("+", ""))
        except ValueError:
            return None

    async def _fetch_and_cache_personal_flow(
        self,
        symbol: str,
        size: int | None = None,
    ) -> list[dict[str, Any]]:
        try:
            trend_rows = await self.get_personal_flow_trend_list(
                symbol,
                size=size or self.PERSONAL_FLOW_BACKFILL_SIZE,
            )
        except Exception:
            trend_rows = []
        if not trend_rows:
            integration_data = await self.get_integration(symbol)
            trend_rows = integration_data.get("dealTrendInfos", [])
        if not trend_rows:
            return []

        async with get_async_session() as session:
            repo = PersonalFlowSnapshotRepository(session)
            for row in trend_rows:
                biz_date = row.get("bizdate") or row.get("bizDate") or row.get("date")
                if not biz_date:
                    continue
                await repo.upsert_snapshot(
                    symbol=symbol,
                    biz_date=str(biz_date),
                    individual_net_buy=self._parse_int(
                        row.get("individualPureBuyQuant") or row.get("personalPureBuyQuant")
                    ),
                    close_price=self._parse_int(row.get("closePrice") or row.get("close")),
                    trading_volume=self._parse_int(
                        row.get("accumulatedTradingVolume") or row.get("tradingVolume")
                    ),
                    session=session,
                )
        return trend_rows

    async def get_personal_flow_data(self, symbol: str) -> StockPersonalFlowData | None:
        """개인 수급 과열 판단용 최근 수급 데이터 조회 (DB 캐시 우선)"""
        try:
            rows = await self._load_recent_cached_personal_flow(symbol)
            if len(rows) < self.PERSONAL_FLOW_CACHE_ROWS:
                try:
                    await self._fetch_and_cache_personal_flow(symbol)
                except Exception:
                    pass
                rows = await self._load_recent_cached_personal_flow(symbol)
            if not rows:
                return None

            rows = rows[: self.PERSONAL_FLOW_CACHE_ROWS]
            latest = rows[0]
            latest_volume = self._parse_int(latest.get("accumulatedTradingVolume"))
            recent_3d_net_buy = sum(
                self._parse_int(row.get("individualPureBuyQuant")) or 0 for row in rows[:3]
            )
            recent_5d_net_buy = sum(
                self._parse_int(row.get("individualPureBuyQuant")) or 0
                for row in rows[: self.PERSONAL_FLOW_CACHE_ROWS]
            )
            positive_days = sum(
                1
                for row in rows
                if (self._parse_int(row.get("individualPureBuyQuant")) or 0) > 0
            )
            buy_ratio = None
            if latest_volume and latest_volume > 0 and recent_5d_net_buy > 0:
                buy_ratio = recent_5d_net_buy / latest_volume

            return StockPersonalFlowData(
                symbol=symbol,
                latest_date=latest.get("bizdate"),
                latest_individual_net_buy=self._parse_int(latest.get("individualPureBuyQuant")),
                latest_close_price=self._parse_int(latest.get("closePrice")),
                latest_volume=latest_volume,
                days_positive_count=positive_days,
                recent_3d_net_buy=recent_3d_net_buy,
                recent_5d_net_buy=recent_5d_net_buy,
                recent_5d_buy_ratio_to_volume=buy_ratio,
            )
        except Exception:
            return None

    async def refresh_personal_flow_cache(self, symbol: str) -> dict[str, Any]:
        rows = await self._fetch_and_cache_personal_flow(symbol, size=self.PERSONAL_FLOW_CACHE_ROWS)
        return {"symbol": symbol, "rows": len(rows)}

    async def backfill_personal_flow_cache(
        self,
        symbol: str,
        years: int = 2,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        resolved_end = end_date or date.today().strftime("%Y%m%d")
        start = datetime.strptime(resolved_end, "%Y%m%d").date() - timedelta(days=365 * years)
        resolved_start = start.strftime("%Y%m%d")
        rows = await self._fetch_and_cache_personal_flow(
            symbol,
            size=max(self.PERSONAL_FLOW_BACKFILL_SIZE, years * 260),
        )
        in_range_rows = [
            row
            for row in rows
            if resolved_start
            <= str(row.get("bizdate") or row.get("bizDate") or row.get("date") or "")
            <= resolved_end
        ]
        return {
            "symbol": symbol,
            "start_date": resolved_start,
            "end_date": resolved_end,
            "years": years,
            "rows": len(in_range_rows),
        }

    def _extract_latest_value(
        self, row_list: list[dict], title: str
    ) -> float | None:
        """
        재무 지표에서 최신 값 추출

        Args:
            row_list: 재무 지표 리스트
            title: 추출할 항목명 (예: "유보율")

        Returns:
            최신 값 (float) 또는 None
        """
        for row in row_list:
            if row.get("title") == title:
                columns = row.get("columns", {})
                # 가장 최신 연도의 값 찾기 (isConsensus=N인 것 중)
                latest_key = None
                latest_value = None

                for key, col in columns.items():
                    value = col.get("value", "-")
                    if value == "-":
                        continue
                    # 더 최신 연도 선택
                    if latest_key is None or key > latest_key:
                        latest_key = key
                        latest_value = value

                if latest_value:
                    try:
                        return float(latest_value.replace(",", ""))
                    except ValueError:
                        return None
        return None


# 싱글톤 인스턴스
_naver_client_instance: NaverStockClient | None = None


def get_naver_stock_client() -> NaverStockClient:
    """NaverStockClient 싱글톤 인스턴스 반환"""
    global _naver_client_instance
    if _naver_client_instance is None:
        _naver_client_instance = NaverStockClient()
    return _naver_client_instance
