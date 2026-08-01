# -*- coding: utf-8 -*-
"""
OHLCV Repository - 캔들 데이터 캐시 저장소
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Sequence

import pandas as pd
from sqlalchemy import and_, delete, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.ohlcv import OHLCVModel
from src.adapters.database.repositories.base_repository import BaseRepository

if TYPE_CHECKING:
    from src.application.domain.market_data.dto import CandleDTO


class OHLCVRepository(BaseRepository[OHLCVModel]):
    """OHLCV 캔들 데이터 Repository"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(OHLCVModel, session)

    # ==================== Candle 데이터 저장 ====================

    async def save_candle(
        self,
        symbol: str,
        candle: CandleDTO,
        interval: str = "1d",
        source: str = "kis",
    ) -> OHLCVModel:
        """
        단일 캔들 데이터 저장 (Upsert)

        Args:
            symbol: 종목코드
            candle: 캔들 데이터
            interval: 시간 간격
            source: 데이터 출처

        Returns:
            OHLCVModel: 저장된 캔들 모델
        """
        # 기존 데이터 확인
        existing = await self.get_one(
            symbol=symbol,
            timestamp=candle.timestamp,
            interval=interval,
        )

        if existing:
            # 업데이트
            existing.open = candle.open
            existing.high = candle.high
            existing.low = candle.low
            existing.close = candle.close
            existing.volume = candle.volume
            existing.source = source
            await self.session.flush()
            await self.session.refresh(existing)
            return existing
        else:
            # 신규 생성
            return await self.create(
                symbol=symbol,
                timestamp=candle.timestamp,
                interval=interval,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
                source=source,
            )

    async def save_candles_bulk(
        self,
        symbol: str,
        candles: list[CandleDTO],
        interval: str = "1d",
        source: str = "kis",
    ) -> int:
        """
        다중 캔들 데이터 일괄 저장 (Bulk Upsert)

        목표: I/O 최소화.
        - Postgres: ON CONFLICT(symbol, timestamp, interval) DO UPDATE 로 업서트
          (기존 delete+insert 제거 → 대량 DELETE/INSERT로 인한 write amplification 방지)
        - 그 외 DB: 지원하지 않음

        Returns:
            int: 처리된 캔들 수
        """
        if not candles:
            return 0

        # Postgres UPSERT only
        bind = getattr(self.session, "bind", None)
        if bind is None:
            try:
                bind = self.session.get_bind()
            except Exception:
                bind = None
        if bind is None:
            sync_session = getattr(self.session, "sync_session", None)
            bind = getattr(sync_session, "bind", None) if sync_session else None

        dialect = getattr(bind, "dialect", None)
        if dialect is None and hasattr(bind, "sync_engine"):
            dialect = getattr(bind.sync_engine, "dialect", None)

        dialect_name = getattr(dialect, "name", None)
        if dialect_name != "postgresql":
            detected = dialect_name or "unknown"
            raise NotImplementedError(
                "save_candles_bulk supports PostgreSQL only. "
                f"Detected dialect: {detected}. "
                "Configure AsyncSessionLocal with a PostgreSQL engine."
            )

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        # 방어적 dedup: ON CONFLICT DO UPDATE는 한 INSERT 문에 동일 (symbol,timestamp,interval)이
        # 두 번 들어오면 CardinalityViolation("cannot affect row a second time")으로 실패한다.
        # symbol/interval은 호출당 상수이므로 timestamp 기준 dedup(최신 우선). 어떤 호출자가
        # 중복을 넘겨도 심볼 전체 저장이 통째로 실패(saved=0)하는 것을 방지.
        deduped: dict = {}
        for candle in candles:
            deduped[candle.timestamp] = candle
        rows = [
            {
                "symbol": symbol,
                "timestamp": candle.timestamp,
                "interval": interval,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "source": source,
            }
            for candle in deduped.values()
        ]

        chunk_size = 1000
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i : i + chunk_size]
            stmt = pg_insert(self.model).values(chunk)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_ohlcv_symbol_timestamp_interval",
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "source": stmt.excluded.source,
                },
            )
            await self.session.execute(stmt)

        return len(rows)

    # ==================== Candle 데이터 조회 ====================

    async def get_candles_by_date_range(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> Sequence[OHLCVModel]:
        """
        날짜 범위로 캔들 데이터 조회

        Args:
            symbol: 종목코드
            start_date: 시작일
            end_date: 종료일
            interval: 시간 간격

        Returns:
            Sequence[OHLCVModel]: 캔들 데이터 리스트 (시간순 정렬)
        """
        stmt = (
            select(self.model)
            .where(
                and_(
                    self.model.symbol == symbol,
                    self.model.interval == interval,
                    self.model.timestamp >= start_date,
                    self.model.timestamp <= end_date,
                )
            )
            .order_by(self.model.timestamp)
        )

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_latest_candle(
        self,
        symbol: str,
        interval: str = "1d",
    ) -> OHLCVModel | None:
        """
        최신 캔들 데이터 조회

        Args:
            symbol: 종목코드
            interval: 시간 간격

        Returns:
            OHLCVModel | None: 최신 캔들 또는 None
        """
        stmt = (
            select(self.model)
            .where(
                and_(
                    self.model.symbol == symbol,
                    self.model.interval == interval,
                )
            )
            .order_by(self.model.timestamp.desc())
            .limit(1)
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_candles_to_dataframe(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        날짜 범위 캔들 데이터를 DataFrame으로 변환

        Args:
            symbol: 종목코드
            start_date: 시작일
            end_date: 종료일
            interval: 시간 간격

        Returns:
            pd.DataFrame: OHLCV 데이터프레임
        """
        # I/O 절감: ORM 모델 전체 로드 대신 필요한 컬럼만 SELECT
        stmt = (
            select(
                self.model.timestamp,
                self.model.open,
                self.model.high,
                self.model.low,
                self.model.close,
                self.model.volume,
            )
            .where(
                and_(
                    self.model.symbol == symbol,
                    self.model.interval == interval,
                    self.model.timestamp >= start_date,
                    self.model.timestamp <= end_date,
                )
            )
            .order_by(self.model.timestamp)
        )

        result = await self.session.execute(stmt)
        rows = result.all()
        if not rows:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(
            [
                {
                    "timestamp": r[0],
                    "open": float(r[1]),
                    "high": float(r[2]),
                    "low": float(r[3]),
                    "close": float(r[4]),
                    "volume": int(r[5]),
                }
                for r in rows
            ]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df

    async def get_recent_candles_to_dataframe(
        self,
        symbol: str,
        end_date: datetime,
        limit: int,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        최신 N개 캔들 데이터를 DataFrame으로 변환 (I/O 절감용)

        스캔/지표 계산은 과거 전체 기간이 아니라 "최신 구간"만 필요하므로,
        날짜 range 전체를 읽지 않고 LIMIT 기반으로 필요한 만큼만 가져옵니다.

        Returns:
            pd.DataFrame: OHLCV 데이터프레임 (timestamp ASC 정렬)
        """
        if limit <= 0:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        stmt = (
            select(
                self.model.timestamp,
                self.model.open,
                self.model.high,
                self.model.low,
                self.model.close,
                self.model.volume,
            )
            .where(
                and_(
                    self.model.symbol == symbol,
                    self.model.interval == interval,
                    self.model.timestamp <= end_date,
                )
            )
            .order_by(self.model.timestamp.desc())
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        rows = result.all()
        if not rows:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        # DESC로 가져왔으니 다시 ASC로
        rows = list(reversed(rows))
        df = pd.DataFrame(
            [
                {
                    "timestamp": r[0],
                    "open": float(r[1]),
                    "high": float(r[2]),
                    "low": float(r[3]),
                    "close": float(r[4]),
                    "volume": int(r[5]),
                }
                for r in rows
            ]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df

    # ==================== 데이터 가용성 확인 ====================

    async def check_data_availability(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> dict:
        """
        데이터 가용성 확인 (경량 집계 쿼리 사용)

        전체 캔들을 로드하지 않고 집계 함수만 사용하여
        count, min, max 값만 조회합니다.

        Args:
            symbol: 종목코드
            start_date: 시작일
            end_date: 종료일
            interval: 시간 간격

        Returns:
            dict: 가용성 정보
                - has_data: 데이터 존재 여부
                - count: 캔들 개수
                - earliest: 가장 빠른 날짜
                - latest: 가장 늦은 날짜
                - is_complete: 전체 기간 커버 여부
        """
        from datetime import timedelta, timezone as tz

        # 집계 쿼리로 count, min, max만 조회 (전체 로드 방지)
        stmt = (
            select(
                func.count().label("count"),
                func.min(self.model.timestamp).label("earliest"),
                func.max(self.model.timestamp).label("latest"),
            )
            .where(
                and_(
                    self.model.symbol == symbol,
                    self.model.interval == interval,
                    self.model.timestamp >= start_date,
                    self.model.timestamp <= end_date,
                )
            )
        )

        result = await self.session.execute(stmt)
        row = result.one()

        count = row.count or 0
        earliest = row.earliest
        latest = row.latest

        if count == 0 or earliest is None or latest is None:
            return {
                "has_data": False,
                "count": 0,
                "earliest": None,
                "latest": None,
                "is_complete": False,
            }

        def to_utc(dt: datetime) -> datetime:
            """datetime을 UTC로 정규화"""
            if dt.tzinfo is None:
                return dt.replace(tzinfo=tz.utc)
            return dt.astimezone(tz.utc)

        earliest = to_utc(earliest)
        latest = to_utc(latest)
        start_date_utc = to_utc(start_date)
        end_date_utc = to_utc(end_date)

        # 전체 기간 커버 여부 판단
        # 완벽한 매치: earliest <= start_date and latest >= end_date
        # 허용 범위: 시작/종료일 ±3일 이내 (주말/공휴일 고려)
        start_tolerance = timedelta(days=3)
        end_tolerance = timedelta(days=3)

        start_ok = earliest <= start_date_utc or (earliest - start_date_utc) <= start_tolerance
        end_ok = latest >= end_date_utc or (end_date_utc - latest) <= end_tolerance

        is_complete = start_ok and end_ok

        return {
            "has_data": True,
            "count": count,
            "earliest": earliest,
            "latest": latest,
            "is_complete": is_complete,
        }

    async def get_missing_date_ranges(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> list[tuple[datetime, datetime]]:
        """
        결측 날짜 범위 탐지

        Args:
            symbol: 종목코드
            start_date: 시작일
            end_date: 종료일
            interval: 시간 간격

        Returns:
            list[tuple[datetime, datetime]]: 결측 구간 리스트
        """
        from datetime import timezone as tz

        # 타임존 정규화 (tz-aware vs tz-naive 비교 오류 방지)
        def to_utc(dt: datetime) -> datetime:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=tz.utc)
            return dt.astimezone(tz.utc)

        start_date_utc = to_utc(start_date)
        end_date_utc = to_utc(end_date)

        availability = await self.check_data_availability(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )

        if not availability["has_data"]:
            # 전체 구간 결측
            return [(start_date_utc, end_date_utc)]

        if availability["is_complete"]:
            # 결측 없음
            return []

        missing_ranges = []

        # 시작 부분 결측 확인 (둘 다 UTC-aware)
        if availability["earliest"] > start_date_utc:
            missing_ranges.append((start_date_utc, availability["earliest"]))

        # 종료 부분 결측 확인 (둘 다 UTC-aware)
        if availability["latest"] < end_date_utc:
            missing_ranges.append((availability["latest"], end_date_utc))

        return missing_ranges

    # ==================== 데이터 삭제 ====================

    async def delete_by_date_range(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> int:
        """
        날짜 범위로 캔들 데이터 삭제

        Args:
            symbol: 종목코드
            start_date: 시작일
            end_date: 종료일
            interval: 시간 간격

        Returns:
            int: 삭제된 레코드 수
        """
        stmt = delete(self.model).where(
            and_(
                self.model.symbol == symbol,
                self.model.interval == interval,
                self.model.timestamp >= start_date,
                self.model.timestamp <= end_date,
            )
        )

        result = await self.session.execute(stmt)
        return result.rowcount

    async def delete_old_data(
        self,
        symbol: str,
        before_date: datetime,
        interval: str = "1d",
    ) -> int:
        """
        특정 날짜 이전의 오래된 데이터 삭제

        Args:
            symbol: 종목코드
            before_date: 기준 날짜
            interval: 시간 간격

        Returns:
            int: 삭제된 레코드 수
        """
        stmt = delete(self.model).where(
            and_(
                self.model.symbol == symbol,
                self.model.interval == interval,
                self.model.timestamp < before_date,
            )
        )

        result = await self.session.execute(stmt)
        return result.rowcount

    # ==================== 통계 ====================

    async def get_symbol_stats(self, symbol: str, interval: str = "1d") -> dict:
        """
        종목 데이터 통계

        Args:
            symbol: 종목코드
            interval: 시간 간격

        Returns:
            dict: 통계 정보
        """
        candles = await self.get_many(symbol=symbol, interval=interval, limit=10000)

        if not candles:
            return {
                "total_candles": 0,
                "earliest_date": None,
                "latest_date": None,
                "date_range_days": 0,
            }

        timestamps = [candle.timestamp for candle in candles]
        earliest = min(timestamps)
        latest = max(timestamps)
        date_range = (latest - earliest).days

        return {
            "total_candles": len(candles),
            "earliest_date": earliest,
            "latest_date": latest,
            "date_range_days": date_range,
        }

    # ==================== 캐시 관리용 확장 메서드 ====================

    async def get_all_symbols(self, interval: str = "1d") -> list[str]:
        """
        캐시된 모든 종목 코드 목록 조회

        Args:
            interval: 캔들 간격

        Returns:
            list[str]: 종목 코드 목록
        """
        stmt = (
            select(distinct(self.model.symbol))
            .where(self.model.interval == interval)
            .order_by(self.model.symbol)
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_intervals(self) -> list[str]:
        """
        캐시된 모든 간격 목록 조회

        Returns:
            list[str]: 간격 목록
        """
        stmt = select(distinct(self.model.interval)).order_by(self.model.interval)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_symbols_with_stale_data(
        self,
        freshness_days: int = 7,
        interval: str = "1d",
    ) -> list[dict]:
        """
        오래된 데이터 보유 종목 목록 조회

        Args:
            freshness_days: 신선도 기준 (일)
            interval: 캔들 간격

        Returns:
            list[dict]: [{"symbol": str, "latest_date": datetime}]
        """
        from datetime import timedelta

        threshold_date = datetime.now(timezone.utc) - timedelta(days=freshness_days)

        # 종목별 최신 날짜를 서브쿼리로 조회
        subquery = (
            select(
                self.model.symbol,
                func.max(self.model.timestamp).label("latest_date"),
            )
            .where(self.model.interval == interval)
            .group_by(self.model.symbol)
        ).subquery()

        # 최신 날짜가 기준일보다 오래된 종목 필터
        stmt = (
            select(subquery.c.symbol, subquery.c.latest_date)
            .where(subquery.c.latest_date < threshold_date)
            .order_by(subquery.c.latest_date)
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        return [
            {"symbol": row.symbol, "latest_date": row.latest_date}
            for row in rows
        ]

    async def get_cache_summary(self) -> dict:
        """
        전체 캐시 요약 통계 조회

        Returns:
            dict: {
                "total_symbols": int,
                "total_candles": int,
                "oldest_date": datetime | None,
                "newest_date": datetime | None,
                "intervals": list[str],
                "symbols_by_interval": dict[str, int]
            }
        """
        # 전체 캔들 수
        count_stmt = select(func.count()).select_from(self.model)
        count_result = await self.session.execute(count_stmt)
        total_candles = count_result.scalar() or 0

        if total_candles == 0:
            return {
                "total_symbols": 0,
                "total_candles": 0,
                "oldest_date": None,
                "newest_date": None,
                "intervals": [],
                "symbols_by_interval": {},
            }

        # 전체 종목 수
        symbols_stmt = select(func.count(distinct(self.model.symbol)))
        symbols_result = await self.session.execute(symbols_stmt)
        total_symbols = symbols_result.scalar() or 0

        # 가장 오래된/최신 날짜
        dates_stmt = select(
            func.min(self.model.timestamp).label("oldest"),
            func.max(self.model.timestamp).label("newest"),
        )
        dates_result = await self.session.execute(dates_stmt)
        dates_row = dates_result.one()

        # 간격 목록
        intervals = await self.get_all_intervals()

        # 간격별 종목 수
        interval_counts_stmt = (
            select(
                self.model.interval,
                func.count(distinct(self.model.symbol)).label("count"),
            )
            .group_by(self.model.interval)
        )
        interval_counts_result = await self.session.execute(interval_counts_stmt)
        symbols_by_interval = {
            row.interval: row.count for row in interval_counts_result.all()
        }

        return {
            "total_symbols": total_symbols,
            "total_candles": total_candles,
            "oldest_date": dates_row.oldest,
            "newest_date": dates_row.newest,
            "intervals": intervals,
            "symbols_by_interval": symbols_by_interval,
        }

    async def bulk_delete_old_data(
        self,
        before_date: datetime,
        batch_size: int = 1000,
        interval: str = "1d",
    ) -> int:
        """
        배치 단위 오래된 데이터 삭제 (전체 종목)

        Args:
            before_date: 기준 날짜
            batch_size: 배치 크기

        Returns:
            int: 삭제된 총 레코드 수
        """
        total_deleted = 0

        while True:
            # 배치 단위로 삭제할 ID 조회
            ids_stmt = (
                select(self.model.id)
                .where(
                    and_(
                        self.model.interval == interval,
                        self.model.timestamp < before_date,
                    )
                )
                .limit(batch_size)
            )
            ids_result = await self.session.execute(ids_stmt)
            ids_to_delete = list(ids_result.scalars().all())

            if not ids_to_delete:
                break

            # ID 기반 삭제
            delete_stmt = delete(self.model).where(self.model.id.in_(ids_to_delete))
            result = await self.session.execute(delete_stmt)
            await self.session.flush()

            total_deleted += result.rowcount

        return total_deleted

    async def get_symbols_latest_dates(
        self,
        interval: str = "1d",
    ) -> dict[str, datetime]:
        """
        모든 종목의 최신 데이터 날짜 조회

        Args:
            interval: 캔들 간격

        Returns:
            dict[str, datetime]: {symbol: latest_date}
        """
        stmt = (
            select(
                self.model.symbol,
                func.max(self.model.timestamp).label("latest_date"),
            )
            .where(self.model.interval == interval)
            .group_by(self.model.symbol)
        )

        result = await self.session.execute(stmt)
        return {row.symbol: row.latest_date for row in result.all()}

    async def count_by_symbol(
        self,
        symbol: str,
        interval: str = "1d",
    ) -> int:
        """
        특정 종목의 캔들 수 조회

        Args:
            symbol: 종목코드
            interval: 캔들 간격

        Returns:
            int: 캔들 수
        """
        stmt = (
            select(func.count())
            .select_from(self.model)
            .where(
                and_(
                    self.model.symbol == symbol,
                    self.model.interval == interval,
                )
            )
        )

        result = await self.session.execute(stmt)
        return result.scalar() or 0
