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
    PHASE_TO_STAGE_MAP,
    SELL_PHASE_INFO,
    SELL_STAGE_INFO,
    SELL_STAGE_RATIOS,
    SellPhaseEnum,
    SellSignalAnalysisDTO,
    SellStageEnum,
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
        force_refresh: bool = False,
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
            force_refresh: True면 캐시와 관계없이 최신 데이터 요청

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
                force_refresh=force_refresh,
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

        # 2-1. 거래량 지표 계산
        volume_indicators = self._calculate_volume_indicators(df)

        # 2-2. ADX 지표 계산
        adx_indicators = self._calculate_adx_indicators(df, period=14)

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
            is_death_cross=is_death_cross,
            ma_gap_ratio=ma_gap_ratio,
            stoch_k=stoch_k,
            rsi=rsi,
        )

        # 7-1. 비중축소 Stage 결정
        sell_stage, stage_reasons = self._determine_sell_stage(
            sell_phase=sell_phase,
            is_death_cross=is_death_cross,
            is_gc_active=is_gc_active,
            stoch_k=stoch_k,
            rsi=rsi,
            ma_gap_ratio=ma_gap_ratio,
            adx=adx_indicators.get("adx"),
            plus_di=adx_indicators.get("plus_di"),
            minus_di=adx_indicators.get("minus_di"),
            is_volume_sell_signal=volume_indicators.get("is_volume_sell_signal", False),
            profit_ratio=profit_ratio,
            dynamic_stoch_threshold=dynamic_stoch,
            dynamic_rsi_threshold=dynamic_rsi,
        )

        # Stage 기반 매도 비율 계산
        sell_ratios = SELL_STAGE_RATIOS.get(sell_stage, (0.0, 0.0))
        sell_ratio_min, sell_ratio_max = sell_ratios

        # Stage 정보
        stage_info = SELL_STAGE_INFO.get(sell_stage.value, SELL_STAGE_INFO["HOLD"])

        # 과매수 매도 차단 여부 (ADX 강한 상승 추세)
        overbought_sell_blocked = (
            adx_indicators.get("is_strong_uptrend", False)
            and not is_death_cross
            and not volume_indicators.get("is_volume_sell_signal", False)
        )

        # 8. 매도 근거 수집
        sell_reasons = self._collect_sell_reasons(
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
        )

        # Phase 근거 추가
        sell_reasons.extend(phase_reasons)

        if not sell_reasons:
            sell_reasons.append("현재 매도 시그널 없음 - 보유 유지")

        # 트레일링 스탑 관련 계산
        drawdown_from_high: float | None = None
        if highest_price is not None and highest_price > 0:
            drawdown_from_high = (highest_price - close) / highest_price

        # Phase 정보
        phase_info = SELL_PHASE_INFO.get(sell_phase.value, SELL_PHASE_INFO["NONE"])

        logger.info(
            f"[Sell Signal] {symbol}: phase={sell_phase.value}, stage={sell_stage.value}, "
            f"phase_name={phase_info['name']}, profit_ratio={profit_ratio}, "
            f"adx={adx_indicators.get('adx')}, volume_spike={volume_indicators.get('is_volume_spike')}"
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
            # Phase 기반 매도 시그널
            sell_phase=sell_phase.value,
            sell_phase_name=phase_info["name"],
            sell_phase_action=phase_info["action"],
            sell_reasons=sell_reasons,
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
            # === 비중축소 관련 신규 필드 ===
            sell_stage=sell_stage.value,
            sell_stage_name=stage_info["name"],
            sell_ratio_min=sell_ratio_min,
            sell_ratio_max=sell_ratio_max,
            sell_quantity_suggested=None,  # 보유 수량 정보가 있을 때 별도 계산
            holding_quantity=None,  # 보유 수량은 외부에서 제공
            sold_ratio=0.0,
            sell_stage_reasons=stage_reasons,
            # === 거래량 관련 신규 필드 ===
            current_volume=volume_indicators.get("current_volume"),
            prev_volume=volume_indicators.get("prev_volume"),
            volume_ma_20=volume_indicators.get("volume_ma_20"),
            volume_ratio=volume_indicators.get("volume_ratio"),
            is_volume_spike=volume_indicators.get("is_volume_spike", False),
            price_drop_ratio=volume_indicators.get("price_drop_ratio"),
            is_volume_sell_signal=volume_indicators.get("is_volume_sell_signal", False),
            volume_sell_reasons=volume_indicators.get("volume_sell_reasons", []),
            # === ADX 관련 신규 필드 ===
            adx=adx_indicators.get("adx"),
            plus_di=adx_indicators.get("plus_di"),
            minus_di=adx_indicators.get("minus_di"),
            is_strong_uptrend=adx_indicators.get("is_strong_uptrend", False),
            is_strong_downtrend=adx_indicators.get("is_strong_downtrend", False),
            overbought_sell_blocked=overbought_sell_blocked,
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
        is_death_cross: bool,
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
            is_gc_active: 골든크로스 활성 여부 (MA55 > MA165)
            is_death_cross: 데드크로스 여부 (MA55 < MA165)
            ma_gap_ratio: MA 갭 비율 (%)
            stoch_k: Stochastic %K
            rsi: RSI

        Returns:
            tuple[SellPhaseEnum, list[str]]: (Phase, 근거 리스트)

        Note:
            MA55 == MA165인 경우 is_gc_active=False, is_death_cross=False로 처리됨
        """
        reasons: list[str] = []

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

    def _collect_sell_reasons(
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
    ) -> list[str]:
        """
        매도 근거 수집

        Returns:
            list[str]: 매도 근거 리스트
        """
        sell_reasons: list[str] = []

        # 긴급 손절 (최우선)
        if is_stop_loss_triggered and profit_ratio is not None:
            sell_reasons.append(f"손절 라인 도달 (수익률 {profit_ratio * 100:.1f}% <= -7%)")
            return sell_reasons

        # 데드크로스
        if is_death_cross:
            sell_reasons.append(f"데드크로스 발생 (MA55 {ma_short:,.0f} < MA165 {ma_long:,.0f})")

        # Stochastic 과매수
        if is_stoch_overbought:
            sell_reasons.append(f"Stochastic 과매수 (K={stoch_k:.1f} > {stoch_overbought})")
            if stoch_k > 80:
                sell_reasons.append("Stochastic 극단적 과매수 (K > 80)")

        # RSI 과매수
        if is_rsi_overbought:
            sell_reasons.append(f"RSI 과매수 (RSI={rsi:.1f} > {rsi_overbought})")
            if rsi > 80:
                sell_reasons.append("RSI 극단적 과매수 (RSI > 80)")

        # Stochastic + RSI 동시 과매수
        if is_stoch_overbought and is_rsi_overbought:
            sell_reasons.append("Stochastic & RSI 동시 과매수 - 고점 가능성 높음")

        # MA 갭이 너무 벌어진 경우 (과열)
        if ma_gap_ratio > 20:
            sell_reasons.append(f"MA 갭 과대 ({ma_gap_ratio:.1f}%) - 평균 회귀 예상")

        # 수익률 관련 정보
        if profit_ratio is not None:
            profit_pct = profit_ratio * 100
            if is_take_profit_triggered:
                sell_reasons.append(f"익절 목표 도달 (수익률 {profit_pct:.1f}% >= 20%)")
            elif profit_ratio > 0:
                sell_reasons.append(f"현재 수익률: {profit_pct:.1f}%")
            else:
                sell_reasons.append(f"현재 손실률: {profit_pct:.1f}%")

        return sell_reasons

    def _calculate_volume_indicators(
        self,
        df: pd.DataFrame,
    ) -> dict[str, float | bool | list[str] | None]:
        """
        거래량 지표 계산

        Args:
            df: OHLCV 데이터프레임 (volume 컬럼 포함)

        Returns:
            dict: 거래량 관련 지표
        """
        result: dict[str, float | bool | list[str] | None] = {
            "current_volume": None,
            "prev_volume": None,
            "volume_ma_20": None,
            "volume_ratio": None,
            "is_volume_spike": False,
            "price_drop_ratio": None,
            "is_volume_sell_signal": False,
            "volume_sell_reasons": [],
        }

        if "volume" not in df.columns or len(df) < 21:
            return result

        volumes = df["volume"].tolist()
        closes = df["close"].tolist()

        # NaN/None 체크 및 안전한 형변환
        def safe_int(val: float | None) -> int | None:
            if val is None or pd.isna(val):
                return None
            return int(val)

        def safe_float(val: float | None) -> float:
            if val is None or pd.isna(val):
                return 0.0
            return float(val)

        current_volume = safe_int(volumes[-1])
        prev_volume = safe_int(volumes[-2]) if len(volumes) > 1 else None

        # 현재 거래량이 None이면 계산 불가
        if current_volume is None:
            return result

        current_price = safe_float(closes[-1])
        prev_price = safe_float(closes[-2]) if len(closes) > 1 else current_price

        # 거래량 MA20 계산 (NaN 필터링)
        valid_volumes = [safe_int(v) for v in volumes if safe_int(v) is not None]
        if len(valid_volumes) < 20:
            result["current_volume"] = current_volume
            result["prev_volume"] = prev_volume
            return result

        volume_ma_20 = TechnicalIndicators.calculate_volume_ma(
            valid_volumes, period=20
        )

        if volume_ma_20 is None or volume_ma_20 <= 0:
            result["current_volume"] = current_volume
            result["prev_volume"] = prev_volume
            return result

        # 거래량 비율 및 급증 여부
        volume_ratio = TechnicalIndicators.calculate_volume_ratio(
            current_volume, volume_ma_20
        )
        is_volume_spike = TechnicalIndicators.is_volume_spike(
            current_volume, volume_ma_20, threshold=1.3
        )

        # 거래량+하락 매도 신호 (ATR은 별도 계산 필요, 여기서는 None)
        is_signal, reasons = TechnicalIndicators.check_volume_sell_signal(
            current_price=current_price,
            prev_price=prev_price,
            current_volume=current_volume,
            volume_ma_20=volume_ma_20,
            atr=None,  # ATR은 ADX 계산에서 가져올 수 있으나 여기서는 생략
            volume_ratio_threshold=1.3,
            min_drop_ratio=0.005,
        )

        # 가격 하락률 계산
        price_drop_ratio = (prev_price - current_price) / prev_price if prev_price > 0 else 0

        result["current_volume"] = current_volume
        result["prev_volume"] = prev_volume
        result["volume_ma_20"] = round(volume_ma_20, 0)
        result["volume_ratio"] = round(volume_ratio, 2)
        result["is_volume_spike"] = is_volume_spike
        result["price_drop_ratio"] = round(price_drop_ratio, 4)
        result["is_volume_sell_signal"] = is_signal
        result["volume_sell_reasons"] = reasons

        return result

    def _calculate_adx_indicators(
        self,
        df: pd.DataFrame,
        period: int = 14,
    ) -> dict[str, float | bool | None]:
        """
        ADX 지표 계산

        Args:
            df: OHLCV 데이터프레임 (high, low, close 컬럼 포함)
            period: ADX 기간 (기본 14)

        Returns:
            dict: ADX 관련 지표
        """
        result: dict[str, float | bool | None] = {
            "adx": None,
            "plus_di": None,
            "minus_di": None,
            "is_strong_uptrend": False,
            "is_strong_downtrend": False,
        }

        # ADX 계산에는 최소 2*period+1 (29개) 캔들 필요
        min_required = 2 * period + 1
        if len(df) < min_required:
            logger.debug(f"ADX 계산 불가: 데이터 부족 ({len(df)} < {min_required})")
            return result

        high_prices = df["high"].tolist()
        low_prices = df["low"].tolist()
        close_prices = df["close"].tolist()

        adx_data = TechnicalIndicators.calculate_adx(
            high_prices=high_prices,
            low_prices=low_prices,
            close_prices=close_prices,
            period=period,
        )

        if adx_data is None:
            return result

        adx = adx_data.get("adx")
        plus_di = adx_data.get("plus_di")
        minus_di = adx_data.get("minus_di")

        result["adx"] = adx
        result["plus_di"] = plus_di
        result["minus_di"] = minus_di
        result["is_strong_uptrend"] = TechnicalIndicators.is_strong_uptrend(
            adx, plus_di, minus_di, adx_threshold=25.0
        )
        result["is_strong_downtrend"] = TechnicalIndicators.is_strong_downtrend(
            adx, plus_di, minus_di, adx_threshold=25.0
        )

        return result

    def _determine_sell_stage(
        self,
        sell_phase: SellPhaseEnum,
        is_death_cross: bool,
        is_gc_active: bool,
        stoch_k: float,
        rsi: float,
        ma_gap_ratio: float,
        adx: float | None,
        plus_di: float | None,
        minus_di: float | None,
        is_volume_sell_signal: bool,
        profit_ratio: float | None,
        dynamic_stoch_threshold: float = 70.0,
        dynamic_rsi_threshold: float = 70.0,
    ) -> tuple[SellStageEnum, list[str]]:
        """
        비중축소 Stage 결정 (기존 Phase와 별도)

        우선순위:
        1. 긴급 손절 (profit_ratio <= -7%) → EXIT_ALL
        2. 전량 청산 (데드크로스 + 거래량 급증) → EXIT_ALL
        3. 추세 붕괴 (데드크로스 + 극심한 과열) → EXIT_ALL
        4. ADX 추세 유지 필터 (강한 상승 추세) → HOLD
        5. 2차 축소 (데드크로스 + 과열) → REDUCE_2
        6. 1차 축소 (과열 초기 / 거래량 경고) → REDUCE_1
        7. 보유 유지 → HOLD

        Returns:
            tuple[SellStageEnum, list[str]]: (stage, reasons)
        """
        reasons: list[str] = []

        # === 1순위: 긴급 손절 (최우선) ===
        if profit_ratio is not None and profit_ratio <= -0.07:
            reasons.append(f"긴급 손절 (수익률 {profit_ratio * 100:.1f}%)")
            return SellStageEnum.EXIT_ALL, reasons

        # === 2순위: 추세 붕괴 - 전량 청산 ===
        if is_death_cross and is_volume_sell_signal:
            reasons.append("데드크로스 + 거래량 급증 하락")
            return SellStageEnum.EXIT_ALL, reasons

        if is_death_cross and stoch_k > 80 and rsi > 75:
            reasons.append("데드크로스 + 극심한 과열 (Stoch>80, RSI>75)")
            return SellStageEnum.EXIT_ALL, reasons

        # === 3순위: ADX 추세 유지 필터 ===
        # (손절/전량청산 이후에만 적용)
        is_strong_uptrend = False
        if adx is not None and plus_di is not None and minus_di is not None:
            is_strong_uptrend = adx > 25 and plus_di > minus_di
            if is_strong_uptrend and not is_death_cross and not is_volume_sell_signal:
                reasons.append(f"강한 상승 추세 유지 (ADX={adx:.1f}, +DI={plus_di:.1f} > -DI={minus_di:.1f})")
                return SellStageEnum.HOLD, reasons

        # === 4순위: 2차 비중 축소 (30~40%) ===
        if is_death_cross and (stoch_k > dynamic_stoch_threshold or rsi > dynamic_rsi_threshold):
            reasons.append(f"데드크로스 + 과열 (Stoch>{dynamic_stoch_threshold:.0f} OR RSI>{dynamic_rsi_threshold:.0f})")
            return SellStageEnum.REDUCE_2, reasons

        if is_volume_sell_signal and ma_gap_ratio < 3:
            reasons.append("거래량 급증 하락 + MA 갭 축소 (<3%)")
            return SellStageEnum.REDUCE_2, reasons

        # === 5순위: 1차 비중 축소 (20~30%) ===
        if is_gc_active and stoch_k > 85 and rsi > 80:
            reasons.append("GC 유지 + 극심한 과열 (수익 보호)")
            return SellStageEnum.REDUCE_1, reasons

        if ma_gap_ratio < 3 and ma_gap_ratio > 0 and stoch_k > 75 and rsi > 70:
            reasons.append("MA 갭 축소 + 과열 (데드크로스 임박)")
            return SellStageEnum.REDUCE_1, reasons

        if is_volume_sell_signal:
            reasons.append("거래량 급증 하락 감지")
            return SellStageEnum.REDUCE_1, reasons

        # === 6순위: 보유 유지 ===
        # 기존 Phase에서 매핑 (호환성)
        default_stage = PHASE_TO_STAGE_MAP.get(sell_phase, SellStageEnum.HOLD)
        if default_stage != SellStageEnum.HOLD:
            reasons.append(f"기존 Phase({sell_phase.value})에서 매핑")
            return default_stage, reasons

        return SellStageEnum.HOLD, reasons
