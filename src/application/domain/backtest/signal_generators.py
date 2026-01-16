# -*- coding: utf-8 -*-
"""
Signal Generators - 백테스트용 시그널 생성기

전략별 매수/매도 시그널 생성 로직
"""

from abc import ABC, abstractmethod
from decimal import Decimal

from src.application.common.indicators import TechnicalIndicators


class BaseSignalGenerator(ABC):
    """시그널 생성기 기본 클래스"""

    @abstractmethod
    def generate_signal(
        self,
        price_history: list[float],
        current_price: Decimal,
    ) -> str:
        """
        매매 시그널 생성

        Args:
            price_history: 가격 히스토리 (close 가격 리스트)
            current_price: 현재가

        Returns:
            str: "buy" (매수), "sell" (매도), "hold" (보유)
        """
        pass

    @property
    @abstractmethod
    def min_period(self) -> int:
        """최소 필요 기간"""
        pass

    def reset(self) -> None:
        """상태 초기화 (필요시 하위 클래스에서 오버라이드)"""
        pass


class BollingerEnvelopeSignalGenerator(BaseSignalGenerator):
    """
    볼린저밴드 + 엔벨로프 시그널 생성기 (기존 전략)
    """

    def __init__(
        self,
        bb_period: int = 20,
        bb_std_multiplier: float = 2.0,
        env_period: int = 20,
        env_percentage: float = 2.0,
        use_strict_mode: bool = True,
    ):
        self.bb_period = bb_period
        self.bb_std_multiplier = bb_std_multiplier
        self.env_period = env_period
        self.env_percentage = env_percentage
        self.use_strict_mode = use_strict_mode

    @property
    def min_period(self) -> int:
        return max(self.bb_period, self.env_period)

    def generate_signal(
        self,
        price_history: list[float],
        current_price: Decimal,
    ) -> str:
        if len(price_history) < self.min_period:
            return "hold"

        # 볼린저 밴드 계산
        bb_bands = TechnicalIndicators.calculate_bollinger_bands(
            price_history,
            period=self.bb_period,
            std_multiplier=self.bb_std_multiplier
        )

        # 엔벨로프 계산
        env_bands = TechnicalIndicators.calculate_envelope(
            price_history,
            period=self.env_period,
            percentage=self.env_percentage
        )

        # 결합 시그널 생성
        signal = TechnicalIndicators.generate_combined_signal(
            current_price=float(current_price),
            bb_bands=bb_bands,
            envelope_bands=env_bands,
            use_strict_mode=self.use_strict_mode
        )

        return signal


