# -*- coding: utf-8 -*-
"""
Backtest Data Loader - 백테스팅 데이터 수집 및 전처리

과거 차트 데이터 수집, 검증, 전처리를 담당합니다.
"""

import asyncio
from datetime import datetime, timedelta
import pandas as pd

from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.repositories.ohlcv_repository import OHLCVRepository
from src.application.common.exceptions import BacktestDataError
from src.application.domain.market_data.dto import CandleDTO
from src.application.domain.market_data.service import MarketDataService


class BacktestDataLoader:
    """
    백테스팅 데이터 로더

    과거 차트 데이터를 수집하고 백테스팅에 적합한 형태로 전처리합니다.
    DB 캐싱을 통해 반복 API 호출을 최소화합니다.
    """

    def __init__(
        self,
        market_data_service: MarketDataService,
        db_session: AsyncSession | None = None,
    ):
        """
        Args:
            market_data_service: 시세 데이터 서비스
            db_session: DB 세션 (캐싱 사용 시 필수)
        """
        self.market_data_service = market_data_service
        self.db_session = db_session
        self.ohlcv_repo = OHLCVRepository(db_session) if db_session else None

    async def load_ohlcv_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        chunk_days: int = 90,
        use_cache: bool = True,
    ) -> tuple[pd.DataFrame, datetime, datetime]:
        """
        OHLCV 데이터 로드 (DB 캐시 우선)

        Args:
            symbol: 종목코드
            start_date: 시작일
            end_date: 종료일
            chunk_days: 한 번에 조회할 기간 (일)
            use_cache: 캐시 사용 여부

        Returns:
            tuple:
                - pd.DataFrame: OHLCV 데이터 (컬럼: timestamp, open, high, low, close, volume)
                - datetime: 실제 데이터 시작일
                - datetime: 실제 데이터 종료일

        Raises:
            BacktestDataError: 데이터 로드 실패
        """
        try:
            # ==================== 1. DB 캐시 확인 ====================
            if use_cache and self.ohlcv_repo:
                cached_data = await self._load_from_cache(symbol, start_date, end_date)
                if cached_data is not None:
                    df, actual_start, actual_end = cached_data
                    print(f"✅ 캐시에서 데이터 로드: {len(df)}건 (DB)")
                    return df, actual_start, actual_end

            # ==================== 2. API에서 수집 ====================
            all_candles = await self._collect_long_period(
                symbol, start_date, end_date, chunk_days
            )

            if not all_candles:
                raise BacktestDataError(f"No data collected for {symbol}")

            # ==================== 3. DB에 저장 ====================
            if use_cache and self.ohlcv_repo:
                await self._save_to_cache(symbol, all_candles)
                await self.db_session.commit()
                print(f"💾 데이터 DB 저장 완료: {len(all_candles)}건")

            # ==================== 4. DataFrame 변환 및 검증 ====================
            df = self._candles_to_dataframe(all_candles)
            self._validate_data(df, start_date, end_date)
            df = self._preprocess_data(df)

            actual_start = df["timestamp"].min()
            actual_end = df["timestamp"].max()

            return df, actual_start, actual_end

        except Exception as e:
            if self.db_session:
                await self.db_session.rollback()
            raise BacktestDataError(f"Failed to load OHLCV data for {symbol}: {e}")

    async def _collect_long_period(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        chunk_days: int = 90
    ) -> list[CandleDTO]:
        """
        장기간 데이터 분할 수집

        KIS API 제한을 고려하여 기간을 나눠서 수집합니다.

        Args:
            symbol: 종목코드
            start_date: 시작일
            end_date: 종료일
            chunk_days: 한 번에 조회할 기간 (일)

        Returns:
            list[CandleDTO]: 전체 기간 캔들 데이터
        """
        candles_by_date: dict[datetime, CandleDTO] = {}
        current_end = end_date
        last_earliest: datetime | None = None

        while current_end >= start_date:
            current_start = max(start_date, current_end - timedelta(days=chunk_days - 1))

            chart_data = await self.market_data_service.get_chart_data(
                symbol=symbol,
                interval="1d",
                start_date=current_start,
                end_date=current_end
            )

            if not chart_data.candles:
                break

            for candle in chart_data.candles:
                if start_date <= candle.timestamp <= end_date:
                    candles_by_date[candle.timestamp] = candle

            earliest_in_chunk = min(c.timestamp for c in chart_data.candles)

            if last_earliest and earliest_in_chunk >= last_earliest:
                # 더 이상 과거 데이터가 내려오지 않는 경우 (API 한계)
                break

            last_earliest = earliest_in_chunk

            if earliest_in_chunk <= start_date:
                break

            current_end = earliest_in_chunk - timedelta(days=1)
            await asyncio.sleep(0.1)  # Rate limit 대응

        all_candles = list(candles_by_date.values())
        all_candles.sort(key=lambda x: x.timestamp)
        return all_candles

    def _candles_to_dataframe(self, candles: list[CandleDTO]) -> pd.DataFrame:
        """
        CandleDTO 리스트를 DataFrame으로 변환

        Args:
            candles: 캔들 데이터 리스트

        Returns:
            pd.DataFrame: OHLCV 데이터
        """
        data = []
        for candle in candles:
            data.append({
                "timestamp": candle.timestamp,
                "open": float(candle.open),
                "high": float(candle.high),
                "low": float(candle.low),
                "close": float(candle.close),
                "volume": candle.volume,
            })

        df = pd.DataFrame(data)

        # 날짜 인덱스 설정
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp")
        df = df.reset_index(drop=True)

        return df

    def _validate_data(
        self,
        df: pd.DataFrame,
        start_date: datetime,
        end_date: datetime
    ) -> None:
        """
        데이터 유효성 검증

        Args:
            df: OHLCV 데이터
            start_date: 예상 시작일
            end_date: 예상 종료일

        Raises:
            BacktestDataError: 데이터 검증 실패
        """
        # 최소 데이터 수 확인 (최소 20일 이상)
        if len(df) < 20:
            raise BacktestDataError(
                f"Insufficient data: {len(df)} rows (minimum 20 required)"
            )

        # OHLC 관계 검증
        violations = self._validate_ohlc_relationship(df)
        if violations:
            raise BacktestDataError(
                f"OHLC relationship violations found: {len(violations)} rows"
            )

        # 결측치 확인
        if df.isnull().any().any():
            raise BacktestDataError("Missing values found in data")

        # 음수 가격 확인
        price_columns = ["open", "high", "low", "close"]
        for col in price_columns:
            if (df[col] <= 0).any():
                raise BacktestDataError(f"Negative or zero prices found in {col}")

        # 음수 거래량 확인
        if (df["volume"] < 0).any():
            raise BacktestDataError("Negative volume found")

    def _validate_ohlc_relationship(self, df: pd.DataFrame) -> list[int]:
        """
        OHLC 관계 검증

        High >= Open, Close, Low
        Low <= Open, Close, High

        Args:
            df: OHLCV 데이터

        Returns:
            list[int]: 위반 행 인덱스 리스트
        """
        violations = []

        for idx, row in df.iterrows():
            # High가 가장 높은지
            if row["high"] < row["open"] or row["high"] < row["close"] or row["high"] < row["low"]:
                violations.append(idx)
                continue

            # Low가 가장 낮은지
            if row["low"] > row["open"] or row["low"] > row["close"] or row["low"] > row["high"]:
                violations.append(idx)
                continue

        return violations

    def _preprocess_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        데이터 전처리

        - 결측치 보간 (Forward Fill)
        - 이상치 제거
        - 정렬

        Args:
            df: 원본 OHLCV 데이터

        Returns:
            pd.DataFrame: 전처리된 데이터
        """
        # 날짜순 정렬
        df = df.sort_values("timestamp")

        # 결측치 보간 (Forward Fill)
        df = df.ffill()

        # 중복 제거
        df = df.drop_duplicates(subset=["timestamp"], keep="first")

        # 인덱스 리셋
        df = df.reset_index(drop=True)

        return df

    def validate_missing_dates(
        self,
        df: pd.DataFrame,
        start_date: datetime,
        end_date: datetime
    ) -> dict:
        """
        결측 거래일 검증

        Args:
            df: OHLCV 데이터
            start_date: 예상 시작일
            end_date: 예상 종료일

        Returns:
            dict: 검증 결과
                - total_expected: 예상 거래일 수
                - total_actual: 실제 데이터 수
                - missing_count: 결측일 수
                - coverage_rate: 커버리지 비율
        """
        # 실제 데이터 날짜 추출
        actual_dates = set(df["timestamp"].dt.date)

        # 예상 거래일 생성 (주말 제외)
        expected_dates = set()
        current = start_date
        while current <= end_date:
            if current.weekday() < 5:  # 월~금
                expected_dates.add(current.date())
            current += timedelta(days=1)

        # 결측일 확인
        missing_dates = expected_dates - actual_dates

        return {
            "total_expected": len(expected_dates),
            "total_actual": len(actual_dates),
            "missing_count": len(missing_dates),
            "coverage_rate": len(actual_dates) / len(expected_dates) if expected_dates else 0.0
        }

    def get_data_summary(self, df: pd.DataFrame) -> dict:
        """
        데이터 요약 정보

        Args:
            df: OHLCV 데이터

        Returns:
            dict: 요약 정보
        """
        return {
            "total_rows": len(df),
            "start_date": df["timestamp"].min(),
            "end_date": df["timestamp"].max(),
            "price_min": df["low"].min(),
            "price_max": df["high"].max(),
            "avg_volume": int(df["volume"].mean()),
            "total_volume": int(df["volume"].sum()),
        }

    # ==================== DB 캐싱 헬퍼 메서드 ====================

    async def _load_from_cache(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> tuple[pd.DataFrame, datetime, datetime] | None:
        """
        DB 캐시에서 데이터 로드

        Args:
            symbol: 종목코드
            start_date: 시작일
            end_date: 종료일

        Returns:
            tuple | None: (DataFrame, 실제 시작일, 실제 종료일) 또는 None (캐시 미스)
        """
        if not self.ohlcv_repo:
            return None

        # 데이터 가용성 확인
        availability = await self.ohlcv_repo.check_data_availability(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval="1d",
        )

        # 완전한 데이터가 없으면 캐시 미스
        if not availability["is_complete"]:
            if availability["has_data"]:
                print(f"⚠️ 부분 캐시 존재 (미사용): {availability['count']}건")
            return None

        # DB에서 DataFrame 로드
        df = await self.ohlcv_repo.get_candles_to_dataframe(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval="1d",
        )

        if df.empty:
            return None

        # 데이터 검증 및 전처리
        self._validate_data(df, start_date, end_date)
        df = self._preprocess_data(df)

        actual_start = df["timestamp"].min()
        actual_end = df["timestamp"].max()

        # 타임존 정규화 (pandas Timestamp를 Python datetime으로, timezone-naive로)
        if hasattr(actual_start, 'to_pydatetime'):
            actual_start = actual_start.to_pydatetime()
        if hasattr(actual_end, 'to_pydatetime'):
            actual_end = actual_end.to_pydatetime()
        if actual_start.tzinfo is not None:
            actual_start = actual_start.replace(tzinfo=None)
        if actual_end.tzinfo is not None:
            actual_end = actual_end.replace(tzinfo=None)

        return df, actual_start, actual_end

    async def _save_to_cache(
        self,
        symbol: str,
        candles: list[CandleDTO],
    ) -> None:
        """
        수집한 캔들 데이터를 DB에 저장

        Args:
            symbol: 종목코드
            candles: 캔들 데이터 리스트
        """
        if not self.ohlcv_repo or not candles:
            return

        await self.ohlcv_repo.save_candles_bulk(
            symbol=symbol,
            candles=candles,
            interval="1d",
            source="kis",
        )
