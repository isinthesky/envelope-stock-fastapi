# -*- coding: utf-8 -*-
"""
Sell Strategy Service - 매도 전략 서비스

기술적 지표 기반 매도 시그널 분석
- Phase 기반 선제적 매도 시그널
- 수익률 기반 동적 임계값
"""

import logging
import math
from dataclasses import asdict
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
    SellScoreResultDTO,
    SellStageEnum,
)
from src.application.domain.strategy.ohlcv_data_loader import OHLCVDataLoader
from src.application.domain.strategy.sell_rule_research_service import SellPeakRuleResearchService
from src.settings.sell_score_settings import SellScoreSettings
from src.adapters.external.kofia_client import MarketCreditTrendData, get_kofia_client
from src.adapters.external.naver.stock_client import StockPersonalFlowData, get_naver_stock_client


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
        sell_score_settings: SellScoreSettings | None = None,
    ) -> None:
        """
        Args:
            session: Database Session
            dynamic_config: 수익률 기반 동적 임계값 설정
        """
        self.session = session
        self._data_loader: OHLCVDataLoader | None = None
        self.dynamic_config = dynamic_config or DynamicSellThresholdConfig()
        self.sell_score_settings = sell_score_settings or SellScoreSettings()

    def _get_data_loader(self) -> OHLCVDataLoader:
        """OHLCVDataLoader 인스턴스 반환"""
        if self._data_loader is None:
            self._data_loader = OHLCVDataLoader(self.session)
        return self._data_loader

    async def _get_personal_flow_data(self, symbol: str) -> StockPersonalFlowData | None:
        """네이버 dealTrend 기반 개인 수급 데이터 조회"""
        try:
            return await get_naver_stock_client().get_personal_flow_data(symbol)
        except Exception:
            logger.debug("[Sell Signal] failed to fetch personal flow for %s", symbol, exc_info=True)
            return None

    async def _get_market_credit_trend(
        self,
        market: str | None,
    ) -> MarketCreditTrendData | None:
        """KOFIA 기반 시장 신용 과열 데이터 조회"""
        market_label = "전체"
        if (market or "").upper() == "KOSPI":
            market_label = "유가증권"
        elif (market or "").upper() == "KOSDAQ":
            market_label = "코스닥"

        try:
            return await get_kofia_client().get_market_credit_trend(
                start_date="20260101",
                end_date=datetime.now().strftime("%Y%m%d"),
                market_label=market_label,
            )
        except Exception:
            logger.debug("[Sell Signal] failed to fetch market credit trend for %s", market, exc_info=True)
            return None

    def _is_personal_buying_overheated(
        self,
        personal_flow_data: StockPersonalFlowData | None,
    ) -> tuple[bool, list[str]]:
        """개인 수급 과열 여부 판단"""
        if personal_flow_data is None:
            return False, []

        config = self.sell_score_settings
        reasons: list[str] = []
        ratio = personal_flow_data.recent_5d_buy_ratio_to_volume
        positive_days = personal_flow_data.days_positive_count
        recent_5d_net_buy = personal_flow_data.recent_5d_net_buy

        if positive_days >= config.personal_buy_days_threshold and recent_5d_net_buy > 0:
            reasons.append(
                f"개인 순매수 집중 ({positive_days}/5일, 5일 합계 {recent_5d_net_buy:,}주)"
            )

        if ratio is not None:
            if ratio >= config.personal_buy_ratio_high:
                reasons.append(f"개인 매수 과열 비중 높음 ({ratio * 100:.1f}% of 최근 거래량)")
            elif ratio >= config.personal_buy_ratio_mid:
                reasons.append(f"개인 매수 비중 확대 ({ratio * 100:.1f}% of 최근 거래량)")

        return len(reasons) >= 2, reasons

    @staticmethod
    def _upgrade_stage_for_overlay(
        stage: SellStageEnum,
        is_triggered: bool,
        label: str,
    ) -> tuple[SellStageEnum, list[str]]:
        """오버레이 신호가 켜지면 Stage를 한 단계 강화한다."""
        if not is_triggered:
            return stage, []

        stage_order = [
            SellStageEnum.HOLD,
            SellStageEnum.REDUCE_1,
            SellStageEnum.REDUCE_2,
            SellStageEnum.EXIT_ALL,
        ]
        current_index = stage_order.index(stage)
        upgraded_stage = stage_order[min(current_index + 1, len(stage_order) - 1)]

        if upgraded_stage == stage:
            return stage, []

        return upgraded_stage, [
            f"{label}로 Stage 한 단계 강화 ({stage.value} → {upgraded_stage.value})"
        ]

    async def _get_symbol_hints(
        self,
        symbol: str,
        name: str | None = None,
        market: str | None = None,
    ) -> tuple[str | None, str | None]:
        """유니버스에서 종목명/시장 힌트를 보강한다."""
        if self.session is None or (name and market):
            return name, market

        try:
            from src.adapters.database.repositories.stock_universe_repository import (
                StockUniverseRepository,
            )

            stock = await StockUniverseRepository(self.session).get_by_symbol(
                symbol, session=self.session
            )
            if stock:
                return name or stock.name, market or stock.market
        except Exception:
            logger.debug(
                "[Sell Signal] failed to resolve symbol hints for %s",
                symbol,
                exc_info=True,
            )

        return name, market

    @staticmethod
    def _is_nan(value: float | None) -> bool:
        """float NaN 여부 확인"""
        return value is not None and math.isnan(value)

    @staticmethod
    def infer_instrument_profile(
        symbol: str,
        name: str | None = None,
        market: str | None = None,
    ) -> dict[str, bool]:
        """심볼/종목명/시장 힌트만으로 ETF 계열 여부를 보수적으로 추정한다."""
        _ = symbol
        normalized_name = (name or "").upper().replace(" ", "")
        normalized_market = (market or "").upper()

        leveraged_keywords = (
            "레버리지",
            "2X",
            "3X",
            "2배",
            "3배",
            "인버스",
            "INVERSE",
        )
        etf_keywords = ("ETF", "ETN")

        is_leveraged_etf_like = any(
            keyword in normalized_name for keyword in leveraged_keywords
        )
        is_etf_like = (
            normalized_market == "ETF"
            or any(keyword in normalized_name for keyword in etf_keywords)
            or is_leveraged_etf_like
        )

        return {
            "is_etf_like": is_etf_like,
            "is_leveraged_etf_like": is_leveraged_etf_like,
        }

    def _check_stoch_dead_cross(
        self,
        stoch_k: float,
        stoch_d: float,
        prev_stoch_k: float | None = None,
        prev_stoch_d: float | None = None,
    ) -> tuple[bool, float, str]:
        """Stochastic 데드크로스 확인"""
        is_dead_cross = stoch_k < stoch_d

        prev_k_valid = (
            prev_stoch_k is not None
            and not self._is_nan(prev_stoch_k)
            and prev_stoch_d is not None
            and not self._is_nan(prev_stoch_d)
        )

        is_fresh_cross = False
        if prev_k_valid:
            is_fresh_cross = prev_stoch_k >= prev_stoch_d and stoch_k < stoch_d

        if is_fresh_cross:
            return True, 10.0, f"Stoch 데드크로스 발생 (K={stoch_k:.1f} < D={stoch_d:.1f})"
        if is_dead_cross:
            return True, 5.0, f"Stoch 데드크로스 상태 (K={stoch_k:.1f} < D={stoch_d:.1f})"
        return False, 0.0, f"Stoch 골든크로스 (K={stoch_k:.1f} ≥ D={stoch_d:.1f})"

    def _calculate_stochastic_indicators(
        self,
        df: pd.DataFrame,
        min_candles: int = 17,
    ) -> dict[str, float | bool | str | None]:
        """Stochastic 지표 계산 (이전 값 포함)"""
        result: dict[str, float | bool | str | None] = {
            "stoch_k": None,
            "stoch_d": None,
            "prev_stoch_k": None,
            "prev_stoch_d": None,
            "is_stoch_dead_cross": False,
            "stoch_cross_score": 0.0,
            "stoch_cross_reason": None,
            "stoch_cross_type": "insufficient_data",
        }

        if len(df) < min_candles:
            return result

        stoch_k_series = df.get("stoch_k")
        stoch_d_series = df.get("stoch_d")
        if stoch_k_series is None or stoch_d_series is None:
            stoch_k_series, stoch_d_series = TechnicalIndicators.calculate_stochastic(df)
            df["stoch_k"] = stoch_k_series
            df["stoch_d"] = stoch_d_series

        if (
            stoch_k_series is None
            or stoch_d_series is None
            or len(stoch_k_series) == 0
            or len(stoch_d_series) == 0
        ):
            return result

        if len(stoch_k_series) < 2 or len(stoch_d_series) < 2:
            return result

        current_k = df["stoch_k"].iloc[-1]
        current_d = df["stoch_d"].iloc[-1]
        if pd.isna(current_k) or pd.isna(current_d):
            return result

        prev_k = df["stoch_k"].iloc[-2]
        prev_d = df["stoch_d"].iloc[-2]

        stoch_k = float(current_k)
        stoch_d = float(current_d)
        prev_stoch_k = float(prev_k) if prev_k is not None and pd.notna(prev_k) else None
        prev_stoch_d = float(prev_d) if prev_d is not None and pd.notna(prev_d) else None

        is_dead_cross, cross_score, cross_reason = self._check_stoch_dead_cross(
            stoch_k, stoch_d, prev_stoch_k, prev_stoch_d
        )

        if is_dead_cross:
            if (
                prev_stoch_k is not None
                and prev_stoch_d is not None
                and prev_stoch_k >= prev_stoch_d
            ):
                cross_type = "fresh_cross"
            else:
                cross_type = "dead_cross_state"
        else:
            cross_type = "golden_cross"

        result.update(
            {
                "stoch_k": stoch_k,
                "stoch_d": stoch_d,
                "prev_stoch_k": prev_stoch_k,
                "prev_stoch_d": prev_stoch_d,
                "is_stoch_dead_cross": is_dead_cross,
                "stoch_cross_score": cross_score,
                "stoch_cross_reason": cross_reason,
                "stoch_cross_type": cross_type,
            }
        )
        return result

    def _calculate_ma_position_score(
        self,
        current_price: float,
        ma_short: float,
        ma_long: float,
        ma_gap_ratio: float,
    ) -> tuple[float, list[str]]:
        """MA 위치 기반 점수"""
        score = 0.0
        reasons: list[str] = []

        is_death_cross = ma_short < ma_long
        is_below_ma55 = current_price < ma_short

        if is_death_cross and is_below_ma55:
            score = 10.0
            reasons.append("데드크로스 + 현재가 MA55 하회")
        elif is_death_cross:
            score = 7.0
            reasons.append("데드크로스 발생 (MA55 < MA165)")
        elif is_below_ma55:
            score = 5.0
            reasons.append(f"현재가 MA55 하회 ({current_price:,.0f} < {ma_short:,.0f})")

        if not is_death_cross and ma_gap_ratio < 3.0:
            score += 3.0
            reasons.append(f"MA 갭 축소 ({ma_gap_ratio:.1f}%) - 데드크로스 임박 주의")

        return score, reasons

    def _check_52week_high(
        self,
        symbol: str,
        current_price: float,
        df: pd.DataFrame,
    ) -> tuple[bool, float, str, str]:
        """52주 신고가 확인"""
        min_candles = 50
        if "high" not in df.columns or len(df) < min_candles:
            logger.debug(f"52주 신고가 계산 불가: {symbol} 데이터 부족")
            return False, 0.0, "", "insufficient_data"

        lookback = min(252, len(df))
        high_52w = df["high"].tail(lookback).max()
        if pd.isna(high_52w):
            return False, 0.0, "", "insufficient_data"

        high_52w = float(high_52w)
        is_new_high = current_price >= high_52w
        ratio = current_price / high_52w if high_52w > 0 else 0.0

        if is_new_high:
            return (
                True,
                10.0,
                f"52주 신고가 경신 ({current_price:,.0f} ≥ {high_52w:,.0f})",
                "raw",
            )

        if ratio >= 0.95:
            return False, 5.0, f"52주 신고가 근접 ({ratio:.1%})", "raw"

        return False, 0.0, "", "raw"

    def _calculate_atr(
        self,
        df: pd.DataFrame,
        period: int = 14,
    ) -> float | None:
        """ATR 계산 (스칼라 반환)"""
        min_candles = period + 1
        if len(df) < min_candles:
            return None

        if not {"high", "low", "close"}.issubset(df.columns):
            return None

        return TechnicalIndicators.calculate_atr(
            high_prices=df["high"].tolist(),
            low_prices=df["low"].tolist(),
            close_prices=df["close"].tolist(),
            period=period,
        )

    async def analyze_sell_signal(
        self,
        symbol: str,
        stoch_overbought: float = 70.0,
        rsi_overbought: float = 70.0,
        entry_price: float | None = None,
        highest_price: float | None = None,
        trailing_stop_activated: bool = False,
        force_refresh: bool = False,
        use_scoring: bool = True,
        merge_strategy: str = "conservative",
        name: str | None = None,
        market: str | None = None,
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
        name, market = await self._get_symbol_hints(symbol=symbol, name=name, market=market)

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

        # 2-1. 거래량 지표 계산 (ATR 포함)
        atr_value = self._calculate_atr(df, period=14)
        volume_indicators = self._calculate_volume_indicators(df, atr=atr_value)

        # 2-2. ADX 지표 계산
        adx_indicators = self._calculate_adx_indicators(df, period=14)

        # 3. 최신 값 추출
        latest = df.iloc[-1]
        close = float(latest["close"])
        ma_short = float(latest["ma_short"]) if pd.notna(latest["ma_short"]) else 0
        ma_long = float(latest["ma_long"]) if pd.notna(latest["ma_long"]) else 0
        rsi_raw = float(latest["rsi"]) if pd.notna(latest["rsi"]) else None

        stoch_data = self._calculate_stochastic_indicators(df)
        stoch_k_raw = stoch_data.get("stoch_k")
        stoch_d_raw = stoch_data.get("stoch_d")
        prev_stoch_k = stoch_data.get("prev_stoch_k")
        prev_stoch_d = stoch_data.get("prev_stoch_d")
        is_stoch_dead_cross = bool(stoch_data.get("is_stoch_dead_cross", False))
        stoch_cross_type = stoch_data.get("stoch_cross_type")

        stoch_k = stoch_k_raw if stoch_k_raw is not None else 50
        stoch_d = stoch_d_raw if stoch_d_raw is not None else 50
        rsi = rsi_raw if rsi_raw is not None else 50

        # 3-1. 52주 신고가 체크
        (
            is_52week_high,
            high_52week_score,
            high_52week_reason,
            high_52week_note,
        ) = self._check_52week_high(
            symbol=symbol,
            current_price=close,
            df=df,
        )
        high_52week_value: float | None = None
        high_52week_ratio: float | None = None
        if high_52week_note == "raw" and "high" in df.columns and len(df) > 0:
            lookback = min(252, len(df))
            high_52week_raw = df["high"].tail(lookback).max()
            if high_52week_raw is not None and pd.notna(high_52week_raw):
                high_52week_value = float(high_52week_raw)
                if high_52week_value > 0:
                    high_52week_ratio = close / high_52week_value

        # 3-2. 개인 수급 과열 체크 (정확한 신용잔고 API 확보 전 보조지표)
        personal_flow_data = await self._get_personal_flow_data(symbol)
        is_personal_buying_overheated, personal_flow_reasons = self._is_personal_buying_overheated(
            personal_flow_data
        )

        # 3-3. 시장 신용 과열 체크 (KOFIA)
        market_credit_data = await self._get_market_credit_trend(market)
        is_market_credit_overheated = bool(
            market_credit_data and market_credit_data.is_overheated
        )
        market_credit_reasons = market_credit_data.reasons if market_credit_data else []
        overlay_signals = SellPeakRuleResearchService.evaluate_peak_rule_inputs(
            personal_buy_days_5d=(
                personal_flow_data.days_positive_count if personal_flow_data else None
            ),
            personal_buy_ratio_5d_to_volume=(
                personal_flow_data.recent_5d_buy_ratio_to_volume if personal_flow_data else None
            ),
            market_credit_change_ratio=(
                market_credit_data.balance_change_ratio if market_credit_data else None
            ),
            market_credit_recent_high_ratio=(
                market_credit_data.recent_5d_high_ratio if market_credit_data else None
            ),
            stoch_k=stoch_k,
            is_52week_high=is_52week_high,
            high_52week_ratio=high_52week_ratio,
        )

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
            is_volume_spike=volume_indicators.get("is_volume_spike", False),
            is_volume_peak=volume_indicators.get("is_volume_peak", False),
            is_stoch_dead_cross=is_stoch_dead_cross,
            is_52week_high=is_52week_high,
            high_52week_ratio=high_52week_ratio,
            dynamic_stoch_threshold=dynamic_stoch,
            dynamic_rsi_threshold=dynamic_rsi,
            name=name,
            market=market,
        )
        sell_stage, overlay_stage_reasons = self._apply_overlay_stage_upgrade(
            sell_stage,
            is_personal_buying_overheated=is_personal_buying_overheated,
            overlay_signals=overlay_signals,
        )
        stage_reasons.extend(overlay_stage_reasons)

        sell_score_result = self.calculate_sell_score(
            stoch_k=stoch_k_raw,
            stoch_d=stoch_d_raw,
            prev_stoch_k=prev_stoch_k,
            prev_stoch_d=prev_stoch_d,
            rsi=rsi_raw,
            volume_ratio=volume_indicators.get("volume_ratio"),
            volume_peak_score=volume_indicators.get("volume_peak_score"),
            adx=adx_indicators.get("adx"),
            plus_di=adx_indicators.get("plus_di"),
            minus_di=adx_indicators.get("minus_di"),
            is_death_cross=is_death_cross,
            current_price=close,
            ma_short=ma_short,
            ma_long=ma_long,
            ma_gap_ratio=ma_gap_ratio,
            is_volume_peak=volume_indicators.get("is_volume_peak", False),
            is_volume_sell_signal=volume_indicators.get("is_volume_sell_signal", False),
            is_52week_high=is_52week_high,
            high_52week_score=high_52week_score if high_52week_value is not None else None,
            high_52week_reason=high_52week_reason if high_52week_value is not None else None,
            personal_buy_days_5d=(
                personal_flow_data.days_positive_count if personal_flow_data else None
            ),
            personal_buy_ratio_5d_to_volume=(
                personal_flow_data.recent_5d_buy_ratio_to_volume if personal_flow_data else None
            ),
            recent_5d_personal_net_buy=(
                personal_flow_data.recent_5d_net_buy if personal_flow_data else None
            ),
            market_credit_change_ratio=(
                market_credit_data.balance_change_ratio if market_credit_data else None
            ),
            market_credit_recent_high_ratio=(
                market_credit_data.recent_5d_high_ratio if market_credit_data else None
            ),
            risk_combo_peak=bool(overlay_signals["risk_combo_peak"]),
            risk_combo_extreme=bool(overlay_signals["risk_combo_extreme"]),
        )

        final_stage = self.determine_final_stage(
            rule_stage=sell_stage,
            score_stage=sell_score_result.recommended_stage,
            use_scoring=use_scoring,
            merge_strategy=merge_strategy,
        )
        final_stage, final_overlay_stage_reasons = self._apply_overlay_stage_upgrade(
            final_stage,
            is_personal_buying_overheated=is_personal_buying_overheated,
            overlay_signals=overlay_signals,
        )
        stage_reasons.extend(final_overlay_stage_reasons)

        final_ratio_min, final_ratio_max = SELL_STAGE_RATIOS.get(final_stage, (0.0, 0.0))

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
            and sell_stage == SellStageEnum.HOLD
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
        sell_reasons.extend(personal_flow_reasons)
        sell_reasons.extend(market_credit_reasons)
        sell_reasons.extend(overlay_signals["combo_reasons"])

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
            f"adx={adx_indicators.get('adx')}, "
            f"volume_spike={volume_indicators.get('is_volume_spike')}"
        )

        return SellSignalAnalysisDTO(
            symbol=symbol,
            name=name,
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
            is_stoch_dead_cross=is_stoch_dead_cross,
            stoch_cross_type=stoch_cross_type,
            prev_stoch_k=round(prev_stoch_k, 2) if prev_stoch_k is not None else None,
            prev_stoch_d=round(prev_stoch_d, 2) if prev_stoch_d is not None else None,
            rsi=round(rsi, 2),
            is_rsi_overbought=is_rsi_overbought,
            # 52주 신고가 관련
            is_52week_high=is_52week_high,
            high_52week=Decimal(str(high_52week_value)) if high_52week_value is not None else None,
            high_52week_ratio=round(high_52week_ratio, 4) if high_52week_ratio is not None else None,
            high_52week_data_note=high_52week_note,
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
            sell_score_result=sell_score_result,
            score_based_stage=(
                sell_score_result.recommended_stage.value
                if hasattr(sell_score_result.recommended_stage, "value")
                else str(sell_score_result.recommended_stage)
            ),
            final_stage=final_stage,
            final_ratio_min=final_ratio_min,
            final_ratio_max=final_ratio_max,
            merge_strategy=merge_strategy,
            # === 거래량 관련 신규 필드 ===
            current_volume=volume_indicators.get("current_volume"),
            prev_volume=volume_indicators.get("prev_volume"),
            volume_ma_20=volume_indicators.get("volume_ma_20"),
            volume_ratio=volume_indicators.get("volume_ratio"),
            is_volume_spike=volume_indicators.get("is_volume_spike", False),
            price_drop_ratio=volume_indicators.get("price_drop_ratio"),
            is_volume_sell_signal=volume_indicators.get("is_volume_sell_signal", False),
            volume_sell_reasons=volume_indicators.get("volume_sell_reasons", []),
            is_volume_peak=volume_indicators.get("is_volume_peak", False),
            volume_signal_type=volume_indicators.get("volume_signal_type"),
            volume_peak_reasons=volume_indicators.get("volume_peak_reasons", []),
            # === ADX 관련 신규 필드 ===
            adx=adx_indicators.get("adx"),
            plus_di=adx_indicators.get("plus_di"),
            minus_di=adx_indicators.get("minus_di"),
            is_strong_uptrend=adx_indicators.get("is_strong_uptrend", False),
            is_strong_downtrend=adx_indicators.get("is_strong_downtrend", False),
            overbought_sell_blocked=overbought_sell_blocked,
            personal_net_buy_latest=(
                personal_flow_data.latest_individual_net_buy if personal_flow_data else None
            ),
            personal_net_buy_3d=(
                personal_flow_data.recent_3d_net_buy if personal_flow_data else None
            ),
            personal_net_buy_5d=(
                personal_flow_data.recent_5d_net_buy if personal_flow_data else None
            ),
            personal_buy_days_5d=(
                personal_flow_data.days_positive_count if personal_flow_data else None
            ),
            personal_buy_ratio_5d_to_volume=(
                round(personal_flow_data.recent_5d_buy_ratio_to_volume, 4)
                if personal_flow_data and personal_flow_data.recent_5d_buy_ratio_to_volume is not None
                else None
            ),
            is_personal_buying_overheated=is_personal_buying_overheated,
            market_credit_label=(market_credit_data.market_label if market_credit_data else None),
            market_credit_balance_million=(market_credit_data.latest_balance_million if market_credit_data else None),
            market_credit_change_ratio=(
                round(market_credit_data.balance_change_ratio, 4)
                if market_credit_data and market_credit_data.balance_change_ratio is not None
                else None
            ),
            market_credit_recent_high_ratio=(
                round(market_credit_data.recent_5d_high_ratio, 4)
                if market_credit_data and market_credit_data.recent_5d_high_ratio is not None
                else None
            ),
            is_market_credit_overheated=is_market_credit_overheated,
            candle_count=candle_count,
        )

    def calculate_sell_score(
        self,
        stoch_k: float | None,
        stoch_d: float | None,
        prev_stoch_k: float | None,
        prev_stoch_d: float | None,
        rsi: float | None,
        volume_ratio: float | None,
        adx: float | None,
        plus_di: float | None,
        minus_di: float | None,
        is_death_cross: bool,
        current_price: float,
        ma_short: float,
        ma_long: float,
        ma_gap_ratio: float,
        volume_peak_score: float | None = None,
        is_volume_peak: bool = False,
        is_volume_sell_signal: bool = False,
        is_52week_high: bool = False,
        high_52week_score: float | None = None,
        high_52week_reason: str | None = None,
        personal_buy_days_5d: int | None = None,
        personal_buy_ratio_5d_to_volume: float | None = None,
        recent_5d_personal_net_buy: int | None = None,
        market_credit_change_ratio: float | None = None,
        market_credit_recent_high_ratio: float | None = None,
        risk_combo_peak: bool = False,
        risk_combo_extreme: bool = False,
        settings: SellScoreSettings | None = None,
    ) -> SellScoreResultDTO:
        """점수 기반 매도 판단"""
        config = settings or self.sell_score_settings
        score_reasons: list[str] = []
        score_breakdown: dict[str, float] = {}

        stoch_k = None if self._is_nan(stoch_k) else stoch_k
        stoch_d = None if self._is_nan(stoch_d) else stoch_d
        rsi = None if self._is_nan(rsi) else rsi
        volume_ratio = None if self._is_nan(volume_ratio) else volume_ratio
        volume_peak_score = None if self._is_nan(volume_peak_score) else volume_peak_score
        adx = None if self._is_nan(adx) else adx
        plus_di = None if self._is_nan(plus_di) else plus_di
        minus_di = None if self._is_nan(minus_di) else minus_di
        high_52week_score = None if self._is_nan(high_52week_score) else high_52week_score

        total_score = 0.0

        # Stoch 점수
        stoch_score = 0.0
        if stoch_k is not None:
            if stoch_k > 95:
                stoch_score = config.stoch_weight
                score_reasons.append(f"Stoch 매우 과열 (K={stoch_k:.1f} > 95)")
            elif stoch_k > 85:
                stoch_score = config.stoch_weight * (20.0 / 30.0)
                score_reasons.append(f"Stoch 과열 (K={stoch_k:.1f} > 85)")
            elif stoch_k > 70:
                stoch_score = config.stoch_weight * (10.0 / 30.0)
                score_reasons.append(f"Stoch 과열 초기 (K={stoch_k:.1f} > 70)")
        total_score += stoch_score

        # RSI 점수
        rsi_score = 0.0
        if rsi is not None:
            if rsi > 80:
                rsi_score = config.rsi_weight
                score_reasons.append(f"RSI 매우 과열 (RSI={rsi:.1f} > 80)")
            elif rsi > 70:
                rsi_score = config.rsi_weight * (15.0 / 25.0)
                score_reasons.append(f"RSI 과열 (RSI={rsi:.1f} > 70)")
            elif rsi > 65:
                rsi_score = config.rsi_weight * (5.0 / 25.0)
                score_reasons.append(f"RSI 과열 초기 (RSI={rsi:.1f} > 65)")
        total_score += rsi_score

        # 거래량 점수
        volume_score = 0.0
        if volume_ratio is not None:
            if volume_ratio >= config.volume_ratio_high:
                volume_score = config.volume_weight
                score_reasons.append(f"거래량 폭증 ({volume_ratio:.2f}x)")
            elif volume_ratio >= config.volume_ratio_mid:
                volume_score = config.volume_weight * (15.0 / 20.0)
                score_reasons.append(f"거래량 급증 ({volume_ratio:.2f}x)")
            elif volume_ratio >= config.volume_ratio_low:
                volume_score = config.volume_weight * (10.0 / 20.0)
                score_reasons.append(f"거래량 증가 ({volume_ratio:.2f}x)")

        peak_score_raw = volume_peak_score if volume_peak_score is not None else 0.0
        peak_score = peak_score_raw if is_volume_peak else 0.0
        if is_volume_peak:
            if is_volume_sell_signal and volume_score > 0 and peak_score > 0:
                volume_score = max(volume_score, peak_score)
                score_reasons.append("거래량 매도/피크 중복 → 높은 점수 적용")
            elif peak_score > 0:
                volume_score = max(volume_score, peak_score)
                score_reasons.append("거래량 피크 점수 반영")

            volume_score += 5.0
            score_reasons.append("거래량 피크 보너스 (+5)")

        total_score += volume_score

        # 52주 신고가 점수
        high_score = 0.0
        if high_52week_score is not None and high_52week_score > 0:
            high_score = high_52week_score
            if high_52week_reason:
                score_reasons.append(high_52week_reason)
        total_score += high_score

        # 개인 수급 과열 점수
        personal_flow_score = 0.0
        if (
            recent_5d_personal_net_buy is not None
            and recent_5d_personal_net_buy > 0
            and personal_buy_days_5d is not None
        ):
            if (
                personal_buy_ratio_5d_to_volume is not None
                and personal_buy_days_5d >= config.personal_buy_days_threshold
                and personal_buy_ratio_5d_to_volume >= config.personal_buy_ratio_high
            ):
                personal_flow_score = config.personal_flow_weight
                score_reasons.append(
                    "개인 수급 과열 강함 (연속 순매수 + 거래량 대비 비중 높음)"
                )
            elif (
                personal_buy_ratio_5d_to_volume is not None
                and personal_buy_days_5d >= config.personal_buy_days_threshold
                and personal_buy_ratio_5d_to_volume >= config.personal_buy_ratio_mid
            ):
                personal_flow_score = config.personal_flow_weight * 0.7
                score_reasons.append("개인 수급 과열 경고 (최근 5일 순매수 집중)")
            elif personal_buy_days_5d >= config.personal_buy_days_threshold:
                personal_flow_score = config.personal_flow_weight * 0.4
                score_reasons.append("개인 수급 쏠림 경고 (최근 5일 순매수 우세)")
        total_score += personal_flow_score

        market_credit_score = 0.0
        if (
            market_credit_change_ratio is not None
            and market_credit_recent_high_ratio is not None
        ):
            if market_credit_change_ratio >= 0.01 and market_credit_recent_high_ratio >= 0.995:
                market_credit_score = config.market_credit_weight
                score_reasons.append("시장 신용 과열 강함 (일간 증가율 + 고점권)")
            elif market_credit_change_ratio >= 0.008 and market_credit_recent_high_ratio >= 0.99:
                market_credit_score = config.market_credit_weight * 0.625
                score_reasons.append("시장 신용 과열 경고 (증가율/고점권)")
        total_score += market_credit_score

        # ADX 약화 점수
        adx_score = 0.0
        if adx is not None:
            adx_score, adx_label = TechnicalIndicators.calculate_adx_weakness_score(adx)
            if adx_score > 0:
                score_reasons.append(f"ADX {adx_label} (ADX={adx:.1f})")
        total_score += adx_score

        # MA 상태 점수
        ma_score, ma_reasons = self._calculate_ma_position_score(
            current_price=current_price,
            ma_short=ma_short,
            ma_long=ma_long,
            ma_gap_ratio=ma_gap_ratio,
        )
        if ma_reasons:
            score_reasons.extend(ma_reasons)
        total_score += ma_score

        # Stoch 데드크로스 보너스
        cross_score = 0.0
        if stoch_k is not None and stoch_d is not None:
            is_dead_cross, raw_cross_score, cross_reason = self._check_stoch_dead_cross(
                stoch_k, stoch_d, prev_stoch_k, prev_stoch_d
            )
            if is_dead_cross and raw_cross_score > 0:
                cross_score = raw_cross_score * (config.cross_bonus / 10.0)
                if cross_reason:
                    score_reasons.append(cross_reason)
        total_score += cross_score

        # 52주 신고가 + 과매수 보너스
        overbought_bonus = 0.0
        if is_52week_high and stoch_k is not None and stoch_k > 85:
            overbought_bonus = 5.0
            total_score += overbought_bonus
            score_reasons.append("신고가 + 과매수 조합 (+5)")

        risk_combo_bonus = 0.0
        if risk_combo_extreme:
            risk_combo_bonus = config.risk_combo_weight
            score_reasons.append("개인 수급+시장 신용+고점권 피크 보너스")
        elif risk_combo_peak:
            risk_combo_bonus = config.risk_combo_weight * 0.5
            score_reasons.append("개인 수급+시장 신용 동시 과열 보너스")
        total_score += risk_combo_bonus

        # ADX 강세 감점
        adx_penalty, adx_penalty_reason = self._calculate_adx_penalty(
            adx, plus_di, minus_di, config
        )
        if adx_penalty != 0.0:
            total_score += adx_penalty
            if adx_penalty_reason:
                score_reasons.append(adx_penalty_reason)

        available_max = 0.0
        if stoch_k is not None:
            available_max += config.stoch_weight
        if rsi is not None:
            available_max += config.rsi_weight
        if volume_ratio is not None:
            available_max += config.volume_weight
        if is_volume_peak:
            available_max += 5.0
        if high_52week_score is not None:
            available_max += 10.0
        if recent_5d_personal_net_buy is not None and recent_5d_personal_net_buy > 0:
            available_max += config.personal_flow_weight
        if market_credit_change_ratio is not None and market_credit_recent_high_ratio is not None:
            available_max += config.market_credit_weight
        if adx is not None:
            available_max += config.adx_weight
        available_max += config.ma_weight + 3.0
        if stoch_d is not None:
            available_max += config.cross_bonus
        if overbought_bonus > 0:
            available_max += overbought_bonus
        if risk_combo_peak or risk_combo_extreme:
            available_max += config.risk_combo_weight

        normalized_score = (total_score / available_max) * 100 if available_max > 0 else 0.0

        if normalized_score >= config.exit_all_threshold:
            recommended_stage = SellStageEnum.EXIT_ALL
        elif normalized_score >= config.reduce_2_threshold:
            recommended_stage = SellStageEnum.REDUCE_2
        elif normalized_score >= config.reduce_1_threshold:
            recommended_stage = SellStageEnum.REDUCE_1
        else:
            recommended_stage = SellStageEnum.HOLD

        score_breakdown = {
            "stoch_score": round(stoch_score, 2),
            "rsi_score": round(rsi_score, 2),
            "volume_score": round(volume_score, 2),
            "volume_peak_score": round(peak_score_raw, 2),
            "high_52week_score": round(high_score, 2),
            "high_52week_bonus": round(overbought_bonus, 2),
            "personal_flow_score": round(personal_flow_score, 2),
            "market_credit_score": round(market_credit_score, 2),
            "risk_combo_bonus": round(risk_combo_bonus, 2),
            "adx_score": round(adx_score, 2),
            "ma_score": round(ma_score, 2),
            "cross_score": round(cross_score, 2),
            "adx_penalty": round(adx_penalty, 2),
            "raw_score": round(total_score, 2),
        }

        return SellScoreResultDTO(
            total_score=round(total_score, 2),
            normalized_score=round(normalized_score, 2),
            available_max=round(available_max, 2),
            score_breakdown=score_breakdown,
            score_reasons=score_reasons,
            recommended_stage=recommended_stage,
        )

    def _calculate_adx_penalty(
        self,
        adx: float | None,
        plus_di: float | None,
        minus_di: float | None,
        settings: SellScoreSettings,
    ) -> tuple[float, str | None]:
        """ADX 강세 감점 계산"""
        if adx is None or plus_di is None or minus_di is None:
            return 0.0, None

        if adx >= settings.adx_penalty_strong_threshold and plus_di > minus_di:
            return (
                settings.adx_penalty_strong,
                f"ADX 강한 상승 추세 감점 (ADX={adx:.1f}, +DI={plus_di:.1f} > -DI={minus_di:.1f})",
            )

        if adx >= settings.adx_penalty_moderate_threshold and plus_di > minus_di:
            return (
                settings.adx_penalty_moderate,
                f"ADX 상승 추세 감점 (ADX={adx:.1f}, +DI={plus_di:.1f} > -DI={minus_di:.1f})",
            )

        return 0.0, None

    def _upgrade_stage_for_personal_overheat(
        self,
        stage: SellStageEnum,
        is_personal_buying_overheated: bool,
    ) -> tuple[SellStageEnum, list[str]]:
        """개인 수급 과열이면 Stage를 한 단계 강화"""
        return self._upgrade_stage_for_overlay(
            stage,
            is_personal_buying_overheated,
            "개인 수급 과열",
        )

    def _apply_overlay_stage_upgrade(
        self,
        stage: SellStageEnum,
        *,
        is_personal_buying_overheated: bool,
        overlay_signals: dict[str, object],
    ) -> tuple[SellStageEnum, list[str]]:
        """실전 overlay는 최대 1회만 Stage를 강화한다."""
        if bool(overlay_signals.get("risk_combo_peak")):
            return self._upgrade_stage_for_overlay(
                stage,
                True,
                "개인 수급+시장 신용+고점권 정렬",
            )
        if is_personal_buying_overheated:
            return self._upgrade_stage_for_overlay(
                stage,
                True,
                "개인 수급 과열",
            )
        return stage, []

    def determine_final_stage(
        self,
        rule_stage: SellStageEnum,
        score_stage: SellStageEnum,
        use_scoring: bool,
        merge_strategy: str = "conservative",
    ) -> SellStageEnum:
        """
        최종 매도 단계 결정

        merge_strategy:
        - "conservative": 두 결과 중 더 강한 단계 채택
        - "score_only": 점수 기반만 사용
        - "rule_only": 규칙 기반만 사용
        """
        if not use_scoring:
            return rule_stage

        if merge_strategy == "score_only":
            return score_stage
        if merge_strategy == "rule_only":
            return rule_stage

        stage_order = [
            SellStageEnum.HOLD,
            SellStageEnum.REDUCE_1,
            SellStageEnum.REDUCE_2,
            SellStageEnum.EXIT_ALL,
        ]
        return max(rule_stage, score_stage, key=lambda s: stage_order.index(s))

    def _collect_sharp_top_signals(
        self,
        stoch_k: float,
        rsi: float,
        dynamic_stoch_threshold: float,
        dynamic_rsi_threshold: float,
        is_stoch_dead_cross: bool,
        is_volume_spike: bool,
        is_volume_sell_signal: bool,
        is_volume_peak: bool,
        is_52week_high: bool,
        high_52week_ratio: float | None,
        ma_gap_ratio: float,
    ) -> tuple[int, list[str]]:
        """sharp v1 조기 축소용 상단/과열 신호를 모은다."""
        signals: list[str] = []

        if stoch_k >= max(dynamic_stoch_threshold, 75.0):
            signals.append(f"Stoch 과열 ({stoch_k:.1f})")
        if rsi >= max(dynamic_rsi_threshold, 70.0):
            signals.append(f"RSI 과열 ({rsi:.1f})")
        if is_stoch_dead_cross and stoch_k >= max(dynamic_stoch_threshold - 5.0, 68.0):
            signals.append("Stoch 데드크로스")
        if is_volume_sell_signal:
            signals.append("거래량 매도 신호")
        elif is_volume_peak:
            signals.append("거래량 피크 경고")
        elif is_volume_spike:
            signals.append("거래량 급증")
        if is_52week_high or (high_52week_ratio is not None and high_52week_ratio >= 0.98):
            signals.append("신고가권/고점권")
        if ma_gap_ratio >= 12.0:
            signals.append(f"장기 이격 과대 ({ma_gap_ratio:.1f}%)")

        return len(signals), signals

    def _determine_sharp_profit_protection_stage(
        self,
        *,
        profit_ratio: float | None,
        stoch_k: float,
        rsi: float,
        dynamic_stoch_threshold: float,
        dynamic_rsi_threshold: float,
        is_stoch_dead_cross: bool,
        is_volume_spike: bool,
        is_volume_sell_signal: bool,
        is_volume_peak: bool,
        is_52week_high: bool,
        high_52week_ratio: float | None,
        ma_gap_ratio: float,
        name: str | None,
        market: str | None,
    ) -> tuple[SellStageEnum | None, list[str]]:
        """수익 종목은 sharp v1 기준으로 더 빠르게 축소한다."""
        if profit_ratio is None or profit_ratio <= 0:
            return None, []

        instrument_profile = self.infer_instrument_profile("", name=name, market=market)
        signal_count, top_signals = self._collect_sharp_top_signals(
            stoch_k=stoch_k,
            rsi=rsi,
            dynamic_stoch_threshold=dynamic_stoch_threshold,
            dynamic_rsi_threshold=dynamic_rsi_threshold,
            is_stoch_dead_cross=is_stoch_dead_cross,
            is_volume_spike=is_volume_spike,
            is_volume_sell_signal=is_volume_sell_signal,
            is_volume_peak=is_volume_peak,
            is_52week_high=is_52week_high,
            high_52week_ratio=high_52week_ratio,
            ma_gap_ratio=ma_gap_ratio,
        )
        if signal_count < 2:
            return None, []

        is_etf_like = instrument_profile["is_etf_like"]
        is_leveraged_etf_like = instrument_profile["is_leveraged_etf_like"]
        early_profit_threshold = 0.08
        strong_profit_threshold = 0.15
        reduce_1_signal_threshold = 3
        reduce_2_signal_threshold = 4

        if is_etf_like:
            early_profit_threshold = 0.06
            strong_profit_threshold = 0.12
            reduce_1_signal_threshold = 2
            reduce_2_signal_threshold = 3
        if is_leveraged_etf_like:
            early_profit_threshold = 0.04
            strong_profit_threshold = 0.10
            reduce_1_signal_threshold = 2
            reduce_2_signal_threshold = 3

        reasons: list[str] = []
        if profit_ratio >= strong_profit_threshold and signal_count >= reduce_2_signal_threshold:
            reasons.append(
                f"[sharp v1] 수익 보호 강화: 상단 경고 {signal_count}개 정렬 "
                f"(수익률 {profit_ratio * 100:.1f}%)"
            )
            if is_etf_like:
                reasons.append(
                    "[sharp v1] ETF/레버리지 계열은 이익 보호 기준을 더 엄격하게 적용"
                )
            reasons.extend(top_signals[:4])
            return SellStageEnum.REDUCE_2, reasons

        if profit_ratio >= early_profit_threshold and signal_count >= reduce_1_signal_threshold:
            reasons.append(
                f"[sharp v1] 수익 구간 선제 축소: 상단 경고 {signal_count}개 정렬 "
                f"(수익률 {profit_ratio * 100:.1f}%)"
            )
            if is_etf_like:
                reasons.append(
                    "[sharp v1] ETF/레버리지 계열은 수익 종목 우선 현금화 대상"
                )
            reasons.extend(top_signals[:4])
            return SellStageEnum.REDUCE_1, reasons

        return None, []

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
        atr: float | None = None,
    ) -> dict[str, float | int | bool | list[str] | str | None]:
        """
        거래량 지표 계산

        Args:
            df: OHLCV 데이터프레임 (volume 컬럼 포함)
            atr: ATR 값 (선택)

        Returns:
            dict: 거래량 관련 지표
        """
        result: dict[str, float | int | bool | list[str] | str | None] = {
            "current_volume": None,
            "prev_volume": None,
            "volume_ma_20": None,
            "volume_ratio": None,
            "is_volume_spike": False,
            "price_drop_ratio": None,
            "is_volume_sell_signal": False,
            "volume_sell_reasons": [],
            "is_volume_peak": False,
            "volume_signal_type": "none",
            "volume_peak_reasons": [],
            "volume_peak_score": None,
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

        # 거래량+하락 매도 신호 (ATR 반영)
        if atr is None:
            atr = self._calculate_atr(df, period=14)

        is_signal, reasons = TechnicalIndicators.check_volume_sell_signal(
            current_price=current_price,
            prev_price=prev_price,
            current_volume=current_volume,
            volume_ma_20=volume_ma_20,
            atr=atr,
            volume_ratio_threshold=1.3,
            min_drop_ratio=0.005,
        )

        is_peak, peak_score, peak_reasons = TechnicalIndicators.check_volume_peak_signal(
            current_price=current_price,
            prev_price=prev_price,
            current_volume=current_volume,
            volume_ma_20=volume_ma_20,
            price_change_threshold=0.03,
        )

        if is_signal:
            volume_signal_type = "sell"
        elif is_peak:
            volume_signal_type = "peak"
        else:
            volume_signal_type = "none"

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
        result["is_volume_peak"] = is_peak
        result["volume_signal_type"] = volume_signal_type
        result["volume_peak_reasons"] = peak_reasons
        result["volume_peak_score"] = round(peak_score, 2)

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
        is_volume_spike: bool = False,
        is_volume_peak: bool = False,
        is_stoch_dead_cross: bool = False,
        is_52week_high: bool = False,
        high_52week_ratio: float | None = None,
        dynamic_stoch_threshold: float = 70.0,
        dynamic_rsi_threshold: float = 70.0,
        name: str | None = None,
        market: str | None = None,
    ) -> tuple[SellStageEnum, list[str]]:
        """
        비중축소 Stage 결정 (기존 Phase와 별도)

        우선순위:
        1. 긴급 손절 (profit_ratio <= -7%) → EXIT_ALL
        2. 전량 청산 (데드크로스 + 거래량 급증) → EXIT_ALL
        3. 추세 붕괴 (데드크로스 + 극심한 과열) → EXIT_ALL
        4. sharp v1 수익 보호 (다중 상단 경고 정렬) → REDUCE
        5. ADX 추세 유지 필터 (강한 상승 추세) → HOLD
        6. ADX 약화 + 거래량 급증 → REDUCE_2
        7. 2차 축소 (데드크로스 + 과열) → REDUCE_2
        8. 1차 축소 (ADX 약화 또는 과열 초기 / 거래량 경고) → REDUCE_1
        9. 보유 유지 → HOLD

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

        # === 4순위: sharp v1 수익 보호 ===
        sharp_stage, sharp_reasons = self._determine_sharp_profit_protection_stage(
            profit_ratio=profit_ratio,
            stoch_k=stoch_k,
            rsi=rsi,
            dynamic_stoch_threshold=dynamic_stoch_threshold,
            dynamic_rsi_threshold=dynamic_rsi_threshold,
            is_stoch_dead_cross=is_stoch_dead_cross,
            is_volume_spike=is_volume_spike,
            is_volume_sell_signal=is_volume_sell_signal,
            is_volume_peak=is_volume_peak,
            is_52week_high=is_52week_high,
            high_52week_ratio=high_52week_ratio,
            ma_gap_ratio=ma_gap_ratio,
            name=name,
            market=market,
        )
        if sharp_stage is not None:
            reasons.extend(sharp_reasons)
            return sharp_stage, reasons

        # === 5순위: ADX 추세 유지 필터 ===
        # (손절/전량청산 이후에만 적용)
        is_strong_uptrend = False
        if adx is not None and plus_di is not None and minus_di is not None:
            is_strong_uptrend = adx > 25 and plus_di > minus_di
            if is_strong_uptrend and not is_death_cross and not is_volume_sell_signal:
                reasons.append(
                    f"강한 상승 추세 유지 "
                    f"(ADX={adx:.1f}, +DI={plus_di:.1f} > -DI={minus_di:.1f})"
                )
                return SellStageEnum.HOLD, reasons

        # === 6순위: ADX 약화 대응 ===
        if adx is not None and adx < 15 and is_volume_spike:
            reasons.append(f"ADX 매우 약화 + 거래량 급증 (ADX={adx:.1f})")
            return SellStageEnum.REDUCE_2, reasons

        # === 7순위: 2차 비중 축소 (30~40%) ===
        if is_death_cross and (stoch_k > dynamic_stoch_threshold or rsi > dynamic_rsi_threshold):
            reasons.append(
                f"데드크로스 + 과열 "
                f"(Stoch>{dynamic_stoch_threshold:.0f} OR RSI>{dynamic_rsi_threshold:.0f})"
            )
            return SellStageEnum.REDUCE_2, reasons

        if is_volume_sell_signal and ma_gap_ratio < 3:
            reasons.append("거래량 급증 하락 + MA 갭 축소 (<3%)")
            return SellStageEnum.REDUCE_2, reasons

        # === 8순위: 1차 비중 축소 (20~30%) ===
        if adx is not None and adx < 20 and stoch_k > 85:
            reasons.append(f"ADX 약화 + Stoch 과열 (ADX={adx:.1f}, K={stoch_k:.1f})")
            return SellStageEnum.REDUCE_1, reasons

        if is_gc_active and stoch_k > 85 and rsi > 80:
            reasons.append("GC 유지 + 극심한 과열 (수익 보호)")
            return SellStageEnum.REDUCE_1, reasons

        if ma_gap_ratio < 3 and ma_gap_ratio > 0 and stoch_k > 75 and rsi > 70:
            reasons.append("MA 갭 축소 + 과열 (데드크로스 임박)")
            return SellStageEnum.REDUCE_1, reasons

        if is_volume_sell_signal:
            reasons.append("거래량 급증 하락 감지")
            return SellStageEnum.REDUCE_1, reasons

        # === 9순위: 보유 유지 ===
        # 기존 Phase에서 매핑 (호환성)
        default_stage = PHASE_TO_STAGE_MAP.get(sell_phase, SellStageEnum.HOLD)
        if default_stage != SellStageEnum.HOLD:
            reasons.append(f"기존 Phase({sell_phase.value})에서 매핑")
            return default_stage, reasons

        return SellStageEnum.HOLD, reasons
