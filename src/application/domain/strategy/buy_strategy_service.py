# -*- coding: utf-8 -*-
"""
Buy Strategy Service - 매수 전략 서비스

골든크로스 기반 매수 종목 스캔 및 분석
"""

import asyncio
import logging
from datetime import datetime
from decimal import Decimal

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.stock_universe import MarketType
from src.adapters.database.repositories.stock_universe_repository import (
    StockUniverseRepository,
)
from src.application.common.exceptions import StrategyError
from src.application.common.indicators import TechnicalIndicators
from src.application.domain.strategy.dto import (
    GoldenCrossScanItemDTO,
    GoldenCrossScanListDTO,
)
from src.application.domain.strategy.ohlcv_data_loader import OHLCVDataLoader


logger = logging.getLogger(__name__)


class BuyStrategyService:
    """
    매수 전략 서비스

    골든크로스 기반 매수 후보 종목을 스캔하고 분석합니다.
    """

    def __init__(self, session: AsyncSession | None = None) -> None:
        """
        Args:
            session: Database Session
        """
        self.session = session
        self._data_loader: OHLCVDataLoader | None = None

    def _get_data_loader(self) -> OHLCVDataLoader:
        """OHLCVDataLoader 인스턴스 반환"""
        if self._data_loader is None:
            self._data_loader = OHLCVDataLoader(self.session)
        return self._data_loader

    async def scan_golden_cross_candidates(
        self,
        market: str | None = None,
        stoch_threshold: float = 30.0,
        gc_only: bool = True,
        include_etf: bool = True,
    ) -> GoldenCrossScanListDTO:
        """
        골든크로스 종목 스캔

        기본 스크리닝 통과 종목에 대해 기술적 지표를 계산하여
        골든크로스 전략 조건에 부합하는 종목을 필터링합니다.

        - 2번의 API 호출로 약 160~170개 캔들 수집
        - DB 캐싱을 통해 반복 호출 최소화
        - MA40/MA160 지표 사용

        Args:
            market: 시장 필터 (KOSPI/KOSDAQ/ETF)
            stoch_threshold: Stochastic 과매도 임계값 (기본 30)
            gc_only: 골든크로스 활성 종목만 반환 (기본 True)
            include_etf: ETF 종목도 함께 스캔 (기본 True)

        Returns:
            GoldenCrossScanListDTO: 스캔 결과
        """
        if not self.session:
            raise StrategyError("Database session not provided")

        scan_time = datetime.now()
        errors: list[str] = []
        results: list[GoldenCrossScanItemDTO] = []

        # 1. 유니버스에서 스크리닝 통과 종목 조회 (ETF 포함 옵션)
        universe_repo = StockUniverseRepository(self.session)
        market_type = MarketType(market) if market else None
        stocks = await universe_repo.get_eligible_stocks(
            market=market_type,
            include_etf=include_etf,
        )

        if not stocks:
            return GoldenCrossScanListDTO(
                stocks=[],
                total_scanned=0,
                gc_active_count=0,
                pullback_waiting_count=0,
                ready_to_buy_count=0,
                scan_time=scan_time,
                errors=["No eligible stocks found in universe"],
            )

        logger.info(f"[GC Scan] Scanning {len(stocks)} eligible stocks with MA40/MA160")

        # 2. 종목별 기술적 지표 계산
        data_loader = self._get_data_loader()

        for stock in stocks:
            try:
                # OHLCV 데이터 로딩
                df = await data_loader.load_ohlcv_dataframe(
                    symbol=stock.symbol,
                    days=240,
                    interval="1d",
                    min_candles=160,
                )

                # 지표 계산 (MA40/MA160)
                df = TechnicalIndicators.prepare_golden_cross_indicators(
                    df,
                    short_ma_period=40,
                    long_ma_period=160,
                    stoch_k_period=14,
                    stoch_d_period=3,
                )

                # 최신 행 추출
                latest = df.iloc[-1]
                ma_short = float(latest["ma_short"]) if pd.notna(latest["ma_short"]) else 0
                ma_long = float(latest["ma_long"]) if pd.notna(latest["ma_long"]) else 0
                stoch_k = float(latest["stoch_k"]) if pd.notna(latest["stoch_k"]) else 50
                stoch_d = float(latest["stoch_d"]) if pd.notna(latest["stoch_d"]) else 50
                close = float(latest["close"])

                # 골든크로스 상태 판정
                is_gc_active = ma_short > ma_long

                # gc_only 필터
                if gc_only and not is_gc_active:
                    continue

                # 상태 결정
                gc_state = self._determine_gc_state(
                    is_gc_active=is_gc_active,
                    stoch_k=stoch_k,
                    stoch_threshold=stoch_threshold,
                )

                # MA 갭 비율 계산
                ma_gap_ratio = ((ma_short - ma_long) / ma_long) if ma_long > 0 else 0

                # 결과 추가
                results.append(
                    GoldenCrossScanItemDTO(
                        symbol=stock.symbol,
                        name=stock.name,
                        market=stock.market,
                        current_price=Decimal(str(close)),
                        ma_short=Decimal(str(round(ma_short, 2))),
                        ma_long=Decimal(str(round(ma_long, 2))),
                        ma_gap_ratio=round(ma_gap_ratio * 100, 2),  # 백분율
                        stoch_k=round(stoch_k, 2),
                        stoch_d=round(stoch_d, 2),
                        is_gc_active=is_gc_active,
                        gc_state=gc_state,
                        market_cap=stock.market_cap,
                        screening_score=stock.screening_score,
                    )
                )

                # Rate limit 대응
                await asyncio.sleep(0.05)

            except ValueError as e:
                # 데이터 부족 등의 예상된 오류
                logger.debug(f"[GC Scan] {stock.symbol}: {e}")
            except Exception as e:
                error_msg = f"{stock.symbol}: {str(e)}"
                logger.warning(f"[GC Scan] Error processing {error_msg}")
                errors.append(error_msg)

        # 3. 결과 정렬 (READY_TO_BUY > WAITING_FOR_PULLBACK > 기타)
        state_order = {"READY_TO_BUY": 0, "WAITING_FOR_PULLBACK": 1, "GC_ACTIVE": 2, "NOT_GC": 3}
        results.sort(key=lambda x: (state_order.get(x.gc_state, 99), -float(x.screening_score or 0)))

        # 4. 통계 계산
        gc_active_count = sum(1 for r in results if r.is_gc_active)
        pullback_waiting_count = sum(1 for r in results if r.gc_state == "WAITING_FOR_PULLBACK")
        ready_to_buy_count = sum(1 for r in results if r.gc_state == "READY_TO_BUY")

        logger.info(
            f"[GC Scan] Complete: {len(results)} results, "
            f"GC Active: {gc_active_count}, Pullback: {pullback_waiting_count}, "
            f"Ready: {ready_to_buy_count}, Errors: {len(errors)}"
        )

        return GoldenCrossScanListDTO(
            stocks=results,
            total_scanned=len(stocks),
            gc_active_count=gc_active_count,
            pullback_waiting_count=pullback_waiting_count,
            ready_to_buy_count=ready_to_buy_count,
            scan_time=scan_time,
            errors=errors,
        )

    async def scan_symbols(
        self,
        symbols: list[dict],
        stoch_threshold: float = 30.0,
        gc_only: bool = True,
    ) -> GoldenCrossScanListDTO:
        """
        특정 종목 목록에 대해 골든크로스 스캔

        stock_universe에 없는 종목(ETF 등)도 직접 스캔 가능합니다.

        Args:
            symbols: 스캔할 종목 목록 [{"symbol": "...", "name": "...", "market": "..."}]
            stoch_threshold: Stochastic 과매도 임계값 (기본 30)
            gc_only: 골든크로스 활성 종목만 반환 (기본 True)

        Returns:
            GoldenCrossScanListDTO: 스캔 결과
        """
        scan_time = datetime.now()
        errors: list[str] = []
        results: list[GoldenCrossScanItemDTO] = []

        if not symbols:
            return GoldenCrossScanListDTO(
                stocks=[],
                total_scanned=0,
                gc_active_count=0,
                pullback_waiting_count=0,
                ready_to_buy_count=0,
                scan_time=scan_time,
                errors=["No symbols provided"],
            )

        logger.info(f"[GC Scan] Scanning {len(symbols)} symbols with MA40/MA160")

        data_loader = self._get_data_loader()

        # 종목명 조회를 위한 서비스 준비
        from src.adapters.cache.redis_client import get_redis_client
        from src.adapters.external.kis_api.client import get_kis_client
        from src.application.domain.market_data.service import MarketDataService

        try:
            kis_client = get_kis_client()
            redis_client = await get_redis_client()
            market_data_service = MarketDataService(kis_client, redis_client)
        except Exception:
            market_data_service = None

        for item in symbols:
            symbol = item.get("symbol")
            name = item.get("name")
            market = item.get("market") or "ETF"

            if not symbol:
                continue

            # 종목명이 없으면 API로 조회
            if not name and market_data_service:
                try:
                    name = await market_data_service.get_stock_name(symbol)
                except Exception:
                    pass
            name = name or symbol

            try:
                # OHLCV 데이터 로딩
                df = await data_loader.load_ohlcv_dataframe(
                    symbol=symbol,
                    days=240,
                    interval="1d",
                    min_candles=160,
                )

                # 지표 계산 (MA40/MA160)
                df = TechnicalIndicators.prepare_golden_cross_indicators(
                    df,
                    short_ma_period=40,
                    long_ma_period=160,
                    stoch_k_period=14,
                    stoch_d_period=3,
                )

                # 최신 행 추출
                latest = df.iloc[-1]
                ma_short = float(latest["ma_short"]) if pd.notna(latest["ma_short"]) else 0
                ma_long = float(latest["ma_long"]) if pd.notna(latest["ma_long"]) else 0
                stoch_k = float(latest["stoch_k"]) if pd.notna(latest["stoch_k"]) else 50
                stoch_d = float(latest["stoch_d"]) if pd.notna(latest["stoch_d"]) else 50
                close = float(latest["close"])

                # 골든크로스 상태 판정
                is_gc_active = ma_short > ma_long

                # gc_only 필터
                if gc_only and not is_gc_active:
                    continue

                # 상태 결정
                gc_state = self._determine_gc_state(
                    is_gc_active=is_gc_active,
                    stoch_k=stoch_k,
                    stoch_threshold=stoch_threshold,
                )

                # MA 갭 비율 계산
                ma_gap_ratio = ((ma_short - ma_long) / ma_long) if ma_long > 0 else 0

                # 결과 추가
                results.append(
                    GoldenCrossScanItemDTO(
                        symbol=symbol,
                        name=name,
                        market=market,
                        current_price=Decimal(str(close)),
                        ma_short=Decimal(str(round(ma_short, 2))),
                        ma_long=Decimal(str(round(ma_long, 2))),
                        ma_gap_ratio=round(ma_gap_ratio * 100, 2),
                        stoch_k=round(stoch_k, 2),
                        stoch_d=round(stoch_d, 2),
                        is_gc_active=is_gc_active,
                        gc_state=gc_state,
                        market_cap=None,
                        screening_score=None,
                    )
                )

                # Rate limit 대응
                await asyncio.sleep(0.05)

            except ValueError as e:
                logger.debug(f"[GC Scan] {symbol}: {e}")
            except Exception as e:
                error_msg = f"{symbol}: {str(e)}"
                logger.warning(f"[GC Scan] Error processing {error_msg}")
                errors.append(error_msg)

        # 결과 정렬
        state_order = {"READY_TO_BUY": 0, "WAITING_FOR_PULLBACK": 1, "GC_ACTIVE": 2, "NOT_GC": 3}
        results.sort(key=lambda x: state_order.get(x.gc_state, 99))

        # 통계 계산
        gc_active_count = sum(1 for r in results if r.is_gc_active)
        pullback_waiting_count = sum(1 for r in results if r.gc_state == "WAITING_FOR_PULLBACK")
        ready_to_buy_count = sum(1 for r in results if r.gc_state == "READY_TO_BUY")

        logger.info(
            f"[GC Scan] Complete: {len(results)} results, "
            f"GC Active: {gc_active_count}, Ready: {ready_to_buy_count}, Errors: {len(errors)}"
        )

        return GoldenCrossScanListDTO(
            stocks=results,
            total_scanned=len(symbols),
            gc_active_count=gc_active_count,
            pullback_waiting_count=pullback_waiting_count,
            ready_to_buy_count=ready_to_buy_count,
            scan_time=scan_time,
            errors=errors,
        )

    @staticmethod
    def _determine_gc_state(
        is_gc_active: bool,
        stoch_k: float,
        stoch_threshold: float,
    ) -> str:
        """
        골든크로스 상태 결정

        Args:
            is_gc_active: 골든크로스 활성 여부
            stoch_k: 현재 Stochastic K 값
            stoch_threshold: 과매도 임계값

        Returns:
            str: 상태 문자열
        """
        if not is_gc_active:
            return "NOT_GC"

        # 골든크로스 활성 상태에서 Stochastic 확인
        if stoch_k < stoch_threshold:
            # Stochastic이 과매도 구간에 있으면 매수 준비
            return "READY_TO_BUY"
        elif stoch_k < 50:
            # 중간 구간이면 눌림목 대기
            return "WAITING_FOR_PULLBACK"
        else:
            # Stochastic이 높으면 일반 골든크로스 활성
            return "GC_ACTIVE"
