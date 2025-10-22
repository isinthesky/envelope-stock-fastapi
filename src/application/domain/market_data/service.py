# -*- coding: utf-8 -*-
"""
MarketData Service - 시세 데이터 조회 서비스
"""

from datetime import datetime
from decimal import Decimal

from src.adapters.cache.redis_client import RedisClient
from src.adapters.external.kis_api.client import KISAPIClient
from src.application.common.decorators import cache
from src.application.common.exceptions import KISAPIServiceError
from src.application.domain.market_data.dto import (
    ChartResponseDTO,
    OrderbookResponseDTO,
    PriceResponseDTO,
)
from src.settings.config import settings


class MarketDataService:
    """
    시세 데이터 서비스

    KIS API를 통한 시세 데이터 조회 및 캐싱
    """

    def __init__(self, kis_client: KISAPIClient, redis_client: RedisClient) -> None:
        """
        Args:
            kis_client: KIS API 클라이언트
            redis_client: Redis 클라이언트
        """
        self.kis_client = kis_client
        self.redis_client = redis_client

    # ==================== 현재가 조회 ====================

    async def get_current_price(
        self, symbol: str, use_cache: bool = True
    ) -> PriceResponseDTO:
        """
        현재가 조회

        Args:
            symbol: 종목코드
            use_cache: 캐시 사용 여부

        Returns:
            PriceResponseDTO: 현재가 정보

        Raises:
            KISAPIServiceError: API 호출 실패
        """
        # 캐시 조회
        if use_cache:
            cached_data = await self.redis_client.get_market_data(symbol)
            if cached_data:
                return PriceResponseDTO(**cached_data)

        # API 호출
        try:
            # KIS API 국내주식 현재가 조회
            path = "/uapi/domestic-stock/v1/quotations/inquire-price"
            params = {
                "FID_COND_MRKT_DIV_CODE": "J",  # 주식, ETF, ETN
                "FID_INPUT_ISCD": symbol,
            }
            headers = {"tr_id": "FHKST01010100"}

            response = await self.kis_client.get(path, params=params, headers=headers)
            output = response.get("output", {})

            # 응답 파싱
            price_data = PriceResponseDTO(
                symbol=symbol,
                symbol_name=output.get("prdt_name", ""),
                current_price=Decimal(output.get("stck_prpr", "0")),
                open_price=Decimal(output.get("stck_oprc", "0")),
                high_price=Decimal(output.get("stck_hgpr", "0")),
                low_price=Decimal(output.get("stck_lwpr", "0")),
                prev_close_price=Decimal(output.get("stck_prdy_clpr", "0")),
                change_amount=Decimal(output.get("prdy_vrss", "0")),
                change_rate=Decimal(output.get("prdy_vrss_sign", "0")),
                volume=int(output.get("acml_vol", "0")),
                timestamp=datetime.now(),
            )

            # 캐시 저장
            if use_cache:
                await self.redis_client.cache_market_data(
                    symbol, price_data.model_dump()
                )

            return price_data

        except Exception as e:
            raise KISAPIServiceError(f"Failed to get current price for {symbol}: {e}")

    # ==================== 호가 조회 ====================

    async def get_orderbook(
        self, symbol: str, use_cache: bool = True
    ) -> OrderbookResponseDTO:
        """
        호가 조회

        Args:
            symbol: 종목코드
            use_cache: 캐시 사용 여부

        Returns:
            OrderbookResponseDTO: 호가 정보

        Raises:
            KISAPIServiceError: API 호출 실패
        """
        # 캐시 키
        cache_key = f"orderbook:{symbol}"

        # 캐시 조회
        if use_cache:
            cached_data = await self.redis_client.get(cache_key)
            if cached_data:
                return OrderbookResponseDTO(**cached_data)

        # API 호출
        try:
            # KIS API 국내주식 호가 조회
            path = "/uapi/domestic-stock/v1/quotations/inquire-asking-price"
            params = {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
            }
            headers = {"tr_id": "FHKST01010200"}

            response = await self.kis_client.get(path, params=params, headers=headers)
            output = response.get("output1", {})

            # 호가 파싱 (10단계)
            from src.application.domain.market_data.dto import OrderbookItemDTO

            ask_prices = []
            bid_prices = []
            for i in range(1, 11):
                # 매도 호가
                ask_prices.append(
                    OrderbookItemDTO(
                        price=Decimal(output.get(f"askp{i}", "0")),
                        quantity=int(output.get(f"askp_rsqn{i}", "0")),
                    )
                )
                # 매수 호가
                bid_prices.append(
                    OrderbookItemDTO(
                        price=Decimal(output.get(f"bidp{i}", "0")),
                        quantity=int(output.get(f"bidp_rsqn{i}", "0")),
                    )
                )

            orderbook_data = OrderbookResponseDTO(
                symbol=symbol,
                symbol_name=output.get("prdt_name", ""),
                ask_prices=ask_prices,
                bid_prices=bid_prices,
                total_ask_quantity=int(output.get("total_askp_rsqn", "0")),
                total_bid_quantity=int(output.get("total_bidp_rsqn", "0")),
                timestamp=datetime.now(),
            )

            # 캐시 저장
            if use_cache:
                await self.redis_client.set(
                    cache_key,
                    orderbook_data.model_dump(),
                    ttl=settings.cache_ttl_market_data,
                )

            return orderbook_data

        except Exception as e:
            raise KISAPIServiceError(f"Failed to get orderbook for {symbol}: {e}")

    # ==================== 차트 데이터 조회 ====================

    async def get_chart_data(
        self,
        symbol: str,
        interval: str = "1d",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> ChartResponseDTO:
        """
        차트 데이터 조회

        Args:
            symbol: 종목코드
            interval: 시간 간격 (1d, 1h 등)
            start_date: 시작일
            end_date: 종료일

        Returns:
            ChartResponseDTO: 차트 데이터

        Raises:
            KISAPIServiceError: API 호출 실패
        """
        try:
            # KIS API 국내주식 일봉 조회
            path = "/uapi/domestic-stock/v1/quotations/inquire-daily-price"

            # 날짜 포맷팅 (YYYYMMDD)
            end_dt = end_date or datetime.now()
            params = {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
                "FID_PERIOD_DIV_CODE": "D",  # D: 일봉, W: 주봉, M: 월봉
                "FID_ORG_ADJ_PRC": "0",  # 0: 수정주가, 1: 원주가
            }
            headers = {"tr_id": "FHKST01010400"}

            response = await self.kis_client.get(path, params=params, headers=headers)
            output_list = response.get("output", [])

            # 캔들 데이터 파싱
            from src.application.domain.market_data.dto import CandleDTO

            candles = []
            for item in output_list:
                candles.append(
                    CandleDTO(
                        timestamp=datetime.strptime(item.get("stck_bsop_date", ""), "%Y%m%d"),
                        open=Decimal(item.get("stck_oprc", "0")),
                        high=Decimal(item.get("stck_hgpr", "0")),
                        low=Decimal(item.get("stck_lwpr", "0")),
                        close=Decimal(item.get("stck_clpr", "0")),
                        volume=int(item.get("acml_vol", "0")),
                    )
                )

            return ChartResponseDTO(
                symbol=symbol, symbol_name=None, interval=interval, candles=candles
            )

        except Exception as e:
            raise KISAPIServiceError(f"Failed to get chart data for {symbol}: {e}")

    # ==================== 헬스체크 ====================

    async def health_check(self) -> dict[str, str]:
        """
        시세 서비스 헬스체크

        Returns:
            dict[str, str]: 상태 정보
        """
        try:
            # Redis 연결 확인
            redis_ok = await self.redis_client.ping()

            return {
                "status": "healthy" if redis_ok else "degraded",
                "redis": "connected" if redis_ok else "disconnected",
            }
        except Exception:
            return {"status": "unhealthy", "redis": "error"}
