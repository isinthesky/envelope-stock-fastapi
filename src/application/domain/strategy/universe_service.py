# -*- coding: utf-8 -*-
"""
Universe Service - 종목 유니버스 갱신

StrategyService.refresh_universe(god-method)에서 분해한 유니버스 갱신 로직.
동작(워커 동시성/세션 사용/스크리닝/카운트)은 원본과 100% 동일하게 유지한다.

세션 계약:
- refresh(session)의 session은 호출측(@transaction)이 소유한다.
- 시드/워커는 원본과 동일하게 별도 세션(AsyncSessionLocal)에서 커밋한다.
"""

import asyncio
import logging
import time
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select

from src.adapters.database.models.stock_universe import MarketType, StockUniverseModel
from src.adapters.database.repositories.stock_universe_repository import (
    StockUniverseRepository,
)
from src.settings.config import settings

TARGET_UNIVERSE_SIZE = 500


class UniverseService:
    """유니버스 갱신 협력자 (refresh_universe 위임 대상)"""

    async def refresh(self, session) -> dict:
        """유니버스 갱신 (B-1)

        - B-1: 기존 stock_universe에 존재하는 종목들을 대상으로
          (1) 현재가/거래량/시총 등 기본 데이터를 갱신하고
          (2) 스크리닝 재적용(passed_* / screening_score)까지 수행합니다.

        B-2는 "대상 종목 수 확대"로 대체: 상위 500개까지 갱신/스캔 대상으로 사용.
        """
        universe_repo = StockUniverseRepository(session)

        seeded = 0
        universe_size_before = await self._count_active_universe(session, rollback_first=False)

        if settings.etf_universe_enabled:
            seeded = await self._seed_etf(session)
        elif universe_size_before < TARGET_UNIVERSE_SIZE:
            seeded = await self._seed_from_krx(session, universe_size_before)

        # 현재는 "활성 + 제외 아님" 종목 중 상위 500개를 갱신 대상으로 사용
        target_stocks = await universe_repo.get_active_stocks(limit=500, session=session)
        if not target_stocks:
            return {
                "success": False,
                "target": 0,
                "updated": 0,
                "screened": 0,
                "errors": ["No active stocks found in universe"],
                "refreshed_at": datetime.now().isoformat(),
            }

        run = await self._run_refresh_workers(target_stocks, seeded)

        universe_size_after = await self._recount(session)

        return {
            "success": (not run["timed_out"]),
            "message": run["message"],
            "timed_out": run["timed_out"],
            "target": len(target_stocks),
            "updated": run["total_updated"],
            "screened": run["total_screened"],
            "seeded": seeded,
            "universe_size_before": universe_size_before,
            "universe_size_after": universe_size_after,
            "concurrency": run["concurrency"],
            "error_count": run["total_error_count"],
            "errors_truncated": run["total_error_count"] > len(run["errors"]),
            "errors": run["errors"],
            "warning_counts": run["warning_counts"],
            "refreshed_at": datetime.now().isoformat(),
        }

    async def _count_active_universe(self, session, *, rollback_first: bool) -> int:
        """활성(+미제외) 유니버스 크기 count. rollback_first면 트랜잭션 스냅샷 갱신."""
        if rollback_first and session.in_transaction():
            await session.rollback()
        count_res = await session.execute(
            select(func.count())
            .select_from(StockUniverseModel)
            .where(
                StockUniverseModel.is_active == True,
                StockUniverseModel.is_excluded == False,
            )
        )
        return int(count_res.scalar() or 0)

    async def _recount(self, session) -> int:
        """실제 활성 유니버스 크기를 재집계(ETF 모드는 deactivate_all 후 ETF만 활성화하므로
        before+seeded 산식이 부정확 → 커밋된 활성 행을 직접 count)"""
        return await self._count_active_universe(session, rollback_first=True)

    async def _seed_etf(self, session) -> int:
        """ETF 유니버스 모드: 개별주 전량 비활성화 후 지정 ETF만 시드(market=ETF).

        이후 get_active_stocks/스캔 경로가 ETF-only를 반환 → 개별주 매수 알림 자동 소멸.
        """
        from src.adapters.database.connection import AsyncSessionLocal
        from src.adapters.external.naver.stock_client import get_naver_stock_client

        _etf_logger = logging.getLogger(__name__)
        etf_symbols = [s.strip() for s in settings.etf_universe_symbols if s and s.strip()]
        # ETF 실제명(예: "KODEX 200")은 네이버 통합 API의 stockName에서만 얻는다.
        # (KIS 현재가는 ETF에 일반명 "ETF(실물복제/수익증권)"만 반환)
        naver_client_seed = get_naver_stock_client()
        name_timeout = 8.0
        name_phase_timeout = 150.0
        name_concurrency = 8

        if not etf_symbols:
            # ETF 모드인데 심볼 목록이 비어 있으면 설정 오류. 그래도 개별주는 반드시
            # 비활성화(개별주 알림 방지). 결과는 빈 유니버스(알림 없음) = fail-safe.
            _etf_logger.error(
                "[universe.refresh] ETF_UNIVERSE_ENABLED이지만 etf_universe_symbols가 "
                "비어 있음 → 개별주 전량 비활성화(빈 ETF 유니버스). 설정을 확인하세요."
            )

        # 기존 행의 이름/제외/거래가능 상태를 보존한다
        # (이름: 코드로 덮어쓰기 방지 / 제외·거래가능: 운영자 수동 제외 유지)
        existing_rows_res = await session.execute(
            select(
                StockUniverseModel.symbol,
                StockUniverseModel.name,
                StockUniverseModel.is_excluded,
                StockUniverseModel.is_tradable,
            ).where(StockUniverseModel.symbol.in_(etf_symbols))
        )
        existing_meta = {
            row[0]: {"name": row[1], "is_excluded": row[2], "is_tradable": row[3]}
            for row in existing_rows_res.all()
        }
        existing_names = {s: m["name"] for s, m in existing_meta.items()}

        name_sem = asyncio.Semaphore(name_concurrency)

        async def _resolve_etf_name(sym: str) -> tuple[str, bool]:
            """(name, fetched_ok). 실패 시 기존명 유지, 없으면 심볼."""
            async with name_sem:
                try:
                    stock_name = await asyncio.wait_for(
                        naver_client_seed.get_stock_name(sym), timeout=name_timeout
                    )
                    if stock_name:
                        return stock_name, True
                except asyncio.CancelledError:
                    raise  # 외부 취소는 전파(중단 시 이후 DB 변경 방지)
                except Exception:
                    pass
            return (existing_names.get(sym) or sym), False

        # bounded 동시성 + 단계 전체 timeout(전체 refresh timeout 밖 장기 지연 방지).
        # CancelledError(외부 취소/셧다운)는 삼키지 않고 전파한다. timeout만 폴백.
        try:
            resolved = await asyncio.wait_for(
                asyncio.gather(*[_resolve_etf_name(s) for s in etf_symbols]),
                timeout=name_phase_timeout,
            )
        except asyncio.TimeoutError:
            resolved = [((existing_names.get(s) or s), False) for s in etf_symbols]
            _etf_logger.warning(
                "[universe.refresh] ETF name-fetch phase timed out "
                f"(>{name_phase_timeout}s); fell back to existing/symbol names"
            )

        name_fetch_failures = sum(1 for _n, ok in resolved if not ok)
        if name_fetch_failures:
            _etf_logger.warning(
                f"[universe.refresh] ETF name fetch: {name_fetch_failures}/"
                f"{len(etf_symbols)} kept existing/symbol name (naver miss)"
            )

        etf_rows = [
            {
                "symbol": sym,
                "name": name,
                "market": MarketType.ETF.value,
                "is_active": True,
                # 기존 행의 제외/거래가능 상태 보존(운영자 수동 제외가 매 refresh마다 부활하지 않게).
                # 신규 행만 기본값(미제외/거래가능).
                "is_excluded": existing_meta.get(sym, {}).get("is_excluded", False),
                "is_tradable": existing_meta.get(sym, {}).get("is_tradable", True),
            }
            for sym, (name, _ok) in zip(etf_symbols, resolved)
        ]

        # ETF 모드는 항상 개별주를 비활성화한다(etf_rows가 비어도 fail-safe).
        # seed는 별도 세션에서 커밋해 worker/현재 세션에서도 즉시 보이게 함.
        async with AsyncSessionLocal() as seed_session:
            seed_repo = StockUniverseRepository(seed_session)
            await seed_repo.deactivate_all(session=seed_session)
            if etf_rows:
                await seed_repo.bulk_upsert(etf_rows, session=seed_session)
            await seed_session.commit()
        seeded = len(etf_rows)
        await session.rollback()
        return seeded

    async def _seed_from_krx(self, session, universe_size_before: int) -> int:
        """(B-2) 유니버스가 500 미만이면 KRX KIND 상장 목록에서 최소 필드만 채워 확장.

        symbol/name/market만 채우고, 이후 갱신 로직에서 시총/거래량/스크리닝을 업데이트.
        """
        from src.adapters.database.connection import AsyncSessionLocal
        from src.adapters.external.krx.kind_client import fetch_kind_corp_list

        # 기존 심볼 set
        sym_res = await session.execute(select(StockUniverseModel.symbol))
        existing_symbols = set(sym_res.scalars().all())

        need = TARGET_UNIVERSE_SIZE - universe_size_before
        rows: list[dict] = []

        # KOSPI 먼저 채우고, 부족하면 KOSDAQ로 채움
        for symbol, name in await fetch_kind_corp_list("stockMkt"):
            if symbol in existing_symbols:
                continue
            rows.append({"symbol": symbol, "name": name, "market": MarketType.KOSPI.value})
            existing_symbols.add(symbol)
            if len(rows) >= need:
                break

        if len(rows) < need:
            for symbol, name in await fetch_kind_corp_list("kosdaqMkt"):
                if symbol in existing_symbols:
                    continue

                rows.append({"symbol": symbol, "name": name, "market": MarketType.KOSDAQ.value})
                existing_symbols.add(symbol)
                if len(rows) >= need:
                    break

        seeded = 0
        if rows:
            # seed는 별도 세션에서 커밋해서 worker 세션에서도 즉시 보이게 함
            async with AsyncSessionLocal() as seed_session:
                seed_repo = StockUniverseRepository(seed_session)
                await seed_repo.create_many(rows, session=seed_session)
                await seed_session.commit()
            seeded = len(rows)

            # 현재 세션에서 이후 조회가 최신 커밋을 볼 수 있도록 트랜잭션 스냅샷을 갱신
            # (refresh_universe는 이 시점에 쓰기 작업이 없으므로 rollback은 안전)
            await session.rollback()
        return seeded

    async def _run_refresh_workers(self, target_stocks, seeded: int) -> dict:
        """대상 종목에 대해 현재가/시총/OHLCV 갱신 + 스크리닝 재적용을 워커 동시성으로 실행."""
        from src.adapters.cache.redis_client import get_redis_client
        from src.adapters.database.connection import AsyncSessionLocal
        from src.adapters.external.kis_api.client import get_kis_client
        from src.adapters.external.naver.stock_client import get_naver_stock_client
        from src.application.domain.market_data.service import MarketDataService
        from src.application.domain.strategy.ohlcv_data_loader import OHLCVDataLoader
        from src.application.domain.strategy.stock_screener import StockScreener

        kis_client = get_kis_client()
        redis_client = await get_redis_client()
        market_data_service = MarketDataService(kis_client, redis_client)
        naver_client = get_naver_stock_client()

        logger = logging.getLogger(__name__)
        started_at = time.monotonic()

        # timeout은 대기 무한을 피하기 위한 운영 안전장치
        kis_timeout = float(getattr(settings, "kis_api_timeout", 10))
        naver_timeout = 10.0
        ohlcv_timeout = max(20.0, kis_timeout * 3)

        MAX_ERRORS = int(getattr(settings, "universe_refresh_error_list_limit", 50))
        warn_budget = int(getattr(settings, "universe_refresh_warn_budget", 50))
        overall_timeout = float(getattr(settings, "universe_refresh_timeout_seconds", 300))

        warning_counts = {"price": 0, "naver": 0, "ohlcv": 0}
        warning_suppressed = {"price": False, "naver": False, "ohlcv": False}

        def warn(category: str, msg: str) -> None:
            warning_counts[category] = warning_counts.get(category, 0) + 1
            if warn_budget <= 0:
                return
            if warning_counts[category] <= warn_budget:
                logger.warning(msg)
                return
            if not warning_suppressed.get(category, False):
                warning_suppressed[category] = True
                logger.warning(
                    f"[universe.refresh] {category} warnings suppressed (>{warn_budget})"
                )

        concurrency = max(1, min(settings.scan_concurrency_limit, 20))
        logger.info(
            f"[universe.refresh] start: target={len(target_stocks)} seeded={seeded} concurrency={concurrency}"
        )

        work_queue: asyncio.Queue[tuple[int, object]] = asyncio.Queue()
        for idx, stock in enumerate(target_stocks):
            work_queue.put_nowait((idx, stock))

        async def worker() -> tuple[int, int, int, list[str]]:
            updated = 0
            screened = 0
            error_count = 0
            errors: list[str] = []

            async with AsyncSessionLocal() as worker_session:
                screener = StockScreener(worker_session, kis_client)
                data_loader = OHLCVDataLoader(worker_session)

                while True:
                    try:
                        _idx, stock = work_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    symbol = getattr(stock, "symbol", None)
                    if not symbol:
                        work_queue.task_done()
                        continue

                    try:
                        # 1) 현재가/누적거래량
                        price = None
                        try:
                            price = await asyncio.wait_for(
                                market_data_service.get_current_price(symbol, use_cache=True),
                                timeout=kis_timeout,
                            )
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            warn("price", f"[universe.refresh] price fetch failed: {symbol}: {e}")

                        # 2) 시총/종목명 (네이버) — 실패해도 진행
                        fin = None
                        try:
                            fin = await asyncio.wait_for(
                                naver_client.get_stock_financial_data(symbol),
                                timeout=naver_timeout,
                            )
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            warn("naver", f"[universe.refresh] naver fetch failed: {symbol}: {e}")

                        # 3) OHLCV 캐시 최신화 + 20일 평균 거래량 계산
                        load = None
                        try:
                            load = await asyncio.wait_for(
                                data_loader.load_ohlcv_with_stats(
                                    symbol=symbol,
                                    days=60,
                                    interval="1d",
                                    min_candles=30,
                                    cache_freshness_days=3,
                                    force_refresh=False,
                                ),
                                timeout=ohlcv_timeout,
                            )
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            warn("ohlcv", f"[universe.refresh] ohlcv load failed: {symbol}: {e}")
                        df = load.df if load is not None else None

                        avg_vol_20d = None
                        if df is not None and not df.empty and len(df) >= 20:
                            avg_vol_20d = int(df["volume"].tail(20).mean())

                        # 4) stock_universe 기본 필드 업데이트
                        await screener.update_stock_data(
                            symbol=symbol,
                            name=(fin.name if fin and fin.name else getattr(stock, "name", None)),
                            market=getattr(stock, "market", None),
                            sector=getattr(stock, "sector", None),
                            industry=(
                                fin.industry_code
                                if fin and fin.industry_code
                                else getattr(stock, "industry", None)
                            ),
                            market_cap=(
                                Decimal(fin.market_cap)
                                if fin and fin.market_cap
                                else getattr(stock, "market_cap", None)
                            ),
                            avg_volume_20d=(
                                Decimal(avg_vol_20d)
                                if avg_vol_20d is not None
                                else getattr(stock, "avg_volume_20d", None)
                            ),
                            current_price=(
                                price.current_price
                                if price
                                else getattr(stock, "current_price", None)
                            ),
                        )
                        updated += 1

                        # 5) 스크리닝 재적용
                        passed = await screener.apply_screening(symbol)
                        if passed:
                            screened += 1

                        # commit (OHLCV 캐시 + stock_universe 업데이트 반영)
                        await worker_session.commit()

                    except asyncio.CancelledError:
                        await worker_session.rollback()
                        raise

                    except Exception as e:
                        await worker_session.rollback()
                        error_count += 1
                        logger.exception(f"[universe.refresh] worker failed: {symbol}")
                        if len(errors) < MAX_ERRORS:
                            errors.append(f"{symbol}: {type(e).__name__}: {e}")
                    finally:
                        work_queue.task_done()

            return updated, screened, error_count, errors

        workers = [asyncio.create_task(worker()) for _ in range(concurrency)]

        timed_out = False
        message = None
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*workers, return_exceptions=True),
                timeout=overall_timeout,
            )
        except asyncio.TimeoutError:
            timed_out = True
            message = f"Global timeout after {overall_timeout}s"
            for t in workers:
                t.cancel()
            results = await asyncio.gather(*workers, return_exceptions=True)

        total_updated = 0
        total_screened = 0
        total_error_count = 0
        errors: list[str] = []
        for item in results:
            if isinstance(item, BaseException):
                total_error_count += 1
                logger.error("[universe.refresh] worker task crashed", exc_info=item)
                if len(errors) < MAX_ERRORS:
                    errors.append(str(item))
                continue
            u, s, ec, e = item
            total_updated += u
            total_screened += s
            total_error_count += ec
            if len(errors) < MAX_ERRORS:
                errors.extend(e[: max(0, MAX_ERRORS - len(errors))])

        elapsed = time.monotonic() - started_at
        logger.info(
            f"[universe.refresh] done: target={len(target_stocks)} updated={total_updated} screened={total_screened} errors={total_error_count} warnings={warning_counts} timed_out={timed_out} elapsed={elapsed:.1f}s"
        )

        return {
            "total_updated": total_updated,
            "total_screened": total_screened,
            "total_error_count": total_error_count,
            "errors": errors,
            "warning_counts": warning_counts,
            "timed_out": timed_out,
            "message": message,
            "concurrency": concurrency,
        }
