# -*- coding: utf-8 -*-
"""
Scripts Common Package - 공통 모듈

- data_generator: 합성 OHLCV 데이터 생성
- strategy_presets: 전략 설정 프리셋
- result_analyzer: 백테스트 결과 분석/포맷팅
- backtest_runner: 백테스트 실행 헬퍼
"""

from scripts.common.backtest_runner import BacktestRunner
from scripts.common.data_generator import MarketScenario, SyntheticDataGenerator, SyntheticMarket
from scripts.common.result_analyzer import ResultAnalyzer
from scripts.common.strategy_presets import StrategyPresets

__all__ = [
    "MarketScenario",
    "SyntheticDataGenerator",
    "SyntheticMarket",
    "StrategyPresets",
    "ResultAnalyzer",
    "BacktestRunner",
]
