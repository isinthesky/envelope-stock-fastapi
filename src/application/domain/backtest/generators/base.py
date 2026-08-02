# -*- coding: utf-8 -*-
"""BaseSignalGenerator - 백테스트 시그널 생성기 공통 계약."""

from abc import ABC, abstractmethod
from decimal import Decimal


class BaseSignalGenerator(ABC):
    @abstractmethod
    def generate_signal(
        self,
        price_history: list[float],
        current_price: Decimal,
        **kwargs: object,
    ) -> str:
        pass

    @property
    @abstractmethod
    def min_period(self) -> int:
        pass

    def reset(self) -> None:
        pass