class GoldenCrossSignalGenerator(BaseSignalGenerator):
    """
    골든크로스 시그널 생성기 (MA55/MA165 + Stochastic)

    매수 조건:
    - MA55 > MA165 (골든크로스 활성)
    - Stochastic K < oversold_threshold (과매도)

    매도 조건:
    - MA55 < MA165 (데드크로스) 또는
    - Stochastic K > overbought_threshold (과매수)
    """

    def __init__(
        self,
        short_period: int = 55,
        long_period: int = 165,
        stoch_k_period: int = 14,
        stoch_d_period: int = 3,
        stoch_oversold: float = 30.0,
        stoch_overbought: float = 70.0,
        require_k_above_d_for_buy: bool = False,
        require_k_below_d_for_sell: bool = False,
    ):
        """
        Args:
            short_period: 단기 MA 기간 (기본 55)
            long_period: 장기 MA 기간 (기본 165)
            stoch_k_period: Stochastic K 기간
            stoch_d_period: Stochastic D 기간
            stoch_oversold: 과매도 임계값 (매수 시그널)
            stoch_overbought: 과매수 임계값 (매도 시그널)
            require_k_above_d_for_buy: 매수 시 K > D 조건 필수 여부
            require_k_below_d_for_sell: 매도 시 K < D 조건 필수 여부
        """
        self.short_period = short_period
        self.long_period = long_period
        self.stoch_k_period = stoch_k_period
        self.stoch_d_period = stoch_d_period
        self.stoch_oversold = stoch_oversold
        self.stoch_overbought = stoch_overbought
        self.require_k_above_d_for_buy = require_k_above_d_for_buy
        self.require_k_below_d_for_sell = require_k_below_d_for_sell

        # 상태 추적
        self._prev_stoch_k: float | None = None
        self._prev_stoch_d: float | None = None

    @property
    def min_period(self) -> int:
        # MA 계산에 필요한 최소 기간 (Stochastic은 이미 충분)
        return self.long_period

    def generate_signal(
        self,
        price_history: list[float],
        current_price: Decimal,
    ) -> str:
        if len(price_history) < self.min_period:
            return "hold"

        # MA 계산
        ma_short = self._calculate_sma(price_history, self.short_period)
        ma_long = self._calculate_sma(price_history, self.long_period)

        # Stochastic 계산
        stoch_k, stoch_d = self._calculate_stochastic(price_history)

        # 상태 판단
        is_gc_active = ma_short > ma_long  # 골든크로스 활성
        is_death_cross = ma_short < ma_long  # 데드크로스

        # 매도 시그널 (우선 체크)
        if self._should_sell(is_death_cross, stoch_k, stoch_d):
            return "sell"

        # 매수 시그널
        if self._should_buy(is_gc_active, stoch_k, stoch_d):
            return "buy"

        # 이전 값 업데이트
        self._prev_stoch_k = stoch_k
        self._prev_stoch_d = stoch_d

        return "hold"

    def _should_buy(
        self,
        is_gc_active: bool,
        stoch_k: float,
        stoch_d: float,
    ) -> bool:
        """매수 조건 확인"""
        if not is_gc_active:
            return False

        # Stochastic 과매도
        if stoch_k >= self.stoch_oversold:
            return False

        # K > D 조건 (옵션)
        if self.require_k_above_d_for_buy and stoch_k <= stoch_d:
            return False

        # 모멘텀 전환 확인 (K가 상승 중) - 제거: 너무 엄격한 조건
        # 골든크로스 + 과매도만으로 충분히 타이밍 포착 가능

        return True

    def _should_sell(
        self,
        is_death_cross: bool,
        stoch_k: float,
        stoch_d: float,
    ) -> bool:
        """매도 조건 확인"""
        # 데드크로스 발생 시 즉시 매도
        if is_death_cross:
            return True

        # Stochastic 과매수
        if stoch_k > self.stoch_overbought:
            # K < D 조건 (옵션)
            if self.require_k_below_d_for_sell and stoch_k >= stoch_d:
                return False
            return True

        return False

    def _calculate_sma(self, prices: list[float], period: int) -> float:
        """단순이동평균 계산"""
        if len(prices) < period:
            return 0.0
        return sum(prices[-period:]) / period

    def _calculate_stochastic(
        self,
        prices: list[float],
    ) -> tuple[float, float]:
        """Stochastic K, D 계산"""
        period = self.stoch_k_period
        d_period = self.stoch_d_period

        if len(prices) < period + d_period:
            return 50.0, 50.0

        # %K 계산
        k_values = []
        for i in range(d_period):
            idx = len(prices) - d_period + i
            window = prices[idx - period + 1:idx + 1]
            high = max(window)
            low = min(window)
            if high == low:
                k_values.append(50.0)
            else:
                k = (prices[idx] - low) / (high - low) * 100
                k_values.append(k)

        stoch_k = k_values[-1]
        stoch_d = sum(k_values) / len(k_values)

        return stoch_k, stoch_d

    def reset(self) -> None:
        """상태 초기화"""
        self._prev_stoch_k = None
        self._prev_stoch_d = None


