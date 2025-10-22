# -*- coding: utf-8 -*-
"""
Technical Indicators - 기술적 지표 계산 모듈

Bollinger Band, Envelope, 이동평균 등 기술적 지표 계산
"""

from decimal import Decimal

import pandas as pd


class TechnicalIndicators:
    """기술적 지표 계산 클래스"""

    @staticmethod
    def calculate_sma(prices: list[float], period: int) -> float | None:
        """
        단순 이동평균 (Simple Moving Average) 계산

        Args:
            prices: 가격 데이터 리스트
            period: 이동평균 기간

        Returns:
            float | None: 이동평균값 (데이터 부족 시 None)
        """
        if len(prices) < period:
            return None

        return sum(prices[-period:]) / period

    @staticmethod
    def calculate_std(prices: list[float], period: int) -> float | None:
        """
        표준편차 계산

        Args:
            prices: 가격 데이터 리스트
            period: 계산 기간

        Returns:
            float | None: 표준편차 (데이터 부족 시 None)
        """
        if len(prices) < period:
            return None

        recent_prices = prices[-period:]
        mean = sum(recent_prices) / period
        variance = sum((x - mean) ** 2 for x in recent_prices) / period
        return variance**0.5

    @classmethod
    def calculate_bollinger_bands(
        cls, prices: list[float], period: int = 20, std_multiplier: float = 2.0
    ) -> dict[str, float | None]:
        """
        볼린저 밴드 계산

        Args:
            prices: 가격 데이터 리스트
            period: 이동평균 기간 (기본: 20)
            std_multiplier: 표준편차 배수 (기본: 2.0)

        Returns:
            dict: {"upper": 상단, "middle": 중간, "lower": 하단}
        """
        if len(prices) < period:
            return {"upper": None, "middle": None, "lower": None}

        middle = cls.calculate_sma(prices, period)
        std = cls.calculate_std(prices, period)

        if middle is None or std is None:
            return {"upper": None, "middle": None, "lower": None}

        upper = middle + (std * std_multiplier)
        lower = middle - (std * std_multiplier)

        return {"upper": upper, "middle": middle, "lower": lower}

    @classmethod
    def calculate_envelope(
        cls, prices: list[float], period: int = 20, percentage: float = 2.0
    ) -> dict[str, float | None]:
        """
        Envelope (이동평균 채널) 계산

        Args:
            prices: 가격 데이터 리스트
            period: 이동평균 기간 (기본: 20)
            percentage: 채널 폭 비율 (기본: 2.0%)

        Returns:
            dict: {"upper": 상단, "middle": 중간, "lower": 하단}
        """
        if len(prices) < period:
            return {"upper": None, "middle": None, "lower": None}

        middle = cls.calculate_sma(prices, period)

        if middle is None:
            return {"upper": None, "middle": None, "lower": None}

        multiplier = 1 + (percentage / 100)
        upper = middle * multiplier
        lower = middle / multiplier

        return {"upper": upper, "middle": middle, "lower": lower}

    @classmethod
    def calculate_rsi(cls, prices: list[float], period: int = 14) -> float | None:
        """
        RSI (Relative Strength Index) 계산

        Args:
            prices: 가격 데이터 리스트
            period: RSI 기간 (기본: 14)

        Returns:
            float | None: RSI 값 (0-100)
        """
        if len(prices) < period + 1:
            return None

        # 가격 변화 계산
        changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        recent_changes = changes[-(period):]

        gains = [max(c, 0) for c in recent_changes]
        losses = [abs(min(c, 0)) for c in recent_changes]

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    @classmethod
    def generate_bollinger_signal(
        cls,
        current_price: float,
        bb_upper: float,
        bb_lower: float,
        threshold: float = 0.001,
    ) -> str:
        """
        볼린저 밴드 기반 매매 시그널 생성

        Args:
            current_price: 현재가
            bb_upper: 볼린저 밴드 상단
            bb_lower: 볼린저 밴드 하단
            threshold: 돌파 판정 임계값 (기본: 0.1%)

        Returns:
            str: "buy" (매수), "sell" (매도), "hold" (보유)
        """
        # 하단 돌파 (과매도) -> 매수 시그널
        if current_price < bb_lower * (1 - threshold):
            return "buy"

        # 상단 돌파 (과매수) -> 매도 시그널
        if current_price > bb_upper * (1 + threshold):
            return "sell"

        return "hold"

    @classmethod
    def calculate_position_size(
        cls, account_balance: float, allocation_ratio: float, current_price: float
    ) -> int:
        """
        포지션 크기 계산

        Args:
            account_balance: 계좌 잔고
            allocation_ratio: 자산 배분 비율 (0.0 ~ 1.0)
            current_price: 현재 주가

        Returns:
            int: 매수 수량
        """
        if current_price <= 0:
            return 0

        target_amount = account_balance * allocation_ratio
        quantity = int(target_amount / current_price)

        return quantity

    @classmethod
    def calculate_bollinger_bandwidth(
        cls, bb_upper: float, bb_lower: float, bb_middle: float
    ) -> float:
        """
        볼린저 밴드 폭 계산 (Bandwidth)

        Args:
            bb_upper: 볼린저 밴드 상단
            bb_lower: 볼린저 밴드 하단
            bb_middle: 볼린저 밴드 중간 (이동평균)

        Returns:
            float: 밴드 폭 비율
        """
        if bb_middle == 0:
            return 0.0

        bandwidth = (bb_upper - bb_lower) / bb_middle
        return bandwidth

    @classmethod
    def is_bollinger_squeeze(cls, bandwidth: float, threshold: float = 0.1) -> bool:
        """
        볼린저 스퀴즈 판정 (밴드 폭이 좁아짐)

        Args:
            bandwidth: 볼린저 밴드 폭
            threshold: 스퀴즈 판정 임계값

        Returns:
            bool: 스퀴즈 여부
        """
        return bandwidth < threshold
