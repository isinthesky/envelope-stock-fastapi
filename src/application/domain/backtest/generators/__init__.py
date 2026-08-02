# -*- coding: utf-8 -*-
"""백테스트 시그널 생성기 패키지.

전략별 매수/매도 시그널 생성 로직을 전략 단위 모듈로 분리한다.
- ``base``: 공통 계약(`BaseSignalGenerator`)
- ``golden_cross``: 스윙형 골든크로스(온디맨드 백테스트 진단용)
- ``factory``: `create_signal_generator`

라이브 parity 검증에는 이 패키지 대신 `backtest.golden_cross_parity`를 사용한다.
"""

from src.application.domain.backtest.generators.base import BaseSignalGenerator
from src.application.domain.backtest.generators.factory import (
    SUPPORTED_STRATEGY_TYPES,
    create_signal_generator,
)
from src.application.domain.backtest.generators.golden_cross import GoldenCrossSignalGenerator

__all__ = [
    "BaseSignalGenerator",
    "GoldenCrossSignalGenerator",
    "create_signal_generator",
    "SUPPORTED_STRATEGY_TYPES",
]
