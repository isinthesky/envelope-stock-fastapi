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
import math
from datetime import datetime, timedelta, timezone
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
from src.adapters.external.dart_api import FinancialScreeningDTO, get_dart_client
from src.application.common.decorators import transaction
from src.application.common.indicators import TechnicalIndicators
from src.application.domain.backtest.regime_filter import (
    RegimeEntryFilter,
    is_entry_allowed_latest,
)
from src.application.domain.strategy.dto import (
    GoldenCrossScanItemDTO,
    GoldenCrossScanListDTO,
)
from src.application.domain.strategy.ohlcv_data_loader import (
    LoadResult,
    LoadType,
    OHLCVDataLoader,
    get_kospi_or_proxy_closes,
    get_regime_benchmark_ohlc,
)
from src.application.domain.strategy.signal_evaluator import (
    GoldenCrossScanContext,
    GoldenCrossSignalEvaluator,
)
from src.application.domain.strategy.strategy_contract import (
    DEFAULT_GOLDEN_CROSS_PULLBACK,
    GOLDEN_CROSS_SCAN_STATE_ORDER,
)
from src.settings.config import settings

logger = logging.getLogger(__name__)

# 골든크로스 스캔 결과 정렬 우선순위 (계약의 canonical 순서에서 파생).
# {state_value: rank}. 미등록 상태(FEAR_BUY 등)는 .get(..., 99)로 최하위 처리한다.
GC_SCAN_STATE_ORDER: dict[str, int] = {
    state.value: idx for idx, state in enumerate(GOLDEN_CROSS_SCAN_STATE_ORDER)
}


def _build_regime_filter() -> RegimeEntryFilter:
    """운영 설정(gc_regime_mode/ma/adx)으로 진입 국면 필터를 구성한다.
    walk-forward A/B가 검증한 것과 동일한 RegimeEntryFilter를 사용해 라이브·백테스트
    수식을 일치시킨다. 알 수 없는 mode는 권장값(adx)로 폴백."""
    mode = settings.gc_regime_mode
    use_ma = mode in ("ma", "ma_adx")
    use_adx = mode in ("adx", "ma_adx")
    if not use_ma and not use_adx:  # 방어: 미지의 mode → ADX(권장)
        use_adx = True
    return RegimeEntryFilter(
        use_ma=use_ma,
        ma_period=settings.gc_regime_ma,
        use_adx=use_adx,
        adx_period=settings.gc_regime_adx_period,
        adx_min=settings.gc_regime_adx_min,
    )


