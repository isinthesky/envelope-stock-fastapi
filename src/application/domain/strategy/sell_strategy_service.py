# -*- coding: utf-8 -*-
"""
Sell Strategy Service - 매도 전략 서비스

기술적 지표 기반 매도 시그널 분석
- Phase 기반 선제적 매도 시그널
- 수익률 기반 동적 임계값
"""

import logging
from datetime import datetime
from decimal import Decimal

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.exceptions import StrategyError
from src.application.common.indicators import TechnicalIndicators
from src.application.domain.strategy.dto import (
    DynamicSellThresholdConfig,
    SELL_PHASE_INFO,
    SellPhaseEnum,
    SellSignalAnalysisDTO,
)
from src.application.domain.strategy.ohlcv_data_loader import OHLCVDataLoader


logger = logging.getLogger(__name__)


class SellStrategyService:
    """
    매도 전략 서비스

    기술적 지표를 분석하여 매도 시그널을 판단합니다.
    - Phase 기반 선제적 매도 시그널
    - 수익률 기반 동적 임계값
    """

    def __init__(
        self,
        session: AsyncSession | None = None,
        dynamic_config: DynamicSellThresholdConfig | None = None,
    ) -> None:
        """
        Args:
            session: Database Session
            dynamic_config: 수익률 기반 동적 임계값 설정
        """
        self.session = session
        self._data_loader: OHLCVDataLoader | None = None
        self.dynamic_config = dynamic_config or DynamicSellThresholdConfig()

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
        entry_price: float | None = None,
        highest_price: float | None = None,
        trailing_stop_activated: bool = False,
    ) -> SellSignalAnalysisDTO:
        """
        매도 시그널 분석

        종목의 기술적 지표를 분석하여 매도 시그널을 판단합니다.
        - MA55/MA165 데드크로스 확인
        - Stochastic 과매수 확인
        - RSI 과매수 확인
        - Phase 기반 선제적 매도 시그널
        - 수익률 기반 동적 임계값

        Args:
            symbol: 종목코드
            stoch_overbought: Stochastic 과매수 임계값 (기본 70)
            rsi_overbought: RSI 과매수 임계값 (기본 70)
            entry_price: 진입가 (수익률 계산용)
            highest_price: 포지션 최고가 (트레일링 스탑용)
            trailing_stop_activated: 트레일링 스탑 활성화 여부

        Returns:
            SellSignalAnalysisDTO: 매도 시그널 분석 결과
        """
        analyzed_at = datetime.now()

        # 1. OHLCV 데이터 로딩
        data_loader = self._get_data_loader()

        try:
            df = await data_loader.load_ohlcv_dataframe(
                symbol=symbol,
                days=300,  # MA165 + 충분한 버퍼
                interval="1d",
                min_candles=165,
            )
        except ValueError as e:
            raise StrategyError(str(e))

        candle_count = len(df)

        # 2. 기술적 지표 계산 (MA55/MA165 + Stochastic)
        df = TechnicalIndicators.prepare_golden_cross_indicators(
            df,
            short_ma_period=55,
            long_ma_period=165,
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

        # 4. 기본 지표 계산
        is_gc_active = ma_short > ma_long
        is_death_cross = ma_short < ma_long
        ma_gap_ratio = ((ma_short - ma_long) / ma_long * 100) if ma_long > 0 else 0

        # 5. 수익률 계산 및 동적 임계값 적용
        profit_ratio: float | None = None
        dynamic_stoch = stoch_overbought
        dynamic_rsi = rsi_overbought
        is_stop_loss_triggered = False
        is_take_profit_triggered = False

        if entry_price is not None and entry_price > 0:
            profit_ratio = (close - entry_price) / entry_price

            # 긴급 손절 체크
            if profit_ratio <= self.dynamic_config.emergency_stop_ratio:
                is_stop_loss_triggered = True

            # 익절 목표 체크
            if profit_ratio >= self.dynamic_config.high_profit_threshold:
                is_take_profit_triggered = True

            # 동적 임계값 조정
            dynamic_stoch, dynamic_rsi = self._get_dynamic_thresholds(profit_ratio)

        # 6. 적용된 임계값으로 과매수 판정
        is_stoch_overbought = stoch_k > dynamic_stoch
        is_rsi_overbought = rsi > dynamic_rsi

        # 7. Phase 분석 (선제적 매도 시그널)
        sell_phase, phase_reasons = self._analyze_sell_phase(
            is_gc_active=is_gc_active,
            ma_gap_ratio=ma_gap_ratio,
            stoch_k=stoch_k,
            rsi=rsi,
        )

        # 8. 매도 근거 수집 및 점수 계산
        sell_reasons, sell_score = self._calculate_sell_score(
            is_death_cross=is_death_cross,
            is_stoch_overbought=is_stoch_overbought,
            is_rsi_overbought=is_rsi_overbought,
            ma_short=ma_short,
            ma_long=ma_long,
            stoch_k=stoch_k,
            stoch_overbought=dynamic_stoch,
            rsi=rsi,
            rsi_overbought=dynamic_rsi,
            ma_gap_ratio=ma_gap_ratio,
            profit_ratio=profit_ratio,
            is_stop_loss_triggered=is_stop_loss_triggered,
            is_take_profit_triggered=is_take_profit_triggered,
            sell_phase=sell_phase,
        )

        # Phase 근거 추가
        sell_reasons.extend(phase_reasons)

        # 점수를 0-5 범위로 제한
        sell_signal_strength = min(5, sell_score)

        # 추천 등급 결정
        sell_recommendation = self._get_recommendation(sell_signal_strength)

        if not sell_reasons:
            sell_reasons.append("현재 매도 시그널 없음 - 보유 유지")

        # 트레일링 스탑 관련 계산
        drawdown_from_high: float | None = None
        if highest_price is not None and highest_price > 0:
            drawdown_from_high = (highest_price - close) / highest_price

        # Phase 정보
        phase_info = SELL_PHASE_INFO.get(sell_phase.value, SELL_PHASE_INFO["NONE"])

        logger.info(
            f"[Sell Signal] {symbol}: phase={sell_phase.value}, strength={sell_signal_strength}, "
            f"recommendation={sell_recommendation}, profit_ratio={profit_ratio}"
        )

        return SellSignalAnalysisDTO(
            symbol=symbol,
            name=None,
            current_price=Decimal(str(close)),
            analyzed_at=analyzed_at,
            ma_short=Decimal(str(round(ma_short, 2))),
            ma_long=Decimal(str(round(ma_long, 2))),
            ma_gap_ratio=round(ma_gap_ratio, 2),
            is_death_cross=is_death_cross,
            is_gc_active=is_gc_active,
            stoch_k=round(stoch_k, 2),
            stoch_d=round(stoch_d, 2),
            is_stoch_overbought=is_stoch_overbought,
            rsi=round(rsi, 2),
            is_rsi_overbought=is_rsi_overbought,
            sell_signal_strength=sell_signal_strength,
            sell_recommendation=sell_recommendation,
            sell_reasons=sell_reasons,
            # Phase 관련
            sell_phase=sell_phase.value,
            sell_phase_name=phase_info["name"],
            sell_phase_action=phase_info["action"],
            # 수익률 관련
            entry_price=Decimal(str(entry_price)) if entry_price else None,
            profit_ratio=round(profit_ratio, 4) if profit_ratio is not None else None,
            dynamic_stoch_threshold=round(dynamic_stoch, 1),
            dynamic_rsi_threshold=round(dynamic_rsi, 1),
            # 손절/익절 상태
            is_stop_loss_triggered=is_stop_loss_triggered,
            is_take_profit_triggered=is_take_profit_triggered,
            # 트레일링 스탑 관련
            highest_price=Decimal(str(highest_price)) if highest_price else None,
            drawdown_from_high=round(drawdown_from_high, 4) if drawdown_from_high is not None else None,
            trailing_stop_activated=trailing_stop_activated,
            candle_count=candle_count,
        )

    def _get_dynamic_thresholds(self, profit_ratio: float) -> tuple[float, float]:
        """
        수익률 기반 동적 매도 임계값 반환

        Args:
            profit_ratio: 현재 수익률

        Returns:
            tuple[float, float]: (stoch_threshold, rsi_threshold)
        """
        config = self.dynamic_config

        if profit_ratio >= config.high_profit_threshold:  # >= 20%
            return (config.high_profit_stoch, config.high_profit_rsi)  # (60, 65)
        elif profit_ratio >= config.mid_profit_threshold:  # >= 10%
            return (config.mid_profit_stoch, config.mid_profit_rsi)  # (65, 68)
        elif profit_ratio < 0:  # 손실
            return (config.loss_stoch, config.loss_rsi)  # (75, 75)
        else:  # 0% ~ 10%
            return (config.default_stoch, config.default_rsi)  # (70, 70)

    def _analyze_sell_phase(
        self,
        is_gc_active: bool,
        ma_gap_ratio: float,
        stoch_k: float,
        rsi: float,
    ) -> tuple[SellPhaseEnum, list[str]]:
        """
        Phase 기반 선제적 매도 시그널 분석

        Phase 조건:
        - PHASE_1: GC 유지 + Stoch > 85 + RSI > 80 (수익 보호)
        - PHASE_2: MA 갭 < 3% + Stoch > 75 + RSI > 70 (매도 준비)
        - PHASE_3: 데드크로스 + (Stoch > 70 OR RSI > 70) (매도 고려)
        - PHASE_4: 데드크로스 + Stoch > 80 + RSI > 75 (매도 권장)
        - PHASE_5: 데드크로스 + Stoch > 90 + RSI > 85 (강력 매도)

        Args:
            is_gc_active: 골든크로스 활성 여부
            ma_gap_ratio: MA 갭 비율 (%)
            stoch_k: Stochastic %K
            rsi: RSI

        Returns:
            tuple[SellPhaseEnum, list[str]]: (Phase, 근거 리스트)
        """
        reasons: list[str] = []
        is_death_cross = not is_gc_active

        # PHASE_5: 데드크로스 + 극단적 과열
        if is_death_cross and stoch_k > 90 and rsi > 85:
            reasons.append(f"[Phase 5] 데드크로스 + 극단적 과열 (Stoch {stoch_k:.1f}, RSI {rsi:.1f})")
            return SellPhaseEnum.PHASE_5, reasons

        # PHASE_4: 데드크로스 + 강한 과열
        if is_death_cross and stoch_k > 80 and rsi > 75:
            reasons.append(f"[Phase 4] 데드크로스 + 강한 과열 (Stoch {stoch_k:.1f}, RSI {rsi:.1f})")
            return SellPhaseEnum.PHASE_4, reasons

        # PHASE_3: 데드크로스 + 과열
        if is_death_cross and (stoch_k > 70 or rsi > 70):
            reasons.append(f"[Phase 3] 데드크로스 + 과열 (Stoch {stoch_k:.1f}, RSI {rsi:.1f})")
            return SellPhaseEnum.PHASE_3, reasons

        # PHASE_2: MA 갭 축소 + 과열 (데드크로스 임박)
        if is_gc_active and 0 < ma_gap_ratio < 3 and stoch_k > 75 and rsi > 70:
            reasons.append(f"[Phase 2] MA 갭 축소 ({ma_gap_ratio:.1f}%) + 과열 - 데드크로스 임박")
            return SellPhaseEnum.PHASE_2, reasons

        # PHASE_1: GC 유지 + 극심한 과열 (수익 보호)
        if is_gc_active and stoch_k > 85 and rsi > 80:
            reasons.append(f"[Phase 1] 골든크로스 유지 + 극심한 과열 (Stoch {stoch_k:.1f}, RSI {rsi:.1f})")
            return SellPhaseEnum.PHASE_1, reasons

        return SellPhaseEnum.NONE, reasons

    def _calculate_sell_score(
        self,
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
        profit_ratio: float | None = None,
        is_stop_loss_triggered: bool = False,
        is_take_profit_triggered: bool = False,
        sell_phase: SellPhaseEnum = SellPhaseEnum.NONE,
    ) -> tuple[list[str], int]:
        """
        매도 점수 및 근거 계산

        Returns:
            tuple[list[str], int]: (매도 근거 리스트, 매도 점수)
        """
        sell_reasons: list[str] = []
        sell_score = 0

        # 긴급 손절 (최우선)
        if is_stop_loss_triggered:
            sell_reasons.append(f"손절 라인 도달 (수익률 {profit_ratio * 100:.1f}% <= -7%)")
            return sell_reasons, 5  # 강력 매도

        # Phase 기반 점수
        phase_scores = {
            SellPhaseEnum.PHASE_1: 2,
            SellPhaseEnum.PHASE_2: 3,
            SellPhaseEnum.PHASE_3: 3,
            SellPhaseEnum.PHASE_4: 4,
            SellPhaseEnum.PHASE_5: 5,
        }
        if sell_phase in phase_scores:
            sell_score = phase_scores[sell_phase]

        # 데드크로스 (강력 매도 시그널)
        if is_death_cross:
            sell_reasons.append(f"데드크로스 발생 (MA55 {ma_short:,.0f} < MA165 {ma_long:,.0f})")
            if sell_phase == SellPhaseEnum.NONE:
                sell_score += 2

        # Stochastic 과매수
        if is_stoch_overbought:
            sell_reasons.append(f"Stochastic 과매수 (K={stoch_k:.1f} > {stoch_overbought})")
            if sell_phase == SellPhaseEnum.NONE:
                sell_score += 1
            if stoch_k > 80:
                sell_reasons.append("Stochastic 극단적 과매수 (K > 80)")
                if sell_phase == SellPhaseEnum.NONE:
                    sell_score += 1

        # RSI 과매수
        if is_rsi_overbought:
            sell_reasons.append(f"RSI 과매수 (RSI={rsi:.1f} > {rsi_overbought})")
            if sell_phase == SellPhaseEnum.NONE:
                sell_score += 1
            if rsi > 80:
                sell_reasons.append("RSI 극단적 과매수 (RSI > 80)")
                if sell_phase == SellPhaseEnum.NONE:
                    sell_score += 1

        # Stochastic + RSI 동시 과매수
        if is_stoch_overbought and is_rsi_overbought:
            sell_reasons.append("Stochastic & RSI 동시 과매수 - 고점 가능성 높음")

        # MA 갭이 너무 벌어진 경우 (과열)
        if ma_gap_ratio > 20:
            sell_reasons.append(f"MA 갭 과대 ({ma_gap_ratio:.1f}%) - 평균 회귀 예상")
            if sell_phase == SellPhaseEnum.NONE:
                sell_score += 1

        # 수익률 관련 정보
        if profit_ratio is not None:
            profit_pct = profit_ratio * 100
            if is_take_profit_triggered:
                sell_reasons.append(f"익절 목표 도달 (수익률 {profit_pct:.1f}% >= 20%)")
            elif profit_ratio > 0:
                sell_reasons.append(f"현재 수익률: {profit_pct:.1f}%")
            else:
                sell_reasons.append(f"현재 손실률: {profit_pct:.1f}%")

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
