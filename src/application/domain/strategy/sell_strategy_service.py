# -*- coding: utf-8 -*-
"""
Sell Strategy Service - 매도 전략 서비스

기술적 지표 기반 매도 시그널 분석
"""

import logging
from datetime import datetime
from decimal import Decimal

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.exceptions import StrategyError
from src.application.common.indicators import TechnicalIndicators
from src.application.domain.strategy.dto import SellSignalAnalysisDTO
from src.application.domain.strategy.ohlcv_data_loader import OHLCVDataLoader


logger = logging.getLogger(__name__)


class SellStrategyService:
    """
    매도 전략 서비스

    기술적 지표를 분석하여 매도 시그널을 판단합니다.
    """

    def __init__(self, session: AsyncSession | None = None) -> None:
        """
        Args:
            session: Database Session
        """
        self.session = session
        self._data_loader: OHLCVDataLoader | None = None

    def _get_data_loader(self) -> OHLCVDataLoader:
        """OHLCVDataLoader 인스턴스 반환"""
        if self._data_loader is None:
            self._data_loader = OHLCVDataLoader(self.session)
        return self._data_loader

    async def analyze_sell_signal(
        self,
        symbol: str,
        stoch_overbought: float = 70.0,
        rsi_overbought: float = 70.0,
    ) -> SellSignalAnalysisDTO:
        """
        매도 시그널 분석

        종목의 기술적 지표를 분석하여 매도 시그널을 판단합니다.
        - MA40/MA160 데드크로스 확인
        - Stochastic 과매수 확인
        - RSI 과매수 확인

        Args:
            symbol: 종목코드
            stoch_overbought: Stochastic 과매수 임계값 (기본 70)
            rsi_overbought: RSI 과매수 임계값 (기본 70)

        Returns:
            SellSignalAnalysisDTO: 매도 시그널 분석 결과
        """
        analyzed_at = datetime.now()

        # 1. OHLCV 데이터 로딩
        data_loader = self._get_data_loader()

        try:
            df = await data_loader.load_ohlcv_dataframe(
                symbol=symbol,
                days=240,
                interval="1d",
                min_candles=160,
            )
        except ValueError as e:
            raise StrategyError(str(e))

        candle_count = len(df)

        # 2. 기술적 지표 계산 (MA40/MA160 + Stochastic)
        df = TechnicalIndicators.prepare_golden_cross_indicators(
            df,
            short_ma_period=40,
            long_ma_period=160,
            stoch_k_period=14,
            stoch_d_period=3,
        )

        # RSI 계산 추가
        close_prices = df["close"].tolist()
        rsi_value = TechnicalIndicators.calculate_rsi(close_prices, period=14)
        df["rsi"] = rsi_value if rsi_value is not None else 50.0

        # 3. 최신 값 추출
        latest = df.iloc[-1]
        close = float(latest["close"])
        ma_short = float(latest["ma_short"]) if pd.notna(latest["ma_short"]) else 0
        ma_long = float(latest["ma_long"]) if pd.notna(latest["ma_long"]) else 0
        stoch_k = float(latest["stoch_k"]) if pd.notna(latest["stoch_k"]) else 50
        stoch_d = float(latest["stoch_d"]) if pd.notna(latest["stoch_d"]) else 50
        rsi = float(latest["rsi"]) if pd.notna(latest["rsi"]) else 50

        # 4. 매도 시그널 판단
        is_death_cross = ma_short < ma_long
        is_stoch_overbought = stoch_k > stoch_overbought
        is_rsi_overbought = rsi > rsi_overbought
        ma_gap_ratio = ((ma_short - ma_long) / ma_long * 100) if ma_long > 0 else 0

        # 5. 매도 근거 수집 및 점수 계산
        sell_reasons, sell_score = self._calculate_sell_score(
            is_death_cross=is_death_cross,
            is_stoch_overbought=is_stoch_overbought,
            is_rsi_overbought=is_rsi_overbought,
            ma_short=ma_short,
            ma_long=ma_long,
            stoch_k=stoch_k,
            stoch_overbought=stoch_overbought,
            rsi=rsi,
            rsi_overbought=rsi_overbought,
            ma_gap_ratio=ma_gap_ratio,
        )

        # 점수를 0-5 범위로 제한
        sell_signal_strength = min(5, sell_score)

        # 추천 등급 결정
        sell_recommendation = self._get_recommendation(sell_signal_strength)

        if not sell_reasons:
            sell_reasons.append("현재 매도 시그널 없음 - 보유 유지")

        logger.info(
            f"[Sell Signal] {symbol}: strength={sell_signal_strength}, "
            f"recommendation={sell_recommendation}, reasons={len(sell_reasons)}"
        )

        return SellSignalAnalysisDTO(
            symbol=symbol,
            name=None,  # 종목명은 별도 조회 필요
            current_price=Decimal(str(close)),
            analyzed_at=analyzed_at,
            ma_short=Decimal(str(round(ma_short, 2))),
            ma_long=Decimal(str(round(ma_long, 2))),
            ma_gap_ratio=round(ma_gap_ratio, 2),
            is_death_cross=is_death_cross,
            stoch_k=round(stoch_k, 2),
            stoch_d=round(stoch_d, 2),
            is_stoch_overbought=is_stoch_overbought,
            rsi=round(rsi, 2),
            is_rsi_overbought=is_rsi_overbought,
            sell_signal_strength=sell_signal_strength,
            sell_recommendation=sell_recommendation,
            sell_reasons=sell_reasons,
            candle_count=candle_count,
        )

    @staticmethod
    def _calculate_sell_score(
        is_death_cross: bool,
        is_stoch_overbought: bool,
        is_rsi_overbought: bool,
        ma_short: float,
        ma_long: float,
        stoch_k: float,
        stoch_overbought: float,
        rsi: float,
        rsi_overbought: float,
        ma_gap_ratio: float,
    ) -> tuple[list[str], int]:
        """
        매도 점수 및 근거 계산

        Returns:
            tuple[list[str], int]: (매도 근거 리스트, 매도 점수)
        """
        sell_reasons: list[str] = []
        sell_score = 0

        # 데드크로스 (강력 매도 시그널)
        if is_death_cross:
            sell_reasons.append(f"데드크로스 발생 (MA40 {ma_short:,.0f} < MA160 {ma_long:,.0f})")
            sell_score += 2

        # Stochastic 과매수
        if is_stoch_overbought:
            sell_reasons.append(f"Stochastic 과매수 (K={stoch_k:.1f} > {stoch_overbought})")
            sell_score += 1
            if stoch_k > 80:
                sell_reasons.append("Stochastic 극단적 과매수 (K > 80)")
                sell_score += 1

        # RSI 과매수
        if is_rsi_overbought:
            sell_reasons.append(f"RSI 과매수 (RSI={rsi:.1f} > {rsi_overbought})")
            sell_score += 1
            if rsi > 80:
                sell_reasons.append("RSI 극단적 과매수 (RSI > 80)")
                sell_score += 1

        # Stochastic + RSI 동시 과매수 (추가 정보)
        if is_stoch_overbought and is_rsi_overbought:
            sell_reasons.append("Stochastic & RSI 동시 과매수 - 고점 가능성 높음")

        # MA 갭이 너무 벌어진 경우 (과열)
        if ma_gap_ratio > 20:
            sell_reasons.append(f"MA 갭 과대 ({ma_gap_ratio:.1f}%) - 평균 회귀 예상")
            sell_score += 1

        return sell_reasons, sell_score

    @staticmethod
    def _get_recommendation(sell_signal_strength: int) -> str:
        """매도 추천 등급 결정"""
        recommendation_map = {
            0: "HOLD",
            1: "WATCH",
            2: "WEAK_SELL",
            3: "CONSIDER_SELL",
            4: "SELL",
            5: "STRONG_SELL",
        }
        return recommendation_map.get(sell_signal_strength, "HOLD")
