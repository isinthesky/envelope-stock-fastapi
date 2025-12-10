# -*- coding: utf-8 -*-
"""
News-based Day Trading Domain

뉴스 기반 장 초반 단타 매매 시스템
- 전일 뉴스 분석으로 관련 종목 사전 선별
- 장 시작 후 복합 조건 필터링
- 제한된 시간 내 기계적 매매 실행
"""

from src.application.domain.news_trading.dto import (
    # Enums
    NewsEventType,
    MomentumSignal,
    ExitReason,
    TradingStatus,
    # News Analysis
    NewsItemDTO,
    NewsScoreDTO,
    NewsAnalysisRequestDTO,
    NewsAnalysisResultDTO,
    # Stock Selection
    StockCandidateDTO,
    StockRankingDTO,
    StockSelectionConfigDTO,
    StockSelectionResultDTO,
    # Entry/Exit
    EntryConditionConfigDTO,
    ExitConditionConfigDTO,
    StagedProfitTakingConfig,
    MomentumExitConfigDTO,
    # Risk Management
    PositionSizingConfigDTO,
    RiskLimitConfigDTO,
    SafetyGuardConfigDTO,
    # Trading Session
    TradingSessionConfigDTO,
    TradingSignalDTO,
    TradingResultDTO,
    # Strategy
    NewsTradingStrategyConfigDTO,
    # Backtest
    NewsTradingBacktestRequestDTO,
    NewsTradingBacktestResultDTO,
)

from src.application.domain.news_trading.news_analyzer import NewsAnalyzer
from src.application.domain.news_trading.stock_selector import StockSelector
from src.application.domain.news_trading.momentum_detector import (
    MomentumDetector,
    SimpleMovingMomentum,
)
from src.application.domain.news_trading.exit_manager import (
    ExitManager,
    BacktestExitManager,
)
from src.application.domain.news_trading.safety_guard import SafetyGuard
from src.application.domain.news_trading.strategy_engine import NewsTradingStrategyEngine
from src.application.domain.news_trading.backtest_engine import NewsTradingBacktestEngine

__all__ = [
    # Enums
    "NewsEventType",
    "MomentumSignal",
    "ExitReason",
    "TradingStatus",
    # DTOs - News Analysis
    "NewsItemDTO",
    "NewsScoreDTO",
    "NewsAnalysisRequestDTO",
    "NewsAnalysisResultDTO",
    # DTOs - Stock Selection
    "StockCandidateDTO",
    "StockRankingDTO",
    "StockSelectionConfigDTO",
    "StockSelectionResultDTO",
    # DTOs - Entry/Exit
    "EntryConditionConfigDTO",
    "ExitConditionConfigDTO",
    "StagedProfitTakingConfig",
    "MomentumExitConfigDTO",
    # DTOs - Risk Management
    "PositionSizingConfigDTO",
    "RiskLimitConfigDTO",
    "SafetyGuardConfigDTO",
    # DTOs - Trading Session
    "TradingSessionConfigDTO",
    "TradingSignalDTO",
    "TradingResultDTO",
    # DTOs - Strategy
    "NewsTradingStrategyConfigDTO",
    # DTOs - Backtest
    "NewsTradingBacktestRequestDTO",
    "NewsTradingBacktestResultDTO",
    # Services
    "NewsAnalyzer",
    "StockSelector",
    "MomentumDetector",
    "SimpleMovingMomentum",
    "ExitManager",
    "BacktestExitManager",
    "SafetyGuard",
    "NewsTradingStrategyEngine",
    "NewsTradingBacktestEngine",
]
