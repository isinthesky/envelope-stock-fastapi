# -*- coding: utf-8 -*-
"""
Technical Indicators - 기술적 지표 계산 모듈

Bollinger Band, Envelope, 이동평균 등 기술적 지표 계산
"""

from decimal import Decimal
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    pass


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

    @classmethod
    def generate_combined_signal(
        cls,
        current_price: float,
        bb_bands: dict[str, float | None],
        envelope_bands: dict[str, float | None],
        threshold: float = 0.001,
        use_strict_mode: bool = True,
    ) -> str:
        """
        볼린저 밴드 + 엔벨로프 결합 시그널 생성

        두 지표를 함께 활용하여 더 신뢰도 높은 매매 시그널 생성

        매수 조건:
        - 볼린저 밴드 하단 돌파 (과매도)
        - AND (strict mode) / OR (loose mode) 엔벨로프 하단 근처

        매도 조건:
        - 볼린저 밴드 상단 돌파 (과매수)
        - AND (strict mode) / OR (loose mode) 엔벨로프 상단 근처

        Args:
            current_price: 현재가
            bb_bands: 볼린저 밴드 {"upper", "middle", "lower"}
            envelope_bands: 엔벨로프 {"upper", "middle", "lower"}
            threshold: 돌파 판정 임계값 (기본: 0.1%)
            use_strict_mode: 엄격 모드 (두 지표 모두 만족해야 시그널 생성)

        Returns:
            str: "buy" (매수), "sell" (매도), "hold" (보유)
        """
        if (
            bb_bands["upper"] is None
            or bb_bands["lower"] is None
            or envelope_bands["upper"] is None
            or envelope_bands["lower"] is None
        ):
            return "hold"

        bb_upper: float = bb_bands["upper"]
        bb_lower: float = bb_bands["lower"]
        env_upper: float = envelope_bands["upper"]
        env_lower: float = envelope_bands["lower"]

        # 볼린저 밴드 시그널
        bb_oversold = current_price < bb_lower * (1 - threshold)
        bb_overbought = current_price > bb_upper * (1 + threshold)

        # 엔벨로프 시그널
        env_oversold = current_price < env_lower * (1 + threshold)
        env_overbought = current_price > env_upper * (1 - threshold)

        # 결합 시그널 생성
        if use_strict_mode:
            # 엄격 모드: 두 지표 모두 만족
            if bb_oversold and env_oversold:
                return "buy"
            if bb_overbought and env_overbought:
                return "sell"
        else:
            # 완화 모드: 하나라도 만족
            if bb_oversold or env_oversold:
                return "buy"
            if bb_overbought or env_overbought:
                return "sell"

        return "hold"

    @classmethod
    def get_signal_strength(
        cls,
        current_price: float,
        bb_bands: dict[str, float | None],
        envelope_bands: dict[str, float | None],
    ) -> dict[str, float]:
        """
        시그널 강도 계산

        현재가가 밴드에서 얼마나 벗어났는지 비율로 계산

        Args:
            current_price: 현재가
            bb_bands: 볼린저 밴드
            envelope_bands: 엔벨로프

        Returns:
            dict: {"bb_position": 볼린저 위치 (-1~1), "env_position": 엔벨로프 위치 (-1~1)}
        """
        if (
            bb_bands["upper"] is None
            or bb_bands["middle"] is None
            or bb_bands["lower"] is None
            or envelope_bands["upper"] is None
            or envelope_bands["middle"] is None
            or envelope_bands["lower"] is None
        ):
            return {"bb_position": 0.0, "env_position": 0.0}

        bb_middle: float = bb_bands["middle"]
        bb_upper: float = bb_bands["upper"]
        bb_lower: float = bb_bands["lower"]

        env_middle: float = envelope_bands["middle"]
        env_upper: float = envelope_bands["upper"]
        env_lower: float = envelope_bands["lower"]

        # 볼린저 밴드 포지션 (-1: 하단, 0: 중간, 1: 상단)
        if current_price >= bb_middle:
            bb_position = (current_price - bb_middle) / (bb_upper - bb_middle) if bb_upper != bb_middle else 0
        else:
            bb_position = (current_price - bb_middle) / (bb_middle - bb_lower) if bb_middle != bb_lower else 0

        # 엔벨로프 포지션
        if current_price >= env_middle:
            env_position = (current_price - env_middle) / (env_upper - env_middle) if env_upper != env_middle else 0
        else:
            env_position = (current_price - env_middle) / (env_middle - env_lower) if env_middle != env_lower else 0

        return {
            "bb_position": max(-2.0, min(2.0, bb_position)),  # -2 ~ 2 범위로 제한
            "env_position": max(-2.0, min(2.0, env_position)),
        }

    # ==================== Golden Cross Strategy Indicators ====================

    @staticmethod
    def calculate_stochastic(
        df: pd.DataFrame,
        k_period: int = 14,
        d_period: int = 3,
    ) -> tuple[pd.Series, pd.Series]:
        """
        Stochastic Oscillator 계산

        Args:
            df: OHLCV 데이터프레임 (high, low, close 컬럼 필요)
            k_period: %K 계산 기간 (기본: 14)
            d_period: %D 계산 기간 (기본: 3)

        Returns:
            tuple[pd.Series, pd.Series]: (stoch_k, stoch_d)
        """
        low_min = df["low"].rolling(window=k_period).min()
        high_max = df["high"].rolling(window=k_period).max()

        price_range = high_max - low_min
        price_range = price_range.where(price_range != 0)

        # %K = (현재가 - 최저가) / (최고가 - 최저가) * 100
        stoch_k = 100 * ((df["close"] - low_min) / price_range)
        stoch_k = stoch_k.fillna(50.0)

        # %D = %K의 이동평균
        stoch_d = stoch_k.rolling(window=d_period).mean()

        return stoch_k, stoch_d

    @staticmethod
    def calculate_stochastic_from_prices(
        closes: list[float],
        highs: list[float],
        lows: list[float],
        k_period: int = 14,
        d_period: int = 3,
    ) -> tuple[float | None, float | None]:
        """
        리스트 기반 Stochastic Oscillator 계산 (단일 값 반환)

        Args:
            closes: 종가 리스트
            highs: 고가 리스트
            lows: 저가 리스트
            k_period: %K 계산 기간 (기본: 14)
            d_period: %D 계산 기간 (기본: 3)

        Returns:
            tuple[float | None, float | None]: (stoch_k, stoch_d)
        """
        if len(closes) < k_period + d_period:
            return None, None

        df = pd.DataFrame({"close": closes, "high": highs, "low": lows})
        stoch_k, stoch_d = TechnicalIndicators.calculate_stochastic(df, k_period, d_period)

        return stoch_k.iloc[-1], stoch_d.iloc[-1]

    @staticmethod
    def detect_golden_cross(
        short_ma: pd.Series, long_ma: pd.Series
    ) -> pd.Series:
        """
        골든크로스 감지 (단기 MA가 장기 MA를 상향 돌파)

        Args:
            short_ma: 단기 이동평균 시리즈 (e.g., MA60)
            long_ma: 장기 이동평균 시리즈 (e.g., MA200)

        Returns:
            pd.Series: 골든크로스 발생 시점 True
        """
        prev_short = short_ma.shift(1)
        prev_long = long_ma.shift(1)

        # 전일: 단기 <= 장기 AND 금일: 단기 > 장기
        golden_cross = (prev_short <= prev_long) & (short_ma > long_ma)

        return golden_cross

    @staticmethod
    def detect_dead_cross(
        short_ma: pd.Series, long_ma: pd.Series
    ) -> pd.Series:
        """
        데드크로스 감지 (단기 MA가 장기 MA를 하향 돌파)

        Args:
            short_ma: 단기 이동평균 시리즈 (e.g., MA60)
            long_ma: 장기 이동평균 시리즈 (e.g., MA200)

        Returns:
            pd.Series: 데드크로스 발생 시점 True
        """
        prev_short = short_ma.shift(1)
        prev_long = long_ma.shift(1)

        # 전일: 단기 >= 장기 AND 금일: 단기 < 장기
        dead_cross = (prev_short >= prev_long) & (short_ma < long_ma)

        return dead_cross

    @staticmethod
    def is_golden_cross_active(short_ma: float, long_ma: float) -> bool:
        """
        현재 골든크로스 상태 확인 (단기 MA > 장기 MA)

        Args:
            short_ma: 단기 이동평균 값
            long_ma: 장기 이동평균 값

        Returns:
            bool: 골든크로스 활성 상태
        """
        return short_ma > long_ma

    @staticmethod
    def calculate_ma_series(
        df: pd.DataFrame,
        short_period: int = 60,
        long_period: int = 200,
    ) -> tuple[pd.Series, pd.Series]:
        """
        이동평균 시리즈 계산

        Args:
            df: OHLCV 데이터프레임 (close 컬럼 필요)
            short_period: 단기 MA 기간 (기본: 60)
            long_period: 장기 MA 기간 (기본: 200)

        Returns:
            tuple[pd.Series, pd.Series]: (short_ma, long_ma)
        """
        short_ma = df["close"].rolling(window=short_period).mean()
        long_ma = df["close"].rolling(window=long_period).mean()

        return short_ma, long_ma

    @staticmethod
    def prepare_golden_cross_indicators(
        df: pd.DataFrame,
        short_ma_period: int = 60,
        long_ma_period: int = 200,
        stoch_k_period: int = 14,
        stoch_d_period: int = 3,
    ) -> pd.DataFrame:
        """
        골든크로스 전략에 필요한 모든 지표 계산

        Args:
            df: OHLCV 데이터프레임 (timestamp, open, high, low, close, volume)
            short_ma_period: 단기 MA 기간 (기본: 60)
            long_ma_period: 장기 MA 기간 (기본: 200)
            stoch_k_period: Stochastic %K 기간 (기본: 14)
            stoch_d_period: Stochastic %D 기간 (기본: 3)

        Returns:
            pd.DataFrame: 지표가 추가된 데이터프레임
                - ma_short: 단기 이동평균
                - ma_long: 장기 이동평균
                - stoch_k: Stochastic %K
                - stoch_d: Stochastic %D
                - is_gc_active: 골든크로스 활성 상태
                - gc_signal: 골든크로스 발생 시그널
                - dc_signal: 데드크로스 발생 시그널
        """
        result_df = df.copy()

        # 이동평균 계산
        result_df["ma_short"] = result_df["close"].rolling(window=short_ma_period).mean()
        result_df["ma_long"] = result_df["close"].rolling(window=long_ma_period).mean()

        # Stochastic 계산
        stoch_k, stoch_d = TechnicalIndicators.calculate_stochastic(
            result_df, stoch_k_period, stoch_d_period
        )
        result_df["stoch_k"] = stoch_k
        result_df["stoch_d"] = stoch_d

        # 골든크로스/데드크로스 상태 및 시그널
        result_df["is_gc_active"] = result_df["ma_short"] > result_df["ma_long"]
        result_df["gc_signal"] = TechnicalIndicators.detect_golden_cross(
            result_df["ma_short"], result_df["ma_long"]
        )
        result_df["dc_signal"] = TechnicalIndicators.detect_dead_cross(
            result_df["ma_short"], result_df["ma_long"]
        )

        return result_df