class MA5BreakoutSignalGenerator(BaseSignalGenerator):
    """
    MA5 엔벨로프 상단 돌파 시그널 생성기

    매수 조건:
    - 5일선이 장기 이평선(300일)의 엔벨로프 상단(0.7%)을 돌파
    - 거래량이 평균 거래량의 일정 비율 이상

    매도 조건:
    - 5일선이 장기 이평선 엔벨로프 상단 아래로 하락
    - 또는 20일선 돌파 후 하락 반전 시
    """

    def __init__(
        self,
        short_ma_period: int = 5,
        long_ma_period: int = 300,
        envelope_percentage: float = 0.7,
        secondary_ma_period: int = 400,
        secondary_envelope_percentage: float = 0.7,
        volume_ma_period: int = 20,
        volume_ratio_threshold: float = 1.0,
        use_volume_filter: bool = True,
    ):
        """
        Args:
            short_ma_period: 단기 MA 기간 (기본 5일)
            long_ma_period: 장기 MA 기간 (기본 300일, 분홍선)
            envelope_percentage: 엔벨로프 % (기본 0.7%)
            secondary_ma_period: 보조 장기 MA 기간 (기본 400일, 검정선)
            secondary_envelope_percentage: 보조 엔벨로프 % (기본 0.7%)
            volume_ma_period: 거래량 이평 기간
            volume_ratio_threshold: 거래량 비율 임계값 (1.0 = 평균 이상)
            use_volume_filter: 거래량 필터 사용 여부
        """
        self.short_ma_period = short_ma_period
        self.long_ma_period = long_ma_period
        self.envelope_percentage = envelope_percentage
        self.secondary_ma_period = secondary_ma_period
        self.secondary_envelope_percentage = secondary_envelope_percentage
        self.volume_ma_period = volume_ma_period
        self.volume_ratio_threshold = volume_ratio_threshold
        self.use_volume_filter = use_volume_filter

        # 상태 추적
        self._prev_ma5_above_upper: bool = False
        self._entry_triggered: bool = False
        self._volume_history: list[float] = []

    @property
    def min_period(self) -> int:
        return max(self.long_ma_period, self.secondary_ma_period, self.volume_ma_period)

    def generate_signal(
        self,
        price_history: list[float],
        current_price: Decimal,
        volume: float | None = None,
    ) -> str:
        if len(price_history) < self.min_period:
            return "hold"

        # 거래량 히스토리 업데이트
        if volume is not None:
            self._volume_history.append(volume)

        # MA 계산
        ma5 = self._calculate_sma(price_history, self.short_ma_period)
        ma300 = self._calculate_sma(price_history, self.long_ma_period)

        # 엔벨로프 상단 계산 (300일선 기준)
        upper_300 = ma300 * (1 + self.envelope_percentage / 100)

        # 현재 상태 판단
        ma5_above_upper_300 = ma5 > upper_300
        price_above_upper_300 = float(current_price) > upper_300

        # 매도 시그널 (우선 체크)
        if self._entry_triggered:
            # 5일선이 상단 아래로 하락하면 매도
            if not ma5_above_upper_300:
                self._entry_triggered = False
                self._prev_ma5_above_upper = False
                return "sell"

        # 매수 시그널: 5일선이 300일선 0.7% 상단 돌파
        if not self._prev_ma5_above_upper and ma5_above_upper_300:
            # 거래량 필터 체크
            if self.use_volume_filter:
                if not self._check_volume_condition():
                    self._prev_ma5_above_upper = ma5_above_upper_300
                    return "hold"

            # 현재가도 상단 위에 있어야 함
            if price_above_upper_300:
                self._prev_ma5_above_upper = ma5_above_upper_300
                self._entry_triggered = True
                return "buy"

        # 이전 상태 업데이트
        self._prev_ma5_above_upper = ma5_above_upper_300

        return "hold"

    def _calculate_sma(self, prices: list[float], period: int) -> float:
        """단순이동평균 계산"""
        if len(prices) < period:
            return 0.0
        return sum(prices[-period:]) / period

    def _check_volume_condition(self) -> bool:
        """거래량 조건 확인"""
        if len(self._volume_history) < self.volume_ma_period:
            return True  # 데이터 부족 시 통과

        avg_volume = sum(self._volume_history[-self.volume_ma_period:]) / self.volume_ma_period
        current_volume = self._volume_history[-1] if self._volume_history else 0

        return current_volume >= avg_volume * self.volume_ratio_threshold

    def update_volume(self, volume: float) -> None:
        """거래량 업데이트 (외부에서 호출)"""
        self._volume_history.append(volume)

    def reset(self) -> None:
        """상태 초기화"""
        self._prev_ma5_above_upper = False
        self._entry_triggered = False
        self._volume_history.clear()


def create_signal_generator(
    strategy_type: str,
    **kwargs,
) -> BaseSignalGenerator:
    """
    전략 유형에 따른 시그널 생성기 팩토리

    Args:
        strategy_type: 전략 유형 ("golden_cross", "mean_reversion", "ma5_breakout" 등)
        **kwargs: 전략별 설정 파라미터

    Returns:
        BaseSignalGenerator: 시그널 생성기 인스턴스
    """
    if strategy_type == "golden_cross":
        return GoldenCrossSignalGenerator(
            short_period=kwargs.get("short_period", 55),
            long_period=kwargs.get("long_period", 165),
            stoch_k_period=kwargs.get("stoch_k_period", 14),
            stoch_d_period=kwargs.get("stoch_d_period", 3),
            stoch_oversold=kwargs.get("stoch_oversold", 30.0),
            stoch_overbought=kwargs.get("stoch_overbought", 70.0),
            require_k_above_d_for_buy=kwargs.get("require_k_above_d_for_buy", False),
            require_k_below_d_for_sell=kwargs.get("require_k_below_d_for_sell", False),
        )
    elif strategy_type == "ma5_breakout":
        return MA5BreakoutSignalGenerator(
            short_ma_period=kwargs.get("short_ma_period", 5),
            long_ma_period=kwargs.get("long_ma_period", 300),
            envelope_percentage=kwargs.get("envelope_percentage", 0.7),
            secondary_ma_period=kwargs.get("secondary_ma_period", 400),
            secondary_envelope_percentage=kwargs.get("secondary_envelope_percentage", 0.7),
            volume_ma_period=kwargs.get("volume_ma_period", 20),
            volume_ratio_threshold=kwargs.get("volume_ratio_threshold", 1.0),
            use_volume_filter=kwargs.get("use_volume_filter", True),
        )
    else:
        # 기본: 볼린저밴드 + 엔벨로프
        return BollingerEnvelopeSignalGenerator(
            bb_period=kwargs.get("bb_period", 20),
            bb_std_multiplier=kwargs.get("bb_std_multiplier", 2.0),
            env_period=kwargs.get("env_period", 20),
            env_percentage=kwargs.get("env_percentage", 2.0),
            use_strict_mode=kwargs.get("use_strict_mode", True),
        )
