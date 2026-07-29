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
            closes: 종가 리스트 (highs, lows와 동일한 길이 필요)
            highs: 고가 리스트 (closes, lows와 동일한 길이 필요)
            lows: 저가 리스트 (closes, highs와 동일한 길이 필요)
            k_period: %K 계산 기간 (기본: 14)
            d_period: %D 계산 기간 (기본: 3)

        Returns:
            tuple[float | None, float | None]: (stoch_k, stoch_d)
        """
        if len(closes) != len(highs) or len(closes) != len(lows):
            return None, None

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
        short_period: int = 55,
        long_period: int = 165,
    ) -> tuple[pd.Series, pd.Series]:
        """
        이동평균 시리즈 계산

        Args:
            df: OHLCV 데이터프레임 (close 컬럼 필요)
            short_period: 단기 MA 기간 (기본: 55)
            long_period: 장기 MA 기간 (기본: 165)

        Returns:
            tuple[pd.Series, pd.Series]: (short_ma, long_ma)
        """
        short_ma = df["close"].rolling(window=short_period).mean()
        long_ma = df["close"].rolling(window=long_period).mean()

        return short_ma, long_ma

    @staticmethod
    def prepare_golden_cross_indicators(
        df: pd.DataFrame,
        short_ma_period: int = 55,
        long_ma_period: int = 165,
        stoch_k_period: int = 14,
        stoch_d_period: int = 3,
    ) -> pd.DataFrame:
        """
        골든크로스 전략에 필요한 모든 지표 계산

        Args:
            df: OHLCV 데이터프레임 (timestamp, open, high, low, close, volume)
            short_ma_period: 단기 MA 기간 (기본: 55)
            long_ma_period: 장기 MA 기간 (기본: 165)
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

    @staticmethod
    def calculate_atr(
        high_prices: list[float],
        low_prices: list[float],
        close_prices: list[float],
        period: int = 14,
    ) -> float | None:
        """
        ATR (Average True Range) 계산

        변동성을 측정하는 지표로, 동적 손절에 활용

        Args:
            high_prices: 고가 리스트
            low_prices: 저가 리스트
            close_prices: 종가 리스트
            period: ATR 기간 (기본: 14)

        Returns:
            float | None: ATR 값 (데이터 부족 시 None)
        """
        if len(high_prices) < period + 1 or len(low_prices) < period + 1 or len(close_prices) < period + 1:
            return None

        true_ranges = []
        for i in range(1, len(close_prices)):
            high = high_prices[i]
            low = low_prices[i]
            prev_close = close_prices[i - 1]

            # True Range = max(고가-저가, |고가-전일종가|, |저가-전일종가|)
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)

        if len(true_ranges) < period:
            return None

        # ATR = TR의 이동평균
        return sum(true_ranges[-period:]) / period

    @staticmethod
    def calculate_atr_from_ohlcv(
        ohlcv_data: list[dict],
        period: int = 14,
    ) -> float | None:
        """
        OHLCV 데이터에서 ATR 계산

        Args:
            ohlcv_data: OHLCV 딕셔너리 리스트 [{"high": ..., "low": ..., "close": ...}, ...]
            period: ATR 기간 (기본: 14)

        Returns:
            float | None: ATR 값
        """
        if len(ohlcv_data) < period + 1:
            return None

        high_prices = [d.get("high", d.get("high_price", 0)) for d in ohlcv_data]
        low_prices = [d.get("low", d.get("low_price", 0)) for d in ohlcv_data]
        close_prices = [d.get("close", d.get("close_price", 0)) for d in ohlcv_data]

        return TechnicalIndicators.calculate_atr(high_prices, low_prices, close_prices, period)

    @staticmethod
    def calculate_atr_stop_loss_price(
        entry_price: float,
        atr: float,
        multiplier: float = 2.0,
    ) -> float:
        """
        ATR 기반 손절가 계산

        Args:
            entry_price: 진입가
            atr: ATR 값
            multiplier: ATR 배수 (기본: 2.0)

        Returns:
            float: 손절가
        """
        return entry_price - (atr * multiplier)

    @staticmethod
    def calculate_atr_trailing_stop_price(
        highest_price: float,
        atr: float,
        multiplier: float = 2.0,
    ) -> float:
        """
        ATR 기반 트레일링 스톱가 계산

        Args:
            highest_price: 최고가
            atr: ATR 값
            multiplier: ATR 배수 (기본: 2.0)

        Returns:
            float: 트레일링 스톱가
        """
        return highest_price - (atr * multiplier)

    # ==================== Volume Indicators ====================

    @staticmethod
    def calculate_volume_ma(
        volumes: list[int],
        period: int = 20,
    ) -> float | None:
        """
        거래량 이동평균 계산

        Args:
            volumes: 거래량 리스트
            period: 이동평균 기간 (기본: 20)

        Returns:
            float | None: 거래량 이동평균
        """
        if len(volumes) < period:
            return None
        return sum(volumes[-period:]) / period

    @staticmethod
    def calculate_volume_ratio(
        current_volume: int,
        volume_ma: float,
    ) -> float:
        """
        거래량 비율 계산 (현재/평균)

        Args:
            current_volume: 현재 거래량
            volume_ma: 거래량 이동평균

        Returns:
            float: 거래량 비율
        """
        if volume_ma <= 0:
            return 0.0
        return current_volume / volume_ma

    @staticmethod
    def is_volume_spike(
        current_volume: int,
        volume_ma: float,
        threshold: float = 1.3,
    ) -> bool:
        """
        거래량 급증 여부 확인

        Args:
            current_volume: 현재 거래량
            volume_ma: 거래량 이동평균
            threshold: 급증 임계값 (기본: 1.3 = 130%)

        Returns:
            bool: 거래량 급증 여부
        """
        if volume_ma <= 0:
            return False
        return current_volume >= volume_ma * threshold

    @classmethod
    def check_volume_peak_signal(
        cls,
        current_price: float,
        prev_price: float,
        current_volume: int,
        volume_ma_20: float,
        price_change_threshold: float = 0.03,
    ) -> tuple[bool, float, list[str]]:
        """
        거래량 급증 + 급등 피크 신호 확인

        Args:
            current_price: 현재가
            prev_price: 전일 종가
            current_volume: 현재 거래량
            volume_ma_20: 20일 거래량 평균
            price_change_threshold: 급등 임계값 (기본: 3%)

        Returns:
            tuple[bool, float, list[str]]: (피크 신호 여부, 점수, 근거 리스트)
        """
        reasons: list[str] = []
        score = 0.0

        volume_ratio = cls.calculate_volume_ratio(current_volume, volume_ma_20)
        price_change = (current_price - prev_price) / prev_price if prev_price > 0 else 0.0

        if volume_ratio >= 5.0:
            score += 20.0
            reasons.append(f"거래량 폭증 ({volume_ratio:.2f}x)")
        elif volume_ratio >= 4.0:
            score += 15.0
            reasons.append(f"거래량 급증 ({volume_ratio:.2f}x)")
        elif volume_ratio >= 3.0:
            score += 10.0
            reasons.append(f"거래량 증가 ({volume_ratio:.2f}x)")

        is_peak = volume_ratio >= 3.0 and price_change >= price_change_threshold
        if is_peak:
            score += 5.0
            reasons.append(f"급등+급증 피크 신호 (가격 {price_change:.1%}↑)")

        return is_peak, score, reasons

    @classmethod
    def check_volume_sell_signal(
        cls,
        current_price: float,
        prev_price: float,
        current_volume: int,
        volume_ma_20: float,
        atr: float | None = None,
        volume_ratio_threshold: float = 1.3,
        min_drop_ratio: float = 0.005,
    ) -> tuple[bool, list[str]]:
        """
        거래량 기반 매도 신호 확인

        조건:
        1. 거래량 비율 >= threshold (기본 1.3, 20일 평균 대비 30% 이상)
        2. 종가 < 전일 종가 (하락)
        3. 하락폭 >= min_drop_ratio (기본 0.5%) 또는 ATR의 0.5배 이상

        Args:
            current_price: 현재가
            prev_price: 전일 종가
            current_volume: 현재 거래량
            volume_ma_20: 20일 거래량 평균
            atr: ATR 값 (선택)
            volume_ratio_threshold: 거래량 급증 임계값 (기본: 1.3)
            min_drop_ratio: 최소 하락폭 (기본: 0.005 = 0.5%)

        Returns:
            tuple[bool, list[str]]: (신호 여부, 근거 리스트)
        """
        reasons: list[str] = []

        # 거래량 비율 계산
        volume_ratio = cls.calculate_volume_ratio(current_volume, volume_ma_20)
        is_spike = volume_ratio >= volume_ratio_threshold

        # 하락 여부 및 하락폭 확인
        price_down = current_price < prev_price
        drop_ratio = (prev_price - current_price) / prev_price if prev_price > 0 else 0

        # ATR 기반 하락폭 또는 최소 하락폭 조건
        significant_drop = drop_ratio >= min_drop_ratio
        if atr and prev_price > 0:
            atr_ratio = atr / prev_price
            significant_drop = significant_drop or (drop_ratio >= atr_ratio * 0.5)

        # 최종 신호 판정
        is_signal = is_spike and price_down and significant_drop

        if is_signal:
            reasons.append(f"거래량 급증 ({volume_ratio:.1f}x) + 하락 ({drop_ratio*100:.2f}%)")

        return is_signal, reasons

    # ==================== ADX (Average Directional Index) ====================

    @staticmethod
    def calculate_adx_weakness_score(adx: float | None) -> tuple[float, str]:
        """
        ADX 약화 점수 계산

        Returns:
            tuple[float, str]: (점수, 상태 문자열)
        """
        if adx is None:
            return 0.0, "데이터 없음"
        if adx < 15:
            return 15.0, "매우 약함"
        if adx < 20:
            return 10.0, "약함"
        if adx < 25:
            return 5.0, "보통"
        return 0.0, "강함"

    @staticmethod
    def _wilder_smoothing(data: list[float], period: int) -> list[float]:
        """
        Wilder's Smoothing Method (지수이동평균의 변형)

        첫 번째 값: 단순평균
        이후: prev_smooth * (period-1)/period + current / period

        Args:
            data: 데이터 리스트
            period: 스무딩 기간

        Returns:
            list[float]: 스무딩된 값 리스트
        """
        if len(data) < period:
            return []

        result = []
        # 첫 번째 smoothed 값 = 첫 period개의 단순평균
        first_smooth = sum(data[:period]) / period
        result.append(first_smooth)

        # 이후 Wilder smoothing 적용
        for i in range(period, len(data)):
            smooth = result[-1] * (period - 1) / period + data[i] / period
            result.append(smooth)

        return result

    @classmethod
    def calculate_adx(
        cls,
        high_prices: list[float],
        low_prices: list[float],
        close_prices: list[float],
        period: int = 14,
    ) -> dict[str, float] | None:
        """
        ADX (Average Directional Index) 계산 - Wilder Smoothing 적용

        추세 강도를 측정하는 지표 (0~100)
        - ADX > 25: 강한 추세
        - ADX < 20: 추세 없음 (횡보)

        Args:
            high_prices: 고가 리스트
            low_prices: 저가 리스트
            close_prices: 종가 리스트
            period: ADX 기간 (기본: 14)

        Returns:
            dict[str, float] | None: {"adx": ADX, "plus_di": +DI, "minus_di": -DI}
            또는 데이터 부족 시 None
        """
        # 최소 데이터 요구: 2*period+1
        min_required = 2 * period + 1
        if len(close_prices) < min_required:
            return None

        # Step 1: TR, +DM, -DM 계산
        tr_list: list[float] = []
        plus_dm_list: list[float] = []
        minus_dm_list: list[float] = []

        for i in range(1, len(close_prices)):
            # True Range
            tr = max(
                high_prices[i] - low_prices[i],
                abs(high_prices[i] - close_prices[i - 1]),
                abs(low_prices[i] - close_prices[i - 1]),
            )
            tr_list.append(tr)

            # Directional Movement
            high_diff = high_prices[i] - high_prices[i - 1]
            low_diff = low_prices[i - 1] - low_prices[i]

            plus_dm = high_diff if high_diff > low_diff and high_diff > 0 else 0
            minus_dm = low_diff if low_diff > high_diff and low_diff > 0 else 0

            plus_dm_list.append(plus_dm)
            minus_dm_list.append(minus_dm)

        # Step 2: Wilder Smoothing 적용
        smoothed_tr = cls._wilder_smoothing(tr_list, period)
        smoothed_plus_dm = cls._wilder_smoothing(plus_dm_list, period)
        smoothed_minus_dm = cls._wilder_smoothing(minus_dm_list, period)

        if not smoothed_tr or smoothed_tr[-1] == 0:
            return None

        # Step 3: +DI, -DI, DX 계산 (인덱스 일관성 유지)
        plus_di_list: list[float] = []
        minus_di_list: list[float] = []
        dx_list: list[float] = []

        for i in range(len(smoothed_tr)):
            atr_val = smoothed_tr[i]

            # ATR이 0이면 DI를 0으로 처리 (skip 대신)
            if atr_val == 0:
                plus_di = 0.0
                minus_di = 0.0
            else:
                plus_di = (smoothed_plus_dm[i] / atr_val) * 100
                minus_di = (smoothed_minus_dm[i] / atr_val) * 100

            plus_di_list.append(plus_di)
            minus_di_list.append(minus_di)

            # DX 계산 (di_sum이 0이면 DX도 0)
            di_sum = plus_di + minus_di
            if di_sum > 0:
                dx = abs(plus_di - minus_di) / di_sum * 100
            else:
                dx = 0.0
            dx_list.append(dx)

        if len(dx_list) < period:
            return None

        # Step 4: ADX = DX의 Wilder Smoothing
        smoothed_dx = cls._wilder_smoothing(dx_list, period)

        if not smoothed_dx:
            return None

        # 마지막 유효한 +DI, -DI 값 (ADX와 동일 시점)
        # smoothed_dx의 길이는 len(dx_list) - period + 1
        # 마지막 ADX에 해당하는 DI 인덱스 = len(dx_list) - 1
        last_idx = len(plus_di_list) - 1

        return {
            "adx": round(smoothed_dx[-1], 2),
            "plus_di": round(plus_di_list[last_idx], 2),
            "minus_di": round(minus_di_list[last_idx], 2),
        }

    @classmethod
    def calculate_adx_from_ohlcv(
        cls,
        ohlcv_data: list[dict],
        period: int = 14,
    ) -> dict[str, float] | None:
        """
        OHLCV 데이터에서 ADX 계산

        Args:
            ohlcv_data: OHLCV 딕셔너리 리스트
            period: ADX 기간 (기본: 14)

        Returns:
            dict[str, float] | None: {"adx": ADX, "plus_di": +DI, "minus_di": -DI}
        """
        if len(ohlcv_data) < 2 * period + 1:
            return None

        high_prices = [d.get("high", d.get("high_price", 0)) for d in ohlcv_data]
        low_prices = [d.get("low", d.get("low_price", 0)) for d in ohlcv_data]
        close_prices = [d.get("close", d.get("close_price", 0)) for d in ohlcv_data]

        return cls.calculate_adx(high_prices, low_prices, close_prices, period)

    @staticmethod
    def is_strong_uptrend(
        adx: float | None,
        plus_di: float | None,
        minus_di: float | None,
        adx_threshold: float = 25.0,
    ) -> bool:
        """
        강한 상승 추세 여부 확인

        조건: ADX > threshold AND +DI > -DI

        Args:
            adx: ADX 값
            plus_di: +DI 값
            minus_di: -DI 값
            adx_threshold: ADX 임계값 (기본: 25)

        Returns:
            bool: 강한 상승 추세 여부
        """
        if adx is None or plus_di is None or minus_di is None:
            return False
        return adx > adx_threshold and plus_di > minus_di

    @staticmethod
    def is_strong_downtrend(
        adx: float | None,
        plus_di: float | None,
        minus_di: float | None,
        adx_threshold: float = 25.0,
    ) -> bool:
        """
        강한 하락 추세 여부 확인

        조건: ADX > threshold AND -DI > +DI

        Args:
            adx: ADX 값
            plus_di: +DI 값
            minus_di: -DI 값
            adx_threshold: ADX 임계값 (기본: 25)

        Returns:
            bool: 강한 하락 추세 여부
        """
        if adx is None or plus_di is None or minus_di is None:
            return False
        return adx > adx_threshold and minus_di > plus_di
