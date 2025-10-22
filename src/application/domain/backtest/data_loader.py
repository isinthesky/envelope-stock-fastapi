# -*- coding: utf-8 -*-
"""
Backtest Data Loader - 백테스팅 데이터 수집 및 전처리

과거 차트 데이터 수집, 검증, 전처리를 담당합니다.
"""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

import pandas as pd

from src.application.common.exceptions import BacktestDataError
from src.application.domain.market_data.dto import CandleDTO
from src.application.domain.market_data.service import MarketDataService


class BacktestDataLoader:
    """
    백테스팅 데이터 로더

    과거 차트 데이터를 수집하고 백테스팅에 적합한 형태로 전처리합니다.
    """

    def __init__(self, market_data_service: MarketDataService):
        """
        Args:
            market_data_service: 시세 데이터 서비스
        """
        self.market_data_service = market_data_service

    async def load_ohlcv_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        chunk_days: int = 365
    ) -> pd.DataFrame:
        """
        OHLCV 데이터 로드

        Args:
            symbol: 종목코드
            start_date: 시작일
            end_date: 종료일
            chunk_days: 한 번에 조회할 기간 (일)

        Returns:
            pd.DataFrame: OHLCV 데이터
                컬럼: timestamp, open, high, low, close, volume

        Raises:
            BacktestDataError: 데이터 로드 실패
        """
        try:
            # 기간 분할 수집
            all_candles = await self._collect_long_period(
                symbol, start_date, end_date, chunk_days
            )

            if not all_candles:
                raise BacktestDataError(f"No data collected for {symbol}")

            # DataFrame 변환
            df = self._candles_to_dataframe(all_candles)

            # 데이터 검증
            self._validate_data(df, start_date, end_date)

            # 전처리
            df = self._preprocess_data(df)

            return df

        except Exception as e:
            raise BacktestDataError(f"Failed to load OHLCV data for {symbol}: {e}")

    async def _collect_long_period(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        chunk_days: int = 365
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
        all_candles = []
        current_date = start_date

        while current_date < end_date:
            chunk_end = min(current_date + timedelta(days=chunk_days), end_date)

            # 차트 데이터 조회
            chart_data = await self.market_data_service.get_chart_data(
                symbol=symbol,
                interval="1d",
                start_date=current_date,
                end_date=chunk_end
            )

            all_candles.extend(chart_data.candles)

            current_date = chunk_end
            await asyncio.sleep(0.1)  # Rate limit 대응

        # 날짜순 정렬 (오래된 것부터)
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
