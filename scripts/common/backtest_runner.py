# -*- coding: utf-8 -*-
"""
Backtest Runner - 백테스트 실행 헬퍼 모듈

단일/다중/몬테카를로 백테스트 실행을 위한 헬퍼 함수 제공
"""

import asyncio
from datetime import datetime
from typing import Callable

import pandas as pd

from src.application.domain.backtest.dto import BacktestConfigDTO, BacktestResultDTO
from src.application.domain.backtest.engine import BacktestEngine
from src.application.domain.strategy.dto import StrategyConfigDTO


class BacktestRunner:
    """
    백테스트 실행 헬퍼

    단일, 다중, 몬테카를로 시뮬레이션 백테스트를 위한 유틸리티
    """

    # ==================== 단일 백테스트 ====================

    @staticmethod
    async def run_single(
        df: pd.DataFrame,
        symbol: str,
        strategy_config: StrategyConfigDTO,
        backtest_config: BacktestConfigDTO,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> BacktestResultDTO:
        """
        단일 백테스트 실행

        Args:
            df: OHLCV 데이터프레임
            symbol: 종목코드
            strategy_config: 전략 설정
            backtest_config: 백테스트 설정
            start_date: 시작일 (None이면 데이터 첫날)
            end_date: 종료일 (None이면 데이터 마지막날)

        Returns:
            BacktestResultDTO: 백테스트 결과
        """
        if df.empty:
            raise ValueError("Empty DataFrame provided")

        # 날짜 추출
        if start_date is None:
            start_date = df["timestamp"].iloc[0]
        if end_date is None:
            end_date = df["timestamp"].iloc[-1]

        # pandas Timestamp를 datetime으로 변환
        if hasattr(start_date, 'to_pydatetime'):
            start_date = start_date.to_pydatetime()
        if hasattr(end_date, 'to_pydatetime'):
            end_date = end_date.to_pydatetime()

        engine = BacktestEngine(
            symbol=symbol,
            strategy_config=strategy_config,
            backtest_config=backtest_config,
        )

        result = await engine.run(df, start_date, end_date)
        return result

    # ==================== 다중 종목 백테스트 ====================

    @staticmethod
    async def run_multiple(
        data_map: dict[str, pd.DataFrame],
        strategy_config: StrategyConfigDTO,
        backtest_config: BacktestConfigDTO,
        concurrency: int = 3,
    ) -> dict[str, BacktestResultDTO]:
        """
        다중 종목 백테스트 실행

        Args:
            data_map: {종목코드: OHLCV DataFrame}
            strategy_config: 전략 설정
            backtest_config: 백테스트 설정
            concurrency: 동시 실행 수

        Returns:
            dict[str, BacktestResultDTO]: {종목코드: 결과}
        """
        if not data_map:
            return {}

        semaphore = asyncio.Semaphore(concurrency)
        results = {}

        async def run_one(symbol: str, df: pd.DataFrame):
            async with semaphore:
                try:
                    result = await BacktestRunner.run_single(
                        df=df,
                        symbol=symbol,
                        strategy_config=strategy_config,
                        backtest_config=backtest_config,
                    )
                    return symbol, result
                except Exception as e:
                    print(f"[BacktestRunner] Failed for {symbol}: {e}")
                    return symbol, None

        tasks = [run_one(symbol, df) for symbol, df in data_map.items()]
        completed = await asyncio.gather(*tasks)

        for symbol, result in completed:
            if result is not None:
                results[symbol] = result

        return results

    # ==================== 몬테카를로 시뮬레이션 ====================

    @staticmethod
    async def run_monte_carlo(
        datasets: list[pd.DataFrame],
        strategy_config: StrategyConfigDTO,
        backtest_config: BacktestConfigDTO,
        symbol: str = "SYNTHETIC",
        concurrency: int = 5,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[BacktestResultDTO]:
        """
        몬테카를로 시뮬레이션 백테스트

        Args:
            datasets: 시뮬레이션 데이터 목록
            strategy_config: 전략 설정
            backtest_config: 백테스트 설정
            symbol: 종목코드 (표시용)
            concurrency: 동시 실행 수
            progress_callback: 진행 콜백 함수(current, total)

        Returns:
            list[BacktestResultDTO]: 시뮬레이션 결과 목록
        """
        if not datasets:
            return []

        semaphore = asyncio.Semaphore(concurrency)
        results = []
        total = len(datasets)
        completed_count = 0

        async def run_one(idx: int, df: pd.DataFrame):
            nonlocal completed_count
            async with semaphore:
                try:
                    result = await BacktestRunner.run_single(
                        df=df,
                        symbol=f"{symbol}_{idx}",
                        strategy_config=strategy_config,
                        backtest_config=backtest_config,
                    )
                    completed_count += 1
                    if progress_callback:
                        progress_callback(completed_count, total)
                    return idx, result
                except Exception as e:
                    print(f"[BacktestRunner] Monte Carlo {idx} failed: {e}")
                    completed_count += 1
                    return idx, None

        tasks = [run_one(i, df) for i, df in enumerate(datasets)]
        completed = await asyncio.gather(*tasks)

        # 순서 유지하며 결과 수집
        sorted_results = sorted([r for r in completed if r[1] is not None], key=lambda x: x[0])
        results = [r[1] for r in sorted_results]

        return results

    # ==================== 유틸리티 ====================

    @staticmethod
    def validate_dataframe(df: pd.DataFrame) -> bool:
        """
        OHLCV DataFrame 유효성 검증

        Args:
            df: 검증할 DataFrame

        Returns:
            bool: 유효 여부
        """
        required_columns = ["timestamp", "open", "high", "low", "close", "volume"]

        if df.empty:
            return False

        for col in required_columns:
            if col not in df.columns:
                return False

        # 데이터 타입 확인
        if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
            return False

        # OHLC 관계 확인 (샘플링)
        sample = df.head(100)
        for _, row in sample.iterrows():
            if row["high"] < row["low"]:
                return False
            if row["high"] < max(row["open"], row["close"]):
                return False
            if row["low"] > min(row["open"], row["close"]):
                return False

        return True

    @staticmethod
    def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        """
        DataFrame 전처리

        - 타임스탬프 정렬
        - 중복 제거
        - 인덱스 리셋

        Args:
            df: 원본 DataFrame

        Returns:
            pd.DataFrame: 정리된 DataFrame
        """
        df = df.copy()

        # 타임스탬프를 datetime으로 변환
        if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
            df["timestamp"] = pd.to_datetime(df["timestamp"])

        # 중복 제거 및 정렬
        df = (
            df.drop_duplicates(subset=["timestamp"])
            .sort_values("timestamp")
            .reset_index(drop=True)
        )

        return df

    @staticmethod
    async def run_with_progress(
        datasets: list[pd.DataFrame],
        strategy_config: StrategyConfigDTO,
        backtest_config: BacktestConfigDTO,
    ) -> list[BacktestResultDTO]:
        """
        진행 상황 표시와 함께 몬테카를로 실행

        Args:
            datasets: 데이터 목록
            strategy_config: 전략 설정
            backtest_config: 백테스트 설정

        Returns:
            list[BacktestResultDTO]: 결과 목록
        """
        def progress(current: int, total: int):
            pct = current / total * 100
            bar_len = 30
            filled = int(bar_len * current / total)
            bar = "█" * filled + "░" * (bar_len - filled)
            print(f"\r  [{bar}] {pct:5.1f}% ({current}/{total})", end="", flush=True)

        print(f"  Running {len(datasets)} simulations...")
        results = await BacktestRunner.run_monte_carlo(
            datasets=datasets,
            strategy_config=strategy_config,
            backtest_config=backtest_config,
            progress_callback=progress,
        )
        print()  # 줄바꿈

        return results
