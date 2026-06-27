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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.connection import AsyncSessionLocal

from src.adapters.database.models.naver_industry_code import NaverIndustryCodeModel
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
    MA5BreakoutScanItemDTO,
    MA5BreakoutScanListDTO,
)
from src.application.domain.strategy.ohlcv_data_loader import LoadResult, LoadType, OHLCVDataLoader
from src.application.domain.strategy.signal_evaluator import (
    GoldenCrossScanContext,
    GoldenCrossSignalEvaluator,
)
from src.settings.config import settings


logger = logging.getLogger(__name__)

MA5_VOLUME_RATIO_THRESHOLD = 1.5


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

    @staticmethod
    def _resolve_scan_concurrency(requested: int | None, total: int) -> int:
        """스캔 동시성 제한값 계산"""
        base_limit = min(settings.scan_concurrency_limit, 4)
        desired = requested or base_limit
        safe_limit = max(1, min(desired, settings.kis_api_rate_limit, total))
        if safe_limit != desired:
            logger.info(
                f"[Scan] Capping concurrency from {desired} to {safe_limit} "
                f"(rate_limit={settings.kis_api_rate_limit}, total={total})"
            )
        return safe_limit

    @transaction
    async def scan_golden_cross_candidates(
        self,
        session: AsyncSession,
        market: str | None = None,
        stoch_threshold: float = 30.0,
        gc_only: bool = True,
        include_etf: bool = True,
        limit: int = 1000,
        cache_freshness_days: int = 1,
        force_refresh: bool = False,
        max_concurrent: int | None = None,
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
            max_concurrent: 스캔 동시 처리 수 (None이면 설정값 사용)

        Returns:
            GoldenCrossScanListDTO: 스캔 결과
        """
        scan_time = datetime.now()
        loop = asyncio.get_running_loop()
        scan_started_at = loop.time()
        errors: list[str] = []
        results: list[GoldenCrossScanItemDTO] = []

        # 1. 유니버스에서 스캔 대상 종목 조회 (스크리닝 조건 없이)
        # - B-2 요구사항: 최대 500개(기본)
        market_type = MarketType(market) if market else None
        stocks = await self.universe_repo.get_scan_stocks(
            market=market_type,
            include_etf=include_etf,
            session=session,
            limit=limit,
        )

        if not stocks:
            return GoldenCrossScanListDTO(
                stocks=[],
                total_scanned=0,
                gc_active_count=0,
                pullback_waiting_count=0,
                ready_to_buy_count=0,
                scan_time=scan_time,
                errors=["No scan stocks found in universe"],
            )

        concurrency = self._resolve_scan_concurrency(max_concurrent, len(stocks))
        logger.info(
            f"[GC Scan] Scanning {len(stocks)} stocks with MA55/MA165 "
            f"(concurrency={concurrency}, cache_freshness_days={cache_freshness_days}, "
            f"force_refresh={force_refresh})"
        )

        # 2. 종목별 기술적 지표 계산

        # 캐시 통계 추적
        cache_stats = {
            "cache_hits": 0,
            "incremental_updates": 0,
            "full_loads": 0,
            "total_api_calls": 0,
            "new_candles": 0,
        }

        work_queue: asyncio.Queue[tuple[int, object]] = asyncio.Queue()
        for idx, stock in enumerate(stocks):
            work_queue.put_nowait((idx, stock))

        def update_cache_stats(target: dict[str, int], load_result: LoadResult) -> None:
            if load_result.load_type == LoadType.CACHE_HIT:
                target["cache_hits"] += 1
            elif load_result.load_type == LoadType.INCREMENTAL:
                target["incremental_updates"] += 1
            else:
                target["full_loads"] += 1
            target["total_api_calls"] += load_result.api_calls
            target["new_candles"] += load_result.new_candles

        async def worker() -> (
            tuple[list[tuple[int, GoldenCrossScanItemDTO]], list[tuple[int, str]], dict[str, int]]
        ):
            worker_results: list[tuple[int, GoldenCrossScanItemDTO]] = []
            worker_errors: list[tuple[int, str]] = []
            worker_cache_stats = {
                "cache_hits": 0,
                "incremental_updates": 0,
                "full_loads": 0,
                "total_api_calls": 0,
                "new_candles": 0,
            }

            # 워커(코루틴) 단위로 세션/로더를 1회 생성하여 재사용
            async with AsyncSessionLocal() as worker_session:
                worker_loader = OHLCVDataLoader(worker_session)

                while True:
                    try:
                        if worker_session.in_transaction():
                            await worker_session.rollback()
                        idx, stock = work_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    try:
                        load_result = await worker_loader.load_ohlcv_with_stats(
                            symbol=stock.symbol,
                            days=400,
                            interval="1d",
                            min_candles=160,
                            cache_freshness_days=cache_freshness_days,
                            force_refresh=force_refresh,
                            include_today_candle=True,
                            today_refresh_ttl_seconds=600,
                        )
                        if load_result.load_type == LoadType.CACHE_HIT:
                            if worker_session.in_transaction():
                                await worker_session.rollback()
                        else:
                            await worker_session.commit()
                        df = load_result.df

                        update_cache_stats(worker_cache_stats, load_result)

                        df = TechnicalIndicators.prepare_golden_cross_indicators(
                            df,
                            short_ma_period=55,
                            long_ma_period=165,
                            stoch_k_period=14,
                            stoch_d_period=3,
                        )

                        latest = df.iloc[-1]
                        prev = df.iloc[-2] if len(df) >= 2 else None
                        ma_short = float(latest["ma_short"]) if pd.notna(latest["ma_short"]) else 0
                        ma_long = float(latest["ma_long"]) if pd.notna(latest["ma_long"]) else 0
                        stoch_k = float(latest["stoch_k"]) if pd.notna(latest["stoch_k"]) else 50
                        stoch_d = float(latest["stoch_d"]) if pd.notna(latest["stoch_d"]) else 50
                        prev_stoch_k = (
                            float(prev["stoch_k"])
                            if prev is not None and pd.notna(prev["stoch_k"])
                            else None
                        )
                        close = float(latest["close"])

                        is_gc_active = ma_short > ma_long

                        if gc_only and not is_gc_active:
                            continue

                        ma_gap_ratio = ((ma_short - ma_long) / ma_long * 100) if ma_long > 0 else 0

                        gc_state = self._determine_gc_state(
                            is_gc_active=is_gc_active,
                            stoch_k=stoch_k,
                            stoch_threshold=stoch_threshold,
                            stoch_d=stoch_d,
                            ma_gap_ratio=ma_gap_ratio,
                            prev_stoch_k=prev_stoch_k,
                            recent_oversold=self._has_recent_oversold(df, stoch_threshold),
                        )

                        worker_results.append(
                            (
                                idx,
                                GoldenCrossScanItemDTO(
                                    symbol=stock.symbol,
                                    name=stock.name,
                                    market=stock.market,
                                    current_price=Decimal(str(close)),
                                    industry_code=getattr(stock, "industry", None),
                                    industry_name=None,
                                    ma_short=Decimal(str(round(ma_short, 2))),
                                    ma_long=Decimal(str(round(ma_long, 2))),
                                    ma_gap_ratio=round(ma_gap_ratio, 2),
                                    stoch_k=round(stoch_k, 2),
                                    stoch_d=round(stoch_d, 2),
                                    is_gc_active=is_gc_active,
                                    gc_state=gc_state,
                                    market_cap=stock.market_cap,
                                    screening_score=stock.screening_score,
                                ),
                            )
                        )

                        await asyncio.sleep(0.05)

                    except ValueError as e:
                        error_msg = f"{stock.symbol}: {str(e)}"
                        logger.warning(f"[GC Scan] {error_msg}")
                        worker_errors.append((idx, error_msg))
                        if worker_session.in_transaction():
                            await worker_session.rollback()
                    except Exception as e:
                        error_msg = f"{stock.symbol}: {str(e)}"
                        logger.warning(f"[GC Scan] Error processing {error_msg}")
                        worker_errors.append((idx, error_msg))
                        if worker_session.in_transaction():
                            await worker_session.rollback()
                    finally:
                        work_queue.task_done()

            return worker_results, worker_errors, worker_cache_stats

        workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
        completed = await asyncio.gather(*workers, return_exceptions=True)

        error_map: dict[int, str] = {}
        for item in completed:
            if isinstance(item, Exception):
                errors.append(str(item))
                continue
            worker_results, worker_errors, worker_cache_stats = item
            results.extend([result for _, result in worker_results])
            for idx, error_msg in worker_errors:
                error_map[idx] = error_msg
            for key in cache_stats:
                cache_stats[key] += worker_cache_stats.get(key, 0)

        if error_map:
            for idx in sorted(error_map):
                errors.append(error_map[idx])

        # 3. 결과 정렬 (OPTIMAL_BUY > BUY_INTEREST > READY_TO_BUY > WAITING_FOR_PULLBACK > 기타)
        state_order = {
            "OPTIMAL_BUY": 0,
            "BUY_INTEREST": 1,
            "READY_TO_BUY": 2,
            "WAITING_FOR_PULLBACK": 3,
            "GC_ACTIVE": 4,
            "NOT_GC": 5,
        }
        results.sort(
            key=lambda x: (
                state_order.get(x.gc_state, 99),
                -float(x.screening_score or 0),
                x.symbol,
            )
        )

        # 4. 업종명 매핑 (industry_code -> industry_name)
        # - 운영에서 industry는 네이버 industryCode(숫자 문자열)를 저장
        industry_codes = {r.industry_code for r in results if r.industry_code}
        if industry_codes:
            try:
                stmt = select(NaverIndustryCodeModel).where(
                    NaverIndustryCodeModel.industry_code.in_(industry_codes)
                )
                mapping_rows = (await session.execute(stmt)).scalars().all()
                code_to_name = {row.industry_code: row.industry_name for row in mapping_rows}
                for r in results:
                    if r.industry_code:
                        r.industry_name = code_to_name.get(r.industry_code)
            except Exception as e:
                # 매핑 테이블 미생성/미마이그레이션 등의 상황에서도 스캔 자체는 깨지지 않게 한다.
                logger.warning(f"[GC Scan] Failed to attach industry names: {e}")

        # 5. 통계 계산
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
        scan_duration = loop.time() - scan_started_at
        logger.info(
            f"[GC Scan] Timing: {scan_duration:.2f}s total, "
            f"{scan_duration / max(len(stocks), 1):.2f}s/stock, "
            f"concurrency={concurrency}"
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
                prev = df.iloc[-2] if len(df) >= 2 else None
                ma_short = float(latest["ma_short"]) if pd.notna(latest["ma_short"]) else 0
                ma_long = float(latest["ma_long"]) if pd.notna(latest["ma_long"]) else 0
                stoch_k = float(latest["stoch_k"]) if pd.notna(latest["stoch_k"]) else 50
                stoch_d = float(latest["stoch_d"]) if pd.notna(latest["stoch_d"]) else 50
                prev_stoch_k = (
                    float(prev["stoch_k"])
                    if prev is not None and pd.notna(prev["stoch_k"])
                    else None
                )
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
                    prev_stoch_k=prev_stoch_k,
                    recent_oversold=self._has_recent_oversold(df, stoch_threshold),
                )

                # 결과 추가
                results.append(
                    GoldenCrossScanItemDTO(
                        symbol=symbol,
                        name=name,
                        market=market,
                        current_price=Decimal(str(close)),
                        industry_code=None,
                        industry_name=None,
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
        deep_oversold_threshold: float | None = None,
        require_momentum_turn: bool = True,
        min_ma_gap: float = 0.0,
        max_ma_gap: float = 8.0,
        *,
        prev_stoch_k: float | None = None,
        recent_oversold: bool = False,
        recovery_threshold: float = 20.0,
        strong_recovery_threshold: float = 30.0,
    ) -> str:
        """
        골든크로스 상태 결정

        Args:
            is_gc_active: 골든크로스 활성 여부
            stoch_k: 현재 Stochastic K 값
            stoch_threshold: 과매도 임계값
            stoch_d: 현재 Stochastic D 값
            ma_gap_ratio: MA 갭 비율 (%)
            prev_stoch_k: 이전 Stochastic K 값
            recent_oversold: 최근 캔들에 과매도 구간이 있었는지 여부
            recovery_threshold: 과매도 후 회복 기준
            strong_recovery_threshold: 강한 회복 기준
            require_momentum_turn: K>D 조건 필수 여부
            min_ma_gap: 최소 MA 갭 비율 (기본 0%)
            max_ma_gap: 최대 MA 갭 비율 (기본 8%, 기존 5에서 완화)
            deep_oversold_threshold: 하위 호환용 인자. 현재 상태 판정에는 사용하지 않음.

        Returns:
            str: 상태 문자열
            - OPTIMAL_BUY: 매수 적기 (모든 조건 충족)
            - BUY_INTEREST: 매수 관심 (2개 조건 충족)
            - READY_TO_BUY: 매수 준비 (K < threshold)
            - WAITING_FOR_PULLBACK: 눌림목 대기 (K 30~50)
            - GC_ACTIVE: GC 활성 (K >= 50)
            - NOT_GC: GC 비활성
        """
        _ = deep_oversold_threshold
        return GoldenCrossSignalEvaluator.classify_scan_state(
            GoldenCrossScanContext(
                is_gc_active=is_gc_active,
                stoch_k=stoch_k,
                stoch_d=stoch_d,
                stoch_threshold=stoch_threshold,
                ma_gap_ratio=ma_gap_ratio,
                prev_stoch_k=prev_stoch_k,
                recent_oversold=recent_oversold,
                recovery_threshold=recovery_threshold,
                strong_recovery_threshold=strong_recovery_threshold,
                require_momentum_turn=require_momentum_turn,
                min_ma_gap=min_ma_gap,
                max_ma_gap=max_ma_gap,
            )
        )

    @staticmethod
    def _has_recent_oversold(
        df: pd.DataFrame,
        stoch_threshold: float,
        lookback_bars: int = 5,
    ) -> bool:
        """현재 캔들 전 최근 구간에서 과매도 풀백이 있었는지 확인한다."""
        if "stoch_k" not in df.columns or len(df) < 2:
            return False
        recent = df["stoch_k"].iloc[-(lookback_bars + 1) : -1]
        return bool((recent < stoch_threshold).any())

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
        target_stocks = [stock for stock in scan_result.stocks if stock.gc_state in target_states]

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
                updated_stock = stock.model_copy(
                    update={
                        "financial_filter_status": screening.filter_status,
                        "revenue_yoy": revenue_yoy_value,
                        "operating_margin": float(screening.latest_operating_margin),
                        "is_consecutive_profit": screening.is_consecutive_profit,
                        "is_turnaround": screening.is_turnaround,
                    }
                )

                # 통계 업데이트
                if screening.filter_status == "PASS":
                    financial_pass += 1
                elif screening.filter_status == "TURNAROUND":
                    turnaround += 1
                else:
                    financial_fail += 1
            elif stock.gc_state in target_states:
                # 조회 실패 또는 데이터 없음 (ERROR는 FAIL과 분리)
                updated_stock = stock.model_copy(
                    update={
                        "financial_filter_status": "ERROR",
                    }
                )
                financial_error += 1
            else:
                # 필터 대상 아님
                updated_stock = stock.model_copy(
                    update={
                        "financial_filter_status": "PENDING",
                    }
                )
                pending += 1

            updated_stocks.append(updated_stock)

        # 결과 재정렬 (재무 필터 PASS > TURNAROUND > FAIL > PENDING)
        def sort_key(stock: GoldenCrossScanItemDTO) -> tuple:
            state_order = {
                "OPTIMAL_BUY": 0,
                "BUY_INTEREST": 1,
                "READY_TO_BUY": 2,
                "WAITING_FOR_PULLBACK": 3,
                "GC_ACTIVE": 4,
                "NOT_GC": 5,
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

    # ==================== MA5 돌파 전략 스캔 ====================

    @transaction
    async def scan_ma5_breakout_candidates(
        self,
        session: AsyncSession,
        market: str | None = None,
        short_period: int = 5,
        long_period: int = 300,
        envelope_pct: float = 0.7,
        use_volume_filter: bool = True,
        include_etf: bool = True,
        limit: int = 1000,
        max_concurrent: int | None = None,
    ) -> MA5BreakoutScanListDTO:
        """
        MA5 엔벨로프 상단 돌파 종목 스캔

        Args:
            session: Database Session (@transaction에서 주입)
            market: 시장 필터 (KOSPI/KOSDAQ/ETF)
            short_period: 단기 MA 기간 (기본 5)
            long_period: 장기 MA 기간 (기본 300)
            envelope_pct: 엔벨로프 % (기본 0.7)
            use_volume_filter: 거래량 필터 사용 여부
            include_etf: ETF 종목 포함 여부
            max_concurrent: 스캔 동시 처리 수 (None이면 설정값 사용)

        Returns:
            MA5BreakoutScanListDTO: 스캔 결과
        """
        scan_time = datetime.now()
        loop = asyncio.get_running_loop()
        scan_started_at = loop.time()
        errors: list[str] = []
        results: list[MA5BreakoutScanItemDTO] = []

        # 1. 유니버스에서 스크리닝 통과 종목 조회
        market_type = MarketType(market) if market else None
        stocks = await self.universe_repo.get_eligible_stocks(
            market=market_type,
            include_etf=include_etf,
            session=session,
            limit=limit,
        )

        if not stocks:
            return MA5BreakoutScanListDTO(
                stocks=[],
                total_scanned=0,
                scan_time=scan_time,
                errors=["No scan stocks found in universe"],
            )

        concurrency = self._resolve_scan_concurrency(max_concurrent, len(stocks))
        logger.info(
            f"[MA5 Scan] Scanning {len(stocks)} eligible stocks with MA{short_period}/MA{long_period} "
            f"(concurrency={concurrency}, envelope_pct={envelope_pct}, volume_filter={use_volume_filter})"
        )

        # 2. 종목별 기술적 지표 계산

        cache_stats = {
            "cache_hits": 0,
            "incremental_updates": 0,
            "full_loads": 0,
            "total_api_calls": 0,
            "new_candles": 0,
        }

        work_queue: asyncio.Queue[tuple[int, object]] = asyncio.Queue()
        for idx, stock in enumerate(stocks):
            work_queue.put_nowait((idx, stock))

        def update_cache_stats(target: dict[str, int], load_result: LoadResult) -> None:
            if load_result.load_type == LoadType.CACHE_HIT:
                target["cache_hits"] += 1
            elif load_result.load_type == LoadType.INCREMENTAL:
                target["incremental_updates"] += 1
            else:
                target["full_loads"] += 1
            target["total_api_calls"] += load_result.api_calls
            target["new_candles"] += load_result.new_candles

        async def worker() -> (
            tuple[list[tuple[int, MA5BreakoutScanItemDTO]], list[tuple[int, str]], dict[str, int]]
        ):
            worker_results: list[tuple[int, MA5BreakoutScanItemDTO]] = []
            worker_errors: list[tuple[int, str]] = []
            worker_cache_stats = {
                "cache_hits": 0,
                "incremental_updates": 0,
                "full_loads": 0,
                "total_api_calls": 0,
                "new_candles": 0,
            }

            # 워커(코루틴) 단위로 세션/로더를 1회 생성하여 재사용
            async with AsyncSessionLocal() as worker_session:
                worker_loader = OHLCVDataLoader(worker_session)

                while True:
                    try:
                        if worker_session.in_transaction():
                            await worker_session.rollback()
                        idx, stock = work_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    try:
                        load_result = await worker_loader.load_ohlcv_with_stats(
                            symbol=stock.symbol,
                            days=500,
                            interval="1d",
                            min_candles=long_period + 20,
                            cache_freshness_days=1,
                            include_today_candle=True,
                            today_refresh_ttl_seconds=600,
                        )
                        if load_result.load_type == LoadType.CACHE_HIT:
                            if worker_session.in_transaction():
                                await worker_session.rollback()
                        else:
                            await worker_session.commit()
                        df = load_result.df

                        update_cache_stats(worker_cache_stats, load_result)

                        if len(df) < long_period:
                            continue

                        df["ma_short"] = df["close"].rolling(window=short_period).mean()
                        df["ma_long"] = df["close"].rolling(window=long_period).mean()
                        df["volume_ma20"] = df["volume"].rolling(window=20).mean()

                        latest = df.iloc[-1]
                        prev = df.iloc[-2] if len(df) > 1 else latest

                        ma5 = float(latest["ma_short"]) if pd.notna(latest["ma_short"]) else 0
                        ma300 = float(latest["ma_long"]) if pd.notna(latest["ma_long"]) else 0
                        close = float(latest["close"])
                        volume = float(latest["volume"]) if pd.notna(latest["volume"]) else 0
                        volume_ma20 = (
                            float(latest["volume_ma20"]) if pd.notna(latest["volume_ma20"]) else 1
                        )

                        prev_ma5 = float(prev["ma_short"]) if pd.notna(prev["ma_short"]) else 0

                        if ma300 <= 0:
                            continue

                        upper_band = ma300 * (1 + envelope_pct / 100)

                        ma5_above_upper = ma5 > upper_band
                        prev_ma5_above_upper = prev_ma5 > (ma300 * (1 + envelope_pct / 100))
                        price_above_upper = close > upper_band

                        is_breakout = (
                            ma5_above_upper and not prev_ma5_above_upper and price_above_upper
                        )

                        if not is_breakout:
                            continue

                        ma5_state = "BREAKOUT"
                        gap_ratio = ((ma5 - upper_band) / upper_band * 100) if upper_band > 0 else 0

                        if use_volume_filter and volume_ma20 > 0:
                            volume_ratio = volume / volume_ma20
                            if volume_ratio < MA5_VOLUME_RATIO_THRESHOLD:
                                continue
                        else:
                            volume_ratio = volume / volume_ma20 if volume_ma20 > 0 else 0

                        worker_results.append(
                            (
                                idx,
                                MA5BreakoutScanItemDTO(
                                    symbol=stock.symbol,
                                    name=stock.name,
                                    market=stock.market,
                                    current_price=Decimal(str(close)),
                                    ma5=Decimal(str(round(ma5, 2))),
                                    ma300=Decimal(str(round(ma300, 2))),
                                    upper_band=Decimal(str(round(upper_band, 2))),
                                    ma5_state=ma5_state,
                                    gap_ratio=round(gap_ratio, 2),
                                    envelope_pct=envelope_pct,
                                    volume_ratio=round(volume_ratio, 2),
                                    market_cap=stock.market_cap,
                                    screening_score=stock.screening_score,
                                ),
                            )
                        )

                        await asyncio.sleep(0.05)

                    except ValueError as e:
                        error_msg = f"{stock.symbol}: {str(e)}"
                        logger.warning(f"[MA5 Scan] {error_msg}")
                        worker_errors.append((idx, error_msg))
                        if worker_session.in_transaction():
                            await worker_session.rollback()
                    except Exception as e:
                        error_msg = f"{stock.symbol}: {str(e)}"
                        logger.warning(f"[MA5 Scan] Error processing {error_msg}")
                        worker_errors.append((idx, error_msg))
                        if worker_session.in_transaction():
                            await worker_session.rollback()
                    finally:
                        work_queue.task_done()

            return worker_results, worker_errors, worker_cache_stats

        workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
        completed = await asyncio.gather(*workers, return_exceptions=True)

        error_map: dict[int, str] = {}
        for item in completed:
            if isinstance(item, Exception):
                errors.append(str(item))
                continue
            worker_results, worker_errors, worker_cache_stats = item
            results.extend([result for _, result in worker_results])
            for idx, error_msg in worker_errors:
                error_map[idx] = error_msg
            for key in cache_stats:
                cache_stats[key] += worker_cache_stats.get(key, 0)

        if error_map:
            for idx in sorted(error_map):
                errors.append(error_map[idx])

        # 3. 결과 정렬 (BREAKOUT > ABOVE > BELOW)
        state_order = {"BREAKOUT": 0, "ABOVE": 1, "BELOW": 2}
        results.sort(key=lambda x: (state_order.get(x.ma5_state, 99), -x.gap_ratio, x.symbol))

        # 4. 통계 계산
        breakout_count = sum(1 for r in results if r.ma5_state == "BREAKOUT")
        above_count = sum(1 for r in results if r.ma5_state == "ABOVE")
        below_count = sum(1 for r in results if r.ma5_state == "BELOW")

        logger.info(
            f"[MA5 Scan] Complete: {len(results)} results, "
            f"BREAKOUT: {breakout_count}, ABOVE: {above_count}, BELOW: {below_count}, Errors: {len(errors)}"
        )
        logger.info(
            f"[MA5 Scan] Cache stats: hits={cache_stats['cache_hits']}, "
            f"incremental={cache_stats['incremental_updates']}, "
            f"full={cache_stats['full_loads']}, "
            f"api_calls={cache_stats['total_api_calls']}, "
            f"new_candles={cache_stats['new_candles']}"
        )
        scan_duration = loop.time() - scan_started_at
        logger.info(
            f"[MA5 Scan] Timing: {scan_duration:.2f}s total, "
            f"{scan_duration / max(len(stocks), 1):.2f}s/stock, "
            f"concurrency={concurrency}"
        )

        return MA5BreakoutScanListDTO(
            stocks=results,
            total_scanned=len(stocks),
            breakout_count=breakout_count,
            above_count=above_count,
            below_count=below_count,
            scan_time=scan_time,
            errors=errors,
        )

    @transaction
    async def scan_ma5_breakout_symbols(
        self,
        session: AsyncSession,
        symbols: list[dict],
        short_period: int = 5,
        long_period: int = 300,
        envelope_pct: float = 0.7,
        use_volume_filter: bool = True,
    ) -> MA5BreakoutScanListDTO:
        """
        특정 종목 목록에 대해 MA5 돌파 스캔

        Args:
            session: Database Session (@transaction에서 주입)
            symbols: 스캔할 종목 목록 [{"symbol": "...", "name": "...", "market": "..."}]
            short_period: 단기 MA 기간 (기본 5)
            long_period: 장기 MA 기간 (기본 300)
            envelope_pct: 엔벨로프 % (기본 0.7)
            use_volume_filter: 거래량 필터 사용 여부

        Returns:
            MA5BreakoutScanListDTO: 스캔 결과
        """
        scan_time = datetime.now()
        errors: list[str] = []
        results: list[MA5BreakoutScanItemDTO] = []

        if not symbols:
            return MA5BreakoutScanListDTO(
                stocks=[],
                total_scanned=0,
                scan_time=scan_time,
                errors=["No symbols provided"],
            )

        logger.info(
            f"[MA5 Scan] Scanning {len(symbols)} symbols with MA{short_period}/MA{long_period}"
        )

        data_loader = self._get_data_loader(session)

        # 종목명 조회 서비스
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
            market = item.get("market") or "UNKNOWN"

            if not symbol:
                continue

            # 종목명 조회
            if not name and market_data_service:
                try:
                    name = await market_data_service.get_stock_name(symbol)
                except Exception:
                    pass
            name = name or symbol

            try:
                df = await data_loader.load_ohlcv_dataframe(
                    symbol=symbol,
                    days=500,
                    interval="1d",
                    min_candles=long_period + 20,
                )

                if len(df) < long_period:
                    continue

                # MA 계산
                df["ma_short"] = df["close"].rolling(window=short_period).mean()
                df["ma_long"] = df["close"].rolling(window=long_period).mean()
                df["volume_ma20"] = df["volume"].rolling(window=20).mean()

                latest = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else latest

                ma5 = float(latest["ma_short"]) if pd.notna(latest["ma_short"]) else 0
                ma300 = float(latest["ma_long"]) if pd.notna(latest["ma_long"]) else 0
                close = float(latest["close"])
                volume = float(latest["volume"]) if pd.notna(latest["volume"]) else 0
                volume_ma20 = float(latest["volume_ma20"]) if pd.notna(latest["volume_ma20"]) else 1

                prev_ma5 = float(prev["ma_short"]) if pd.notna(prev["ma_short"]) else 0

                if ma300 <= 0:
                    continue

                upper_band = ma300 * (1 + envelope_pct / 100)

                ma5_above_upper = ma5 > upper_band
                prev_ma5_above_upper = prev_ma5 > (ma300 * (1 + envelope_pct / 100))
                price_above_upper = close > upper_band

                is_breakout = ma5_above_upper and not prev_ma5_above_upper and price_above_upper

                volume_ratio = volume / volume_ma20 if volume_ma20 > 0 else 1.0

                if use_volume_filter and is_breakout and volume_ratio < MA5_VOLUME_RATIO_THRESHOLD:
                    is_breakout = False

                if is_breakout:
                    ma5_state = "BREAKOUT"
                elif ma5_above_upper:
                    ma5_state = "ABOVE"
                else:
                    ma5_state = "BELOW"

                gap_ratio = ((ma5 - upper_band) / upper_band * 100) if upper_band > 0 else 0

                results.append(
                    MA5BreakoutScanItemDTO(
                        symbol=symbol,
                        name=name,
                        market=market,
                        current_price=close,
                        ma5=round(ma5, 2),
                        ma300=round(ma300, 2),
                        upper_band=round(upper_band, 2),
                        ma5_state=ma5_state,
                        gap_ratio=round(gap_ratio, 2),
                        volume_ratio=round(volume_ratio, 2),
                    )
                )

                await asyncio.sleep(0.05)

            except Exception as e:
                error_msg = f"{symbol}: {str(e)}"
                logger.warning(f"[MA5 Scan] Error processing {error_msg}")
                errors.append(error_msg)

        state_order = {"BREAKOUT": 0, "ABOVE": 1, "BELOW": 2}
        results.sort(key=lambda x: (state_order.get(x.ma5_state, 99), -x.gap_ratio))

        breakout_count = sum(1 for r in results if r.ma5_state == "BREAKOUT")
        above_count = sum(1 for r in results if r.ma5_state == "ABOVE")
        below_count = sum(1 for r in results if r.ma5_state == "BELOW")

        logger.info(
            f"[MA5 Scan] Complete: {len(results)} results, "
            f"BREAKOUT: {breakout_count}, ABOVE: {above_count}, BELOW: {below_count}"
        )

        return MA5BreakoutScanListDTO(
            stocks=results,
            total_scanned=len(symbols),
            breakout_count=breakout_count,
            above_count=above_count,
            below_count=below_count,
            scan_time=scan_time,
            errors=errors,
        )