def _market_regime_ok(bench_df) -> bool:
    """시장 레짐 진입 허용 판정(하드 게이트). 실 OHLC 벤치가 없거나(프록시 불가)
    최신 바가 stale/미래이면 신뢰불가 → fail-open(True). 그 외에는 검증된
    `is_entry_allowed_latest`(라이브·백테스트 공용)로 최신 바를 판정한다."""
    if bench_df is None or getattr(bench_df, "empty", True):
        return True
    try:
        last = bench_df["timestamp"].iloc[-1]
        if getattr(last, "tzinfo", None) is None:
            last = last.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - last
        # 오래됨(>7일) 또는 미래(음수 age, 데이터 오류)면 신뢰불가 → fail-open
        if age > timedelta(days=7) or age < -timedelta(days=1):
            logger.warning("[GC Scan] regime benchmark stale/future (last=%s), fail-open", last)
            return True
    except Exception:  # noqa: BLE001
        return True
    return is_entry_allowed_latest(bench_df, _build_regime_filter())


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

    @staticmethod
    def _update_cache_stats(target: dict[str, int], load_result: LoadResult) -> None:
        """워커 캐시 통계 누적."""
        if load_result.load_type == LoadType.CACHE_HIT:
            target["cache_hits"] += 1
        elif load_result.load_type == LoadType.INCREMENTAL:
            target["incremental_updates"] += 1
        else:
            target["full_loads"] += 1
        target["total_api_calls"] += load_result.api_calls
        target["new_candles"] += load_result.new_candles

    async def _run_scan_workers(
        self,
        stocks,
        concurrency: int,
        process_stock,
        log_prefix: str,
    ):
        """work_queue/worker/세션/gather/error_map 동시성 스캐폴딩 (candidates 공용).

        process_stock(worker_loader, worker_session, stock, worker_cache_stats) -> DTO | None
        를 각 종목에 대해 호출한다. DTO를 반환하면 결과에 수집하고, None이면 스킵한다.
        (load/commit/rollback/캐시통계 업데이트/rate-limit sleep은 process_stock 내부 책임)

        Returns:
            (results, errors, cache_stats): 원본 candidates 집계 순서/의미 그대로.
        """
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

        async def worker():
            worker_results: list[tuple[int, object]] = []
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
                        dto = await process_stock(
                            worker_loader, worker_session, stock, worker_cache_stats
                        )
                        if dto is not None:
                            worker_results.append((idx, dto))
                    except ValueError as e:
                        error_msg = f"{stock.symbol}: {str(e)}"
                        logger.warning(f"{log_prefix} {error_msg}")
                        worker_errors.append((idx, error_msg))
                        if worker_session.in_transaction():
                            await worker_session.rollback()
                    except Exception as e:
                        error_msg = f"{stock.symbol}: {str(e)}"
                        logger.warning(f"{log_prefix} Error processing {error_msg}")
                        worker_errors.append((idx, error_msg))
                        if worker_session.in_transaction():
                            await worker_session.rollback()
                    finally:
                        work_queue.task_done()

            return worker_results, worker_errors, worker_cache_stats

        workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
        completed = await asyncio.gather(*workers, return_exceptions=True)

        results: list = []
        errors: list[str] = []
        error_map: dict[int, str] = {}
        for item in completed:
            if isinstance(item, BaseException):
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

        return results, errors, cache_stats

    def _evaluate_gc_row(
        self,
        df: pd.DataFrame,
        *,
        symbol: str,
        name: str | None,
        market: str | None,
        sector_name: str | None,
        industry_code: str | None,
        industry_name: str | None,
        market_cap,
        screening_score,
        short_ma_period: int,
        long_ma_period: int,
        stoch_threshold: float,
        gc_only: bool,
        market_regime_up: bool,
        market_fear_window_open: bool,
        enable_fear_buy: bool,
    ) -> GoldenCrossScanItemDTO | None:
        """골든크로스 스캔 1종목 평가 → DTO(or None).

        candidates(worker)와 symbols 경로의 공통 지표추출/MA유한가드/후보판정/상태판정/
        DTO조립을 공유한다. 경로별 의도된 차이는 플래그로 보존한다.
        - enable_fear_buy=True(candidates): fear-buy 후보 태깅 활성 + gc_only=True 고정 호출.
        - enable_fear_buy=False(symbols): fear-buy 미적용, 인자 gc_only 존중.
        """
        df = TechnicalIndicators.prepare_golden_cross_indicators(
            df,
            short_ma_period=short_ma_period,
            long_ma_period=long_ma_period,
            stoch_k_period=DEFAULT_GOLDEN_CROSS_PULLBACK.stoch_k_period,
            stoch_d_period=DEFAULT_GOLDEN_CROSS_PULLBACK.stoch_d_period,
            include_rsi=True,
            rsi_period=14,
        )

        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else None
        ma_short = float(latest["ma_short"]) if pd.notna(latest["ma_short"]) else 0
        ma_long = float(latest["ma_long"]) if pd.notna(latest["ma_long"]) else 0
        stoch_k = float(latest["stoch_k"]) if pd.notna(latest["stoch_k"]) else 50
        stoch_d = float(latest["stoch_d"]) if pd.notna(latest["stoch_d"]) else 50
        rsi = float(latest["rsi"]) if pd.notna(latest.get("rsi", None)) else None
        prev_stoch_k = (
            float(prev["stoch_k"]) if prev is not None and pd.notna(prev["stoch_k"]) else None
        )
        close = float(latest["close"])

        # 장·단기 MA가 유한 양수가 아니면(캔들 부족 NaN→0, 비정상 inf 등) 골든크로스 오판 방지: 스킵.
        if not (
            ma_short > 0 and ma_long > 0 and math.isfinite(ma_short) and math.isfinite(ma_long)
        ):
            return None

        is_gc_active = ma_short > ma_long

        # === 매수 후보 판정 (#A GC+RSI, #2/#3 fear-window, regime) ===
        gc_pass = is_gc_active
        if is_gc_active and settings.gc_require_rsi_oversold:
            gc_pass = rsi is not None and rsi <= settings.gc_rsi_threshold
        # [regime] 시장 하락레짐(KOSPI<MA)이면 GC(추세추종) 진입 차단.
        if settings.gc_regime_filter_enabled and not market_regime_up:
            gc_pass = False

        # Fear-buy 후보: 시장 공포 윈도우 열림 + 개별 과매도(RSI 임계). symbols 경로는 미적용.
        fear_pass = (
            enable_fear_buy
            and settings.fear_buy_window_enabled
            and market_fear_window_open
            and rsi is not None
            and rsi <= settings.fear_buy_rsi_threshold
        )

        # gc_only=False(symbols 경로)에서만 비-GC 종목을 NOT_GC로 통과시킨다.
        # candidates 경로는 gc_only=True 고정 호출 → 항상 (gc_pass or fear_pass) 게이트.
        keep = True if (not gc_only and not is_gc_active) else (gc_pass or fear_pass)
        if not keep:
            return None

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
        # gc_pass가 아닌데 fear_pass로 통과한 후보는 FEAR_BUY로 태깅 (symbols 경로는 fear_pass=False).
        if fear_pass and not gc_pass:
            gc_state = "FEAR_BUY"

        return GoldenCrossScanItemDTO(
            symbol=symbol,
            name=name,
            market=market,
            current_price=Decimal(str(close)),
            sector_name=sector_name,
            industry_code=industry_code,
            industry_name=industry_name,
            ma_short=Decimal(str(round(ma_short, 2))),
            ma_long=Decimal(str(round(ma_long, 2))),
            ma_gap_ratio=round(ma_gap_ratio, 2),
            stoch_k=round(stoch_k, 2),
            stoch_d=round(stoch_d, 2),
            is_gc_active=is_gc_active,
            gc_state=gc_state,
            market_cap=market_cap,
            screening_score=screening_score,
        )

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
        short_ma_period: int | None = None,
        long_ma_period: int | None = None,
    ) -> GoldenCrossScanListDTO:
        """
        골든크로스 종목 스캔

        기본 스크리닝 통과 종목에 대해 기술적 지표를 계산하여
        골든크로스 전략 조건에 부합하는 종목을 필터링합니다.

        - DB 캐싱을 통해 반복 호출 최소화
        - 캐시가 오래된 경우 증분 업데이트 (chunking 지원)
        - config MA(단기/장기) 지표 사용

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
            f"[GC Scan] Scanning {len(stocks)} stocks with "
            f"MA{settings.gc_short_ma_period}/MA{settings.gc_long_ma_period} "
            f"(concurrency={concurrency}, cache_freshness_days={cache_freshness_days}, "
            f"force_refresh={force_refresh})"
        )

        # === 시장 레짐/공포 (스캔당 1회 계산, fail-open) ===
        # KOSPI(또는 대형주 프록시) 종가로 시장 상태를 판정한다.
        market_fear_window_open = False
        market_regime_up = True  # 레짐필터 off거나 데이터 부족 시 통과(fail-open)
        if settings.fear_buy_window_enabled or settings.gc_regime_filter_enabled:
            try:
                if settings.fear_buy_window_enabled:
                    # 공포 윈도우: 종가 시계열(프록시 허용)로 BB 기반 판정
                    market_closes, _mts, _src = await get_kospi_or_proxy_closes(session, days=500)
                    market_fear_window_open = TechnicalIndicators.is_market_fear_recent(
                        market_closes, window=settings.fear_buy_window_days
                    )
                if settings.gc_regime_filter_enabled:
                    # 레짐: 실 OHLC 벤치(ADX엔 high/low 필요) — 없으면 fail-open
                    regime_bench = await get_regime_benchmark_ohlc(
                        session, settings.gc_regime_benchmark, days=500
                    )
                    market_regime_up = _market_regime_ok(regime_bench)
                logger.info(
                    f"[GC Scan] fear_window_open={market_fear_window_open} "
                    f"regime_up={market_regime_up}"
                )
            except Exception as e:  # noqa: BLE001 - fail-open: 데이터 오류 시 통과 가정
                logger.warning(f"[GC Scan] market load failed, fail-open: {e}")
                market_fear_window_open = False
                market_regime_up = True

        # 2. 종목별 기술적 지표 계산

        # MA 기간: 명시 override 우선, 없으면 운영 config (live 경로는 항상 config)
        resolved_short_ma = (
            short_ma_period if short_ma_period is not None else settings.gc_short_ma_period
        )
        resolved_long_ma = (
            long_ma_period if long_ma_period is not None else settings.gc_long_ma_period
        )
        # 조회 창을 장기 MA에서 파생(고정 400일이면 큰 long MA에서 캔들 부족 → 스캔 전멸 방지).
        # 거래일↔캘린더일 환산(거래일≈캘린더×0.69) 여유 계수 1.6, 최소 400일.
        scan_lookback_days = max(400, int((resolved_long_ma + 20) * 1.6))

        async def process_stock(worker_loader, worker_session, stock, worker_cache_stats):
            load_result = await worker_loader.load_ohlcv_with_stats(
                symbol=stock.symbol,
                days=scan_lookback_days,
                interval="1d",
                min_candles=resolved_long_ma + 20,
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

            self._update_cache_stats(worker_cache_stats, load_result)

            dto = self._evaluate_gc_row(
                load_result.df,
                symbol=stock.symbol,
                name=stock.name,
                market=stock.market,
                sector_name=getattr(stock, "sector", None),
                industry_code=getattr(stock, "industry", None),
                industry_name=None,
                market_cap=stock.market_cap,
                screening_score=stock.screening_score,
                short_ma_period=resolved_short_ma,
                long_ma_period=resolved_long_ma,
                stoch_threshold=stoch_threshold,
                gc_only=True,  # candidates 경로는 gc_only 인자를 사용하지 않던 기존 동작 보존
                market_regime_up=market_regime_up,
                market_fear_window_open=market_fear_window_open,
                enable_fear_buy=True,
            )
            if dto is not None:
                await asyncio.sleep(0.05)
            return dto

        results, worker_errors, cache_stats = await self._run_scan_workers(
            stocks, concurrency, process_stock, "[GC Scan]"
        )
        errors.extend(worker_errors)

        # 3. 결과 정렬 (OPTIMAL_BUY > BUY_INTEREST > READY_TO_BUY > WAITING_FOR_PULLBACK > 기타)
        results.sort(
            key=lambda x: (
                GC_SCAN_STATE_ORDER.get(x.gc_state, 99),
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

        logger.info(
            f"[GC Scan] Scanning {len(symbols)} symbols with "
            f"MA{settings.gc_short_ma_period}/MA{settings.gc_long_ma_period}"
        )

        # 시장 레짐(스캔당 1회, fail-open) — GC(추세추종) 진입 게이트. scan_golden_cross_candidates와 일관.
        market_regime_up = True
        if settings.gc_regime_filter_enabled:
            try:
                regime_bench = await get_regime_benchmark_ohlc(
                    session, settings.gc_regime_benchmark, days=500
                )
                market_regime_up = _market_regime_ok(regime_bench)
                logger.info(f"[GC Scan] regime_up={market_regime_up}")
            except Exception as e:  # noqa: BLE001 - fail-open
                logger.warning(f"[GC Scan] regime load failed, fail-open: {e}")
                market_regime_up = True

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
            sector_name = item.get("sector_name") or item.get("sector")
            industry_code = item.get("industry_code") or item.get("industry")
            industry_name = item.get("industry_name")

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
                # OHLCV 데이터 로딩 (장기 MA 계산에 충분한 캔들 확보: long_ma + 20).
                # 조회 창도 long MA에서 파생(큰 long MA에서 고정 400일이면 캔들 부족 방지).
                sym_lookback_days = max(400, int((settings.gc_long_ma_period + 20) * 1.6))
                df = await data_loader.load_ohlcv_dataframe(
                    symbol=symbol,
                    days=sym_lookback_days,
                    interval="1d",
                    min_candles=settings.gc_long_ma_period + 20,
                    force_refresh=force_refresh,
                )

                # 지표추출/필터/상태판정/DTO조립은 candidates 경로와 공유(_evaluate_gc_row).
                # symbols 경로: fear-buy 미적용(enable_fear_buy=False), gc_only 인자 존중.
                dto = self._evaluate_gc_row(
                    df,
                    symbol=symbol,
                    name=name,
                    market=market,
                    sector_name=sector_name,
                    industry_code=industry_code,
                    industry_name=industry_name,
                    market_cap=None,
                    screening_score=None,
                    short_ma_period=settings.gc_short_ma_period,
                    long_ma_period=settings.gc_long_ma_period,
                    stoch_threshold=stoch_threshold,
                    gc_only=gc_only,
                    market_regime_up=market_regime_up,
                    market_fear_window_open=False,
                    enable_fear_buy=False,
                )
                if dto is not None:
                    results.append(dto)
                    # Rate limit 대응
                    await asyncio.sleep(0.05)

            except ValueError as e:
                logger.debug(f"[GC Scan] {symbol}: {e}")
            except Exception as e:
                error_msg = f"{symbol}: {str(e)}"
                logger.warning(f"[GC Scan] Error processing {error_msg}")
                errors.append(error_msg)

        # industry_code → industry_name 매핑 (DB 스캔 경로와 동일)
        industry_codes = {
            r.industry_code for r in results if r.industry_code and not r.industry_name
        }
        if industry_codes:
            try:
                stmt = select(NaverIndustryCodeModel).where(
                    NaverIndustryCodeModel.industry_code.in_(industry_codes)
                )
                mapping_rows = (await session.execute(stmt)).scalars().all()
                code_to_name = {row.industry_code: row.industry_name for row in mapping_rows}
                for r in results:
                    if r.industry_code and not r.industry_name:
                        r.industry_name = code_to_name.get(r.industry_code)
            except Exception as e:
                logger.warning(f"[GC Scan symbols] Failed to attach industry names: {e}")

        # 결과 정렬 (BUY_INTEREST 추가)
        results.sort(key=lambda x: GC_SCAN_STATE_ORDER.get(x.gc_state, 99))

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
            if isinstance(item, BaseException):
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
            fin_order = {"PASS": 0, "TURNAROUND": 1, "FAIL": 2, "ERROR": 3, "PENDING": 4, None: 5}
            return (
                GC_SCAN_STATE_ORDER.get(stock.gc_state, 99),
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
