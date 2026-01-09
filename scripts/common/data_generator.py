# -*- coding: utf-8 -*-
"""
Synthetic Data Generator - 합성 OHLCV 데이터 생성 모듈

다양한 시장 시나리오에 맞는 합성 데이터를 생성합니다.
"""

import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


@dataclass
class MarketScenario:
    """
    시장 시나리오 설정

    Attributes:
        name: 시나리오 이름
        trend: 일간 평균 수익률 (예: 0.0002 = 0.02%)
        volatility: 일간 변동성 (예: 0.015 = 1.5%)
        start_price: 시작 가격
        periods: 캔들 개수
        seed: 난수 시드 (재현성)
        scenario_type: 시나리오 유형 (random, gc_scenario, dc_scenario, sideways)
    """

    name: str = "Default"
    trend: float = 0.0002
    volatility: float = 0.015
    start_price: float = 10000.0
    periods: int = 250
    seed: int | None = None
    scenario_type: str = "random"  # random, gc_scenario, dc_scenario, sideways

    def __post_init__(self):
        if self.seed is None:
            # 이름 기반 시드 생성 (재현성)
            self.seed = int(hashlib.md5(self.name.encode()).hexdigest()[:8], 16) % (2**31)


class SyntheticDataGenerator:
    """
    합성 OHLCV 데이터 생성기

    다양한 시장 패턴을 시뮬레이션하는 데이터를 생성합니다.
    """

    @staticmethod
    def generate_ohlcv(
        scenario: MarketScenario,
        start_date: datetime | None = None,
    ) -> pd.DataFrame:
        """
        시나리오 기반 OHLCV 데이터 생성

        Args:
            scenario: 시장 시나리오 설정
            start_date: 시작 날짜 (기본값: 1년 전)

        Returns:
            pd.DataFrame: OHLCV 데이터프레임
        """
        if start_date is None:
            start_date = datetime.now() - timedelta(days=scenario.periods + 50)

        # 시나리오 타입에 따른 생성
        if scenario.scenario_type == "gc_scenario":
            return SyntheticDataGenerator.generate_gc_scenario(
                start_date=start_date,
                periods=scenario.periods,
                seed=scenario.seed,
            )
        elif scenario.scenario_type == "dc_scenario":
            return SyntheticDataGenerator.generate_dc_scenario(
                start_date=start_date,
                periods=scenario.periods,
                seed=scenario.seed,
            )
        elif scenario.scenario_type == "sideways":
            return SyntheticDataGenerator.generate_sideways(
                start_date=start_date,
                periods=scenario.periods,
                seed=scenario.seed,
            )
        else:
            return SyntheticDataGenerator._generate_random_walk(
                start_date=start_date,
                periods=scenario.periods,
                trend=scenario.trend,
                volatility=scenario.volatility,
                start_price=scenario.start_price,
                seed=scenario.seed,
            )

    @staticmethod
    def _generate_random_walk(
        start_date: datetime,
        periods: int,
        trend: float,
        volatility: float,
        start_price: float,
        seed: int | None,
    ) -> pd.DataFrame:
        """Random Walk with Drift 기반 데이터 생성"""
        if seed is not None:
            np.random.seed(seed)
            random.seed(seed)

        dates = pd.date_range(start=start_date, periods=periods, freq="D")

        # Random Walk with Drift
        returns = np.random.normal(loc=trend, scale=volatility, size=periods)
        price_paths = start_price * np.cumprod(1 + returns)

        # OHLC 생성
        opens = price_paths
        closes = price_paths * (1 + np.random.normal(0, 0.005, periods))
        highs = np.maximum(opens, closes) * (1 + np.abs(np.random.normal(0, 0.005, periods)))
        lows = np.minimum(opens, closes) * (1 - np.abs(np.random.normal(0, 0.005, periods)))
        volumes = np.random.randint(100000, 1000000, periods)

        df = pd.DataFrame({
            "timestamp": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        })

        return df

    @staticmethod
    def generate_gc_scenario(
        start_date: datetime,
        periods: int = 500,
        seed: int | None = None,
    ) -> pd.DataFrame:
        """
        골든크로스 시나리오 데이터 생성

        MA60이 MA200을 상향 돌파하는 패턴을 강제로 생성

        Args:
            start_date: 시작 날짜
            periods: 캔들 개수
            seed: 난수 시드

        Returns:
            pd.DataFrame: 골든크로스 패턴을 포함한 OHLCV 데이터
        """
        if seed is not None:
            np.random.seed(seed)
            random.seed(seed)

        dates = pd.date_range(start=start_date, periods=periods, freq="D")

        # 4단계 가격 경로:
        # 1단계 (0~200일): 하락/횡보 → MA200 > MA60 상태 유지
        # 2단계 (200~300일): 상승 시작 → MA60 상승
        # 3단계 (300~400일): 조정 (Pullback)
        # 4단계 (400~500일): 2차 파동 상승

        base_price = 10000

        prices = np.zeros(periods)

        # 단계별 가격 설정
        phase1_end = int(periods * 0.4)  # 40%
        phase2_end = int(periods * 0.6)  # 60%
        phase3_end = int(periods * 0.8)  # 80%

        # Phase 1: 하락/횡보
        for i in range(phase1_end):
            if i == 0:
                prices[i] = base_price
            else:
                # 약간의 하락 추세
                drift = -0.0002 + np.random.normal(0, 0.015)
                prices[i] = prices[i-1] * (1 + drift)

        # Phase 2: 상승 시작
        for i in range(phase1_end, phase2_end):
            # 강한 상승
            drift = 0.003 + np.random.normal(0, 0.01)
            prices[i] = prices[i-1] * (1 + drift)

        # Phase 3: 조정 (Pullback)
        for i in range(phase2_end, phase3_end):
            # 약한 하락
            drift = -0.001 + np.random.normal(0, 0.008)
            prices[i] = prices[i-1] * (1 + drift)

        # Phase 4: 2차 상승
        for i in range(phase3_end, periods):
            # 강한 상승
            drift = 0.002 + np.random.normal(0, 0.01)
            prices[i] = prices[i-1] * (1 + drift)

        # OHLC 변환
        opens = prices
        closes = prices * (1 + np.random.normal(0, 0.005, periods))
        highs = np.maximum(opens, closes) * (1 + np.abs(np.random.normal(0, 0.005, periods)))
        lows = np.minimum(opens, closes) * (1 - np.abs(np.random.normal(0, 0.005, periods)))
        volumes = np.random.randint(100000, 1000000, periods)

        df = pd.DataFrame({
            "timestamp": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        })

        return df

    @staticmethod
    def generate_dc_scenario(
        start_date: datetime,
        periods: int = 500,
        seed: int | None = None,
    ) -> pd.DataFrame:
        """
        데드크로스 시나리오 데이터 생성

        MA60이 MA200을 하향 돌파하는 패턴
        """
        if seed is not None:
            np.random.seed(seed)
            random.seed(seed)

        dates = pd.date_range(start=start_date, periods=periods, freq="D")

        base_price = 10000
        prices = np.zeros(periods)

        phase1_end = int(periods * 0.4)
        phase2_end = int(periods * 0.6)
        phase3_end = int(periods * 0.8)

        # Phase 1: 상승
        for i in range(phase1_end):
            if i == 0:
                prices[i] = base_price
            else:
                drift = 0.0003 + np.random.normal(0, 0.015)
                prices[i] = prices[i-1] * (1 + drift)

        # Phase 2: 하락 시작
        for i in range(phase1_end, phase2_end):
            drift = -0.003 + np.random.normal(0, 0.01)
            prices[i] = prices[i-1] * (1 + drift)

        # Phase 3: 반등
        for i in range(phase2_end, phase3_end):
            drift = 0.001 + np.random.normal(0, 0.008)
            prices[i] = prices[i-1] * (1 + drift)

        # Phase 4: 추가 하락
        for i in range(phase3_end, periods):
            drift = -0.002 + np.random.normal(0, 0.01)
            prices[i] = prices[i-1] * (1 + drift)

        opens = prices
        closes = prices * (1 + np.random.normal(0, 0.005, periods))
        highs = np.maximum(opens, closes) * (1 + np.abs(np.random.normal(0, 0.005, periods)))
        lows = np.minimum(opens, closes) * (1 - np.abs(np.random.normal(0, 0.005, periods)))
        volumes = np.random.randint(100000, 1000000, periods)

        return pd.DataFrame({
            "timestamp": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        })

    @staticmethod
    def generate_sideways(
        start_date: datetime,
        periods: int = 250,
        seed: int | None = None,
    ) -> pd.DataFrame:
        """횡보장 시나리오 데이터 생성"""
        if seed is not None:
            np.random.seed(seed)
            random.seed(seed)

        dates = pd.date_range(start=start_date, periods=periods, freq="D")

        # 변동성만 있고 추세 없음
        base_price = 10000
        returns = np.random.normal(loc=0, scale=0.012, size=periods)
        price_paths = base_price * np.cumprod(1 + returns)

        opens = price_paths
        closes = price_paths * (1 + np.random.normal(0, 0.005, periods))
        highs = np.maximum(opens, closes) * (1 + np.abs(np.random.normal(0, 0.005, periods)))
        lows = np.minimum(opens, closes) * (1 - np.abs(np.random.normal(0, 0.005, periods)))
        volumes = np.random.randint(100000, 1000000, periods)

        return pd.DataFrame({
            "timestamp": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        })

    @staticmethod
    def generate_monte_carlo(
        base_scenario: MarketScenario,
        simulations: int = 100,
        trend_std: float = 0.0005,
        vol_range: tuple = (0.01, 0.03),
    ) -> list[pd.DataFrame]:
        """
        몬테카를로 시뮬레이션용 다중 데이터 생성

        Args:
            base_scenario: 기본 시나리오
            simulations: 시뮬레이션 횟수
            trend_std: 트렌드 표준편차
            vol_range: 변동성 범위 (min, max)

        Returns:
            list[pd.DataFrame]: 시뮬레이션 데이터 목록
        """
        datasets = []

        for i in range(simulations):
            # 각 시뮬레이션마다 트렌드와 변동성 변경
            random_trend = np.random.normal(base_scenario.trend, trend_std)
            random_vol = np.random.uniform(vol_range[0], vol_range[1])

            scenario = MarketScenario(
                name=f"{base_scenario.name}_sim_{i}",
                trend=random_trend,
                volatility=random_vol,
                start_price=base_scenario.start_price,
                periods=base_scenario.periods,
                seed=i,  # 재현성을 위해 시뮬레이션 번호를 시드로 사용
                scenario_type="random",
            )

            df = SyntheticDataGenerator.generate_ohlcv(scenario)
            datasets.append(df)

        return datasets


