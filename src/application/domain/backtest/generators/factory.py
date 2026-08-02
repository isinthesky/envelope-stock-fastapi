# -*- coding: utf-8 -*-
"""create_signal_generator - 백테스트 시그널 생성기 팩토리.

지원 전략: ``golden_cross``.
레거시 볼린저+엔벨로프 평균회귀 생성기는 제거되었다(실주문 가드 없는 이중 엔진).
미지원 타입은 조용히 fallback 하지 않고 명시적으로 실패한다.
"""

from src.application.domain.backtest.generators.base import BaseSignalGenerator
from src.application.domain.backtest.generators.golden_cross import GoldenCrossSignalGenerator

SUPPORTED_STRATEGY_TYPES = ("golden_cross",)


def create_signal_generator(strategy_type: str, **kwargs: object) -> BaseSignalGenerator:
    if strategy_type == "golden_cross":
        return GoldenCrossSignalGenerator(**kwargs)
    raise ValueError(
        f"Unsupported strategy_type {strategy_type!r}. "
        f"Supported: {', '.join(SUPPORTED_STRATEGY_TYPES)}."
    )
