# -*- coding: utf-8 -*-
"""
OHLCV Repository - 캔들 데이터 캐시 저장소
"""

from datetime import datetime
from typing import Sequence

import pandas as pd
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.ohlcv import OHLCVModel
from src.adapters.database.repositories.base_repository import BaseRepository
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

        기존 데이터는 삭제 후 재삽입 방식으로 처리 (성능 최적화)

        Args:
            symbol: 종목코드
            candles: 캔들 데이터 리스트
            interval: 시간 간격
            source: 데이터 출처

        Returns:
            int: 저장된 캔들 수
        """
        if not candles:
            return 0

        # 날짜 범위 추출
        timestamps = [candle.timestamp for candle in candles]
        start_date = min(timestamps)
        end_date = max(timestamps)

        # 기존 데이터 삭제 (충돌 방지)
        await self.delete_by_date_range(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )

        # 새 데이터 삽입
        candle_dicts = [
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
            for candle in candles
        ]

        await self.create_many(candle_dicts)
        return len(candles)

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
        candles = await self.get_candles_by_date_range(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )

        if not candles:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        data = [
            {
                "timestamp": candle.timestamp,
                "open": float(candle.open),
                "high": float(candle.high),
                "low": float(candle.low),
                "close": float(candle.close),
                "volume": candle.volume,
            }
            for candle in candles
        ]

        df = pd.DataFrame(data)
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
        데이터 가용성 확인

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
        candles = await self.get_candles_by_date_range(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )

        if not candles:
            return {
                "has_data": False,
                "count": 0,
                "earliest": None,
                "latest": None,
                "is_complete": False,
            }

        timestamps = [candle.timestamp for candle in candles]
        earliest = min(timestamps)
        latest = max(timestamps)

        # 타임존 정규화 (DB에서 온 데이터는 timezone-aware, 입력은 naive일 수 있음)
        if earliest.tzinfo is not None:
            earliest = earliest.replace(tzinfo=None)
        if latest.tzinfo is not None:
            latest = latest.replace(tzinfo=None)

        # 전체 기간 커버 여부 판단
        # 완벽한 매치: earliest <= start_date and latest >= end_date
        # 허용 범위: 시작/종료일 ±3일 이내 (주말/공휴일 고려)
        from datetime import timedelta
        start_tolerance = timedelta(days=3)
        end_tolerance = timedelta(days=3)

        start_ok = earliest <= start_date or (earliest - start_date) <= start_tolerance
        end_ok = latest >= end_date or (end_date - latest) <= end_tolerance

        is_complete = start_ok and end_ok

        return {
            "has_data": True,
            "count": len(candles),
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
        availability = await self.check_data_availability(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )

        if not availability["has_data"]:
            # 전체 구간 결측
            return [(start_date, end_date)]

        if availability["is_complete"]:
            # 결측 없음
            return []

        missing_ranges = []

        # 시작 부분 결측 확인
        if availability["earliest"] > start_date:
            missing_ranges.append((start_date, availability["earliest"]))

        # 종료 부분 결측 확인
        if availability["latest"] < end_date:
            missing_ranges.append((availability["latest"], end_date))

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
