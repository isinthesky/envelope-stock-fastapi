# -*- coding: utf-8 -*-
"""
Buy Strategy Service - 매수 전략 서비스

골든크로스 기반 매수 종목 스캔 및 분석

세션 계약 (2026-01-14 업데이트):
- Repository는 DI로 주입받거나 session으로 생성
- @transaction 데코레이터가 session을 자동 주입
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
from src.adapters.external.dart_api import get_dart_client, FinancialScreeningDTO
from src.application.common.decorators import transaction
from src.application.common.exceptions import StrategyError
from src.application.common.indicators import TechnicalIndicators
from src.application.domain.strategy.dto import (
    GoldenCrossScanItemDTO,
    GoldenCrossScanListDTO,
)
from src.application.domain.strategy.ohlcv_data_loader import LoadType, OHLCVDataLoader


logger = logging.getLogger(__name__)


class BuyStrategyService:
    """
    매수 전략 서비스

    골든크로스 기반 매수 후보 종목을 스캔하고 분석합니다.
    """

    def __init__(
        self,
        universe_repo: StockUniverseRepository | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        """
        Args:
            universe_repo: StockUniverseRepository (DI 주입)
            session: Database Session (레거시 호환)
        """
        # DI 패턴: Repository가 주입된 경우
        if universe_repo is not None:
            self.universe_repo = universe_repo
            self._session = None
        # 레거시 패턴: session이 주입된 경우
        elif session is not None:
            self.universe_repo = StockUniverseRepository(session)
            self._session = session
        # 기본: 빈 Repository (세션은 @transaction에서 주입)
        else:
            self.universe_repo = StockUniverseRepository()
            self._session = None

        self._data_loader: OHLCVDataLoader | None = None

    def _get_data_loader(self, session: AsyncSession | None = None) -> OHLCVDataLoader:
        """OHLCVDataLoader 인스턴스 반환"""
        if self._data_loader is None:
            self._data_loader = OHLCVDataLoader(session or self._session)
        return self._data_loader

    @transaction
    async def scan_golden_cross_candidates(
        self,
        session: AsyncSession,
        market: str | None = None,
        stoch_threshold: float = 30.0,
        gc_only: bool = True,
        include_etf: bool = True,
        cache_freshness_days: int = 1,
        force_refresh: bool = False,
    ) -> GoldenCrossScanListDTO:
        """
        골든크로스 종목 스캔

        기본 스크리닝 통과 종목에 대해 기술적 지표를 계산하여
        골든크로스 전략 조건에 부합하는 종목을 필터링합니다.

        - DB 캐싱을 통해 반복 호출 최소화
        - 캐시가 오래된 경우 증분 업데이트 (chunking 지원)
        - MA55/MA165 지표 사용

        Args:
            session: Database Session (@transaction에서 주입)
            market: 시장 필터 (KOSPI/KOSDAQ/ETF)
            stoch_threshold: Stochastic 과매도 임계값 (기본 30)
            gc_only: 골든크로스 활성 종목만 반환 (기본 True)
            include_etf: ETF 종목도 함께 스캔 (기본 True)
            cache_freshness_days: 캐시 신선도 기준 (일).
                기본 1일 - 당일 데이터가 없으면 API 호출.
                장 마감 후 스캔 시 1일, 주말에는 3일 권장.
            force_refresh: True면 캐시와 관계없이 최신 데이터 요청

        Returns:
            GoldenCrossScanListDTO: 스캔 결과
        """
        scan_time = datetime.now()
        errors: list[str] = []
        results: list[GoldenCrossScanItemDTO] = []

        # 1. 유니버스에서 스크리닝 통과 종목 조회 (ETF 포함 옵션)
        market_type = MarketType(market) if market else None
        stocks = await self.universe_repo.get_eligible_stocks(
            market=market_type,
            include_etf=include_etf,
            session=session,
            limit=300,  # 전체 유니버스 스캔
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

        logger.info(f"[GC Scan] Scanning {len(stocks)} eligible stocks with MA55/MA165")

        # 2. 종목별 기술적 지표 계산
        data_loader = self._get_data_loader(session)

        # 캐시 통계 추적
        cache_stats = {
            "cache_hits": 0,
            "incremental_updates": 0,
            "full_loads": 0,
            "total_api_calls": 0,
            "new_candles": 0,
        }

        for stock in stocks:
            try:
                # OHLCV 데이터 로딩 (증분 업데이트 지원)
                load_result = await data_loader.load_ohlcv_with_stats(
                    symbol=stock.symbol,
                    days=400,
                    interval="1d",
                    min_candles=160,
                    cache_freshness_days=cache_freshness_days,
                    force_refresh=force_refresh,
                )
                df = load_result.df

                # 캐시 통계 업데이트
                if load_result.load_type == LoadType.CACHE_HIT:
                    cache_stats["cache_hits"] += 1
                elif load_result.load_type == LoadType.INCREMENTAL:
                    cache_stats["incremental_updates"] += 1
                else:
                    cache_stats["full_loads"] += 1
                cache_stats["total_api_calls"] += load_result.api_calls
                cache_stats["new_candles"] += load_result.new_candles

                # 지표 계산 (MA55/MA165)
                df = TechnicalIndicators.prepare_golden_cross_indicators(
                    df,
                    short_ma_period=55,
                    long_ma_period=165,
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

                # MA 갭 비율 계산
                ma_gap_ratio = ((ma_short - ma_long) / ma_long * 100) if ma_long > 0 else 0

                # 상태 결정 (stoch_d, ma_gap_ratio 전달)
                gc_state = self._determine_gc_state(
                    is_gc_active=is_gc_active,
                    stoch_k=stoch_k,
                    stoch_threshold=stoch_threshold,
                    stoch_d=stoch_d,
                    ma_gap_ratio=ma_gap_ratio,
                )

                # 결과 추가
                results.append(
                    GoldenCrossScanItemDTO(
                        symbol=stock.symbol,
                        name=stock.name,
                        market=stock.market,
                        current_price=Decimal(str(close)),
                        ma_short=Decimal(str(round(ma_short, 2))),
                        ma_long=Decimal(str(round(ma_long, 2))),
                        ma_gap_ratio=round(ma_gap_ratio, 2),  # 백분율
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
                # 데이터 부족 등의 예상된 오류 - 에러 리스트에 추가하여 디버깅
                error_msg = f"{stock.symbol}: {str(e)}"
                errors.append(error_msg)
                logger.warning(f"[GC Scan] {error_msg}")
            except Exception as e:
                error_msg = f"{stock.symbol}: {str(e)}"
                logger.warning(f"[GC Scan] Error processing {error_msg}")
                errors.append(error_msg)

        # 3. 결과 정렬 (OPTIMAL_BUY > BUY_INTEREST > READY_TO_BUY > WAITING_FOR_PULLBACK > 기타)
        state_order = {
            "OPTIMAL_BUY": 0,
            "BUY_INTEREST": 1,
            "READY_TO_BUY": 2,
            "WAITING_FOR_PULLBACK": 3,
            "GC_ACTIVE": 4,
            "NOT_GC": 5,
        }
        results.sort(key=lambda x: (state_order.get(x.gc_state, 99), -float(x.screening_score or 0)))

        # 4. 통계 계산
        gc_active_count = sum(1 for r in results if r.is_gc_active)
        pullback_waiting_count = sum(1 for r in results if r.gc_state == "WAITING_FOR_PULLBACK")
        buy_interest_count = sum(1 for r in results if r.gc_state == "BUY_INTEREST")
        ready_to_buy_count = sum(1 for r in results if r.gc_state == "READY_TO_BUY")
        optimal_buy_count = sum(1 for r in results if r.gc_state == "OPTIMAL_BUY")

        logger.info(
            f"[GC Scan] Complete: {len(results)} results, "
            f"GC Active: {gc_active_count}, Interest: {buy_interest_count}, "
            f"Ready: {ready_to_buy_count}, Optimal: {optimal_buy_count}, Errors: {len(errors)}"
        )
        logger.info(
            f"[GC Scan] Cache stats: hits={cache_stats['cache_hits']}, "
            f"incremental={cache_stats['incremental_updates']}, "
            f"full={cache_stats['full_loads']}, "
            f"api_calls={cache_stats['total_api_calls']}, "
            f"new_candles={cache_stats['new_candles']}"
        )

        return GoldenCrossScanListDTO(
            stocks=results,
            total_scanned=len(stocks),
            gc_active_count=gc_active_count,
            pullback_waiting_count=pullback_waiting_count,
            buy_interest_count=buy_interest_count,
            ready_to_buy_count=ready_to_buy_count,
            optimal_buy_count=optimal_buy_count,
            scan_time=scan_time,
            errors=errors,
        )

    @transaction
    async def scan_symbols(
        self,
        session: AsyncSession,
        symbols: list[dict],
        stoch_threshold: float = 30.0,
        gc_only: bool = True,
        force_refresh: bool = False,
    ) -> GoldenCrossScanListDTO:
        """
        특정 종목 목록에 대해 골든크로스 스캔

        stock_universe에 없는 종목(ETF 등)도 직접 스캔 가능합니다.

        Args:
            session: Database Session (@transaction에서 주입)
            symbols: 스캔할 종목 목록 [{"symbol": "...", "name": "...", "market": "..."}]
            stoch_threshold: Stochastic 과매도 임계값 (기본 30)
            gc_only: 골든크로스 활성 종목만 반환 (기본 True)
            force_refresh: True면 캐시와 관계없이 최신 데이터 요청

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

        logger.info(f"[GC Scan] Scanning {len(symbols)} symbols with MA55/MA165")

        data_loader = self._get_data_loader(session)

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
                # OHLCV 데이터 로딩 (MA165 계산을 위해 300일 조회, 약 200 거래일)
                df = await data_loader.load_ohlcv_dataframe(
                    symbol=symbol,
                    days=400,
                    interval="1d",
                    min_candles=160,
                    force_refresh=force_refresh,
                )

                # 지표 계산 (MA55/MA165)
                df = TechnicalIndicators.prepare_golden_cross_indicators(
                    df,
                    short_ma_period=55,
                    long_ma_period=165,
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

                # MA 갭 비율 계산
                ma_gap_ratio = ((ma_short - ma_long) / ma_long * 100) if ma_long > 0 else 0

                # 상태 결정 (stoch_d, ma_gap_ratio 전달)
                gc_state = self._determine_gc_state(
                    is_gc_active=is_gc_active,
                    stoch_k=stoch_k,
                    stoch_threshold=stoch_threshold,
                    stoch_d=stoch_d,
                    ma_gap_ratio=ma_gap_ratio,
                )

                # 결과 추가
                results.append(
                    GoldenCrossScanItemDTO(
                        symbol=symbol,
                        name=name,
                        market=market,
                        current_price=Decimal(str(close)),
                        ma_short=Decimal(str(round(ma_short, 2))),
                        ma_long=Decimal(str(round(ma_long, 2))),
                        ma_gap_ratio=round(ma_gap_ratio, 2),
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

        # 결과 정렬 (BUY_INTEREST 추가)
        state_order = {
            "OPTIMAL_BUY": 0,
            "BUY_INTEREST": 1,
            "READY_TO_BUY": 2,
            "WAITING_FOR_PULLBACK": 3,
            "GC_ACTIVE": 4,
            "NOT_GC": 5,
        }
        results.sort(key=lambda x: state_order.get(x.gc_state, 99))

        # 통계 계산
        gc_active_count = sum(1 for r in results if r.is_gc_active)
        pullback_waiting_count = sum(1 for r in results if r.gc_state == "WAITING_FOR_PULLBACK")
        buy_interest_count = sum(1 for r in results if r.gc_state == "BUY_INTEREST")
        ready_to_buy_count = sum(1 for r in results if r.gc_state == "READY_TO_BUY")
        optimal_buy_count = sum(1 for r in results if r.gc_state == "OPTIMAL_BUY")

        logger.info(
            f"[GC Scan] Complete: {len(results)} results, "
            f"GC Active: {gc_active_count}, Interest: {buy_interest_count}, "
            f"Ready: {ready_to_buy_count}, Optimal: {optimal_buy_count}, Errors: {len(errors)}"
        )

        return GoldenCrossScanListDTO(
            stocks=results,
            total_scanned=len(symbols),
            gc_active_count=gc_active_count,
            pullback_waiting_count=pullback_waiting_count,
            buy_interest_count=buy_interest_count,
            ready_to_buy_count=ready_to_buy_count,
            optimal_buy_count=optimal_buy_count,
            scan_time=scan_time,
            errors=errors,
        )

    @staticmethod
    def _determine_gc_state(
        is_gc_active: bool,
        stoch_k: float,
        stoch_threshold: float,
        stoch_d: float = 50.0,
        ma_gap_ratio: float = 0.0,
        # 신규 파라미터 (기본값으로 하위 호환성 유지)
        deep_oversold_threshold: float = 30.0,
        require_momentum_turn: bool = False,
        min_ma_gap: float = 0.0,
        max_ma_gap: float = 8.0,
    ) -> str:
        """
        골든크로스 상태 결정

        Args:
            is_gc_active: 골든크로스 활성 여부
            stoch_k: 현재 Stochastic K 값
            stoch_threshold: 과매도 임계값
            stoch_d: 현재 Stochastic D 값
            ma_gap_ratio: MA 갭 비율 (%)
            deep_oversold_threshold: 깊은 과매도 기준 (기본 30, 기존 25에서 완화)
            require_momentum_turn: K>D 조건 필수 여부 (기본 False)
            min_ma_gap: 최소 MA 갭 비율 (기본 0%)
            max_ma_gap: 최대 MA 갭 비율 (기본 8%, 기존 5에서 완화)

        Returns:
            str: 상태 문자열
            - OPTIMAL_BUY: 매수 적기 (모든 조건 충족)
            - BUY_INTEREST: 매수 관심 (2개 조건 충족)
            - READY_TO_BUY: 매수 준비 (K < threshold)
            - WAITING_FOR_PULLBACK: 눌림목 대기 (K 30~50)
            - GC_ACTIVE: GC 활성 (K >= 50)
            - NOT_GC: GC 비활성
        """
        if not is_gc_active:
            return "NOT_GC"

        # 골든크로스 활성 상태에서 Stochastic 확인
        if stoch_k < stoch_threshold:
            # OPTIMAL_BUY 조건 (보수적 완화 적용)
            is_deep_oversold = stoch_k < deep_oversold_threshold
            is_momentum_turning = (stoch_k > stoch_d) if require_momentum_turn else True
            is_healthy_trend = min_ma_gap <= ma_gap_ratio <= max_ma_gap

            conditions = [is_deep_oversold, is_momentum_turning, is_healthy_trend]
            conditions_met = sum(conditions)

            # 모든 조건 충족: 매수 적기
            if all(conditions):
                return "OPTIMAL_BUY"

            # 2개 이상 조건 충족: 매수 관심
            if conditions_met >= 2:
                return "BUY_INTEREST"

            # 일반 매수 준비
            return "READY_TO_BUY"
        elif stoch_k < 50:
            # 중간 구간이면 눌림목 대기
            return "WAITING_FOR_PULLBACK"
        else:
            # Stochastic이 높으면 일반 골든크로스 활성
            return "GC_ACTIVE"

    # ==================== 재무 필터링 (2차 필터) ====================

    async def apply_financial_filter(
        self,
        scan_result: GoldenCrossScanListDTO,
        target_states: list[str] | None = None,
        max_concurrent: int = 3,
    ) -> GoldenCrossScanListDTO:
        """
        스캔 결과에 재무 필터 적용 (2차 필터)

        DART API를 통해 재무제표를 조회하여 필터링합니다.
        - 매출 YoY ≥ 0%
        - 영업이익 2년 연속 흑자
        - 적자→흑자 전환 별도 분류

        Args:
            scan_result: 골든크로스 스캔 결과
            target_states: 필터 적용 대상 상태 (기본: OPTIMAL_BUY, BUY_INTEREST, READY_TO_BUY)
            max_concurrent: DART API 동시 요청 수 (기본 3, 너무 높으면 rate limit)

        Returns:
            재무 필터가 적용된 스캔 결과
        """
        if target_states is None:
            target_states = ["OPTIMAL_BUY", "BUY_INTEREST", "READY_TO_BUY"]

        # 필터 대상 종목 추출
        target_stocks = [
            stock for stock in scan_result.stocks
            if stock.gc_state in target_states
        ]

        if not target_stocks:
            logger.info("[Financial Filter] No target stocks to filter")
            return scan_result

        logger.info(f"[Financial Filter] Applying to {len(target_stocks)} stocks")

        # DART 클라이언트로 재무 스크리닝
        dart_client = await get_dart_client()
        await dart_client.load_corp_codes()

        # 종목별 재무 스크리닝 결과
        screening_results: dict[str, FinancialScreeningDTO] = {}
        semaphore = asyncio.Semaphore(max_concurrent)

        async def screen_one(symbol: str) -> tuple[str, FinancialScreeningDTO | None]:
            async with semaphore:
                try:
                    result = await dart_client.get_financial_screening(symbol)
                    return symbol, result
                except Exception as e:
                    logger.warning(f"[Financial Filter] {symbol} error: {e}")
                    return symbol, None

        tasks = [screen_one(stock.symbol) for stock in target_stocks]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for item in completed:
            if isinstance(item, Exception):
                continue
            symbol, result = item
            if result:
                screening_results[symbol] = result

        logger.info(f"[Financial Filter] Got {len(screening_results)} screening results")

        # 스캔 결과에 재무 필터 정보 적용
        updated_stocks: list[GoldenCrossScanItemDTO] = []
        financial_pass = 0
        financial_fail = 0
        financial_error = 0
        turnaround = 0
        pending = 0

        for stock in scan_result.stocks:
            screening = screening_results.get(stock.symbol)

            if screening:
                # 재무 스크리닝 결과 적용
                revenue_yoy_value = (
                    float(screening.revenue_yoy) if screening.revenue_yoy is not None else None
                )
                updated_stock = stock.model_copy(update={
                    "financial_filter_status": screening.filter_status,
                    "revenue_yoy": revenue_yoy_value,
                    "operating_margin": float(screening.latest_operating_margin),
                    "is_consecutive_profit": screening.is_consecutive_profit,
                    "is_turnaround": screening.is_turnaround,
                })

                # 통계 업데이트
                if screening.filter_status == "PASS":
                    financial_pass += 1
                elif screening.filter_status == "TURNAROUND":
                    turnaround += 1
                else:
                    financial_fail += 1
            elif stock.gc_state in target_states:
                # 조회 실패 또는 데이터 없음 (ERROR는 FAIL과 분리)
                updated_stock = stock.model_copy(update={
                    "financial_filter_status": "ERROR",
                })
                financial_error += 1
            else:
                # 필터 대상 아님
                updated_stock = stock.model_copy(update={
                    "financial_filter_status": "PENDING",
                })
                pending += 1

            updated_stocks.append(updated_stock)

        # 결과 재정렬 (재무 필터 PASS > TURNAROUND > FAIL > PENDING)
        def sort_key(stock: GoldenCrossScanItemDTO) -> tuple:
            state_order = {
                "OPTIMAL_BUY": 0, "BUY_INTEREST": 1, "READY_TO_BUY": 2,
                "WAITING_FOR_PULLBACK": 3, "GC_ACTIVE": 4, "NOT_GC": 5,
            }
            fin_order = {"PASS": 0, "TURNAROUND": 1, "FAIL": 2, "ERROR": 3, "PENDING": 4, None: 5}
            return (
                state_order.get(stock.gc_state, 99),
                fin_order.get(stock.financial_filter_status, 99),
                -float(stock.screening_score or 0),
            )

        updated_stocks.sort(key=sort_key)

        logger.info(
            f"[Financial Filter] Complete: PASS={financial_pass}, "
            f"TURNAROUND={turnaround}, FAIL={financial_fail}, "
            f"ERROR={financial_error}, PENDING={pending}"
        )

        return GoldenCrossScanListDTO(
            stocks=updated_stocks,
            total_scanned=scan_result.total_scanned,
            gc_active_count=scan_result.gc_active_count,
            pullback_waiting_count=scan_result.pullback_waiting_count,
            buy_interest_count=scan_result.buy_interest_count,
            ready_to_buy_count=scan_result.ready_to_buy_count,
            optimal_buy_count=scan_result.optimal_buy_count,
            scan_time=scan_result.scan_time,
            errors=scan_result.errors,
            financial_pass_count=financial_pass,
            financial_fail_count=financial_fail,
            financial_error_count=financial_error,
            turnaround_count=turnaround,
            financial_pending_count=pending,
        )