@dataclass
class StockMetadata:
    """종목 메타데이터"""
    symbol: str
    name: str
    market: str = "KOSPI"
    sector: str = "Unknown"
    market_cap: float = 1e12
    avg_volume: int = 500000
    volatility: float = 0.02
    per: float = 15.0
    debt_ratio: float = 50.0


@dataclass
class SyntheticMarket:
    """
    가상 시장 (다중 종목 관리)

    여러 종목의 합성 데이터를 생성하고 관리합니다.
    """

    stocks: dict[str, StockMetadata] = field(default_factory=dict)
    _data_cache: dict[str, pd.DataFrame] = field(default_factory=dict)

    def add_stock(
        self,
        symbol: str,
        name: str,
        scenario: MarketScenario | None = None,
        **metadata_kwargs,
    ) -> None:
        """
        종목 추가

        Args:
            symbol: 종목코드
            name: 종목명
            scenario: 시장 시나리오 (None이면 기본값)
            **metadata_kwargs: 추가 메타데이터 (market_cap, per 등)
        """
        self.stocks[symbol] = StockMetadata(
            symbol=symbol,
            name=name,
            **metadata_kwargs,
        )

        if scenario:
            self._data_cache[symbol] = SyntheticDataGenerator.generate_ohlcv(scenario)

    def generate_all(
        self,
        start_date: datetime | None = None,
        periods: int = 250,
    ) -> dict[str, pd.DataFrame]:
        """
        전체 종목 데이터 생성

        Args:
            start_date: 시작 날짜
            periods: 캔들 개수

        Returns:
            dict[str, pd.DataFrame]: 종목별 OHLCV 데이터
        """
        result = {}

        for symbol, meta in self.stocks.items():
            if symbol in self._data_cache:
                result[symbol] = self._data_cache[symbol]
            else:
                scenario = MarketScenario(
                    name=symbol,
                    volatility=meta.volatility,
                    periods=periods,
                )
                result[symbol] = SyntheticDataGenerator.generate_ohlcv(
                    scenario,
                    start_date=start_date,
                )

        return result

    def screen_stocks(
        self,
        min_volume: int = 500000,
        max_volatility: float = 0.03,
        max_debt_ratio: float = 100.0,
        max_per: float = 40.0,
    ) -> list[str]:
        """
        기준에 따른 종목 스크리닝

        Args:
            min_volume: 최소 거래량
            max_volatility: 최대 변동성
            max_debt_ratio: 최대 부채비율
            max_per: 최대 PER

        Returns:
            list[str]: 스크리닝 통과 종목 코드
        """
        passed = []

        for symbol, meta in self.stocks.items():
            if meta.avg_volume < min_volume:
                continue
            if meta.volatility > max_volatility:
                continue
            if meta.debt_ratio > max_debt_ratio:
                continue
            if meta.per > max_per:
                continue
            passed.append(symbol)

        return passed
