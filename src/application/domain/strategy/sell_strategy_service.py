# -*- coding: utf-8 -*-
"""
Sell Strategy Service - 매도 전략 서비스

기술적 지표 기반 매도 시그널 분석
- Phase 기반 선제적 매도 시그널
- 수익률 기반 동적 임계값
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.external.kofia_client import MarketCreditTrendData, get_kofia_client
from src.adapters.external.naver.stock_client import StockPersonalFlowData, get_naver_stock_client
from src.application.common.exceptions import StrategyError
from src.application.common.indicators import TechnicalIndicators
from src.application.domain.strategy.dto import (
    PHASE_TO_STAGE_MAP,
    SELL_PHASE_INFO,
    SELL_STAGE_INFO,
    SELL_STAGE_RATIOS,
    DynamicSellThresholdConfig,
    SellPhaseEnum,
    SellScoreResultDTO,
    SellSignalAnalysisDTO,
    SellStageEnum,
)
from src.application.domain.strategy.ohlcv_data_loader import OHLCVDataLoader
from src.application.domain.strategy.sell_rule_research_service import SellPeakRuleResearchService
from src.application.domain.strategy.sell_score_rules import (
    ScoreRule,
    adx_penalty_rule,
    adx_rule,
    cross_rule,
    high_52week_rule,
    ma_rule,
    market_credit_rule,
    overbought_bonus_rule,
    personal_flow_rule,
    risk_combo_rule,
    rsi_rule,
    stoch_rule,
    volume_rule,
)
from src.application.domain.strategy.strategy_contract import (
    SELL_STAGE_ORDER,
    market_credit_label,
)
from src.settings.config import settings
from src.settings.sell_score_settings import DEFAULT_PEAK_RULE_THRESHOLDS, SellScoreSettings

logger = logging.getLogger(__name__)


@dataclass
class _SellAnalysisContext:
    """``analyze_sell_signal`` 단계 간에 전달되는 가변 작업 컨텍스트.

    로딩(_load_analysis_context) → overlay(_build_overlays) →
    점수/Stage(_score_and_stage) → DTO(_to_sell_dto) 순으로 각 헬퍼가
    필드를 채워 넣는다. 기존 단일 메서드의 지역 변수를 그대로 옮긴 것이며
    계산/순서는 동일하다(동작 보존).
    """

    df: pd.DataFrame
    candle_count: int = 0

    # --- 로딩/지표 ---
    close: float = 0.0
    ma_short: float = 0.0
    ma_long: float = 0.0
    rsi_raw: float | None = None
    stoch_k_raw: float | None = None
    stoch_d_raw: float | None = None
    prev_stoch_k: float | None = None
    prev_stoch_d: float | None = None
    is_stoch_dead_cross: bool = False
    stoch_cross_type: str | None = None
    stoch_k: float = 50.0
    stoch_d: float = 50.0
    rsi: float = 50.0
    volume_indicators: dict = field(default_factory=dict)
    adx_indicators: dict = field(default_factory=dict)
    simple_sell_info: dict = field(default_factory=dict)
    is_52week_high: bool = False
    high_52week_score: float = 0.0
    high_52week_reason: str = ""
    high_52week_note: str = ""
    high_52week_value: float | None = None
    high_52week_ratio: float | None = None

    # --- overlay ---
    personal_flow_data: StockPersonalFlowData | None = None
    is_personal_buying_overheated: bool = False
    personal_flow_reasons: list[str] = field(default_factory=list)
    market_credit_data: MarketCreditTrendData | None = None
    is_market_credit_overheated: bool = False
    market_credit_reasons: list[str] = field(default_factory=list)
    overlay_signals: dict = field(default_factory=dict)

    # --- 점수/Stage ---
    is_gc_active: bool = False
    is_death_cross: bool = False
    ma_gap_ratio: float = 0.0
    profit_ratio: float | None = None
    dynamic_stoch: float = 0.0
    dynamic_rsi: float = 0.0
    is_stop_loss_triggered: bool = False
    is_take_profit_triggered: bool = False
    is_stoch_overbought: bool = False
    is_rsi_overbought: bool = False
    sell_phase: SellPhaseEnum = SellPhaseEnum.NONE
    sell_stage: SellStageEnum = SellStageEnum.HOLD
    stage_reasons: list[str] = field(default_factory=list)
    sell_score_result: SellScoreResultDTO | None = None
    drawdown_from_high: float | None = None
    final_stage: SellStageEnum = SellStageEnum.HOLD
    final_ratio_min: float = 0.0
    final_ratio_max: float = 0.0
    sell_ratio_min: float = 0.0
    sell_ratio_max: float = 0.0
    stage_info: dict = field(default_factory=dict)
    overbought_sell_blocked: bool = False
    sell_reasons: list[str] = field(default_factory=list)
    phase_info: dict = field(default_factory=dict)


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
        self._market_credit_cache: dict[str | None, MarketCreditTrendData | None] = {}

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
            logger.debug(
                "[Sell Signal] failed to fetch personal flow for %s", symbol, exc_info=True
            )
            return None

    async def _get_market_credit_trend(
        self,
        market: str | None,
    ) -> MarketCreditTrendData | None:
        """KOFIA 기반 시장 신용 과열 데이터 조회 (인스턴스 레벨 캐시)"""
        cache_key = (market or "").upper() or None
        if cache_key in self._market_credit_cache:
            return self._market_credit_cache[cache_key]

        market_label = market_credit_label(market)

        try:
            result = await get_kofia_client().get_market_credit_trend(
                start_date="20260101",
                end_date=datetime.now().strftime("%Y%m%d"),
                market_label=market_label,
            )
            self._market_credit_cache[cache_key] = result
            return result
        except Exception:
            logger.debug(
                "[Sell Signal] failed to fetch market credit trend for %s", market, exc_info=True
            )
            self._market_credit_cache[cache_key] = None
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

        current_index = SELL_STAGE_ORDER.index(stage)
        upgraded_stage = SELL_STAGE_ORDER[min(current_index + 1, len(SELL_STAGE_ORDER) - 1)]

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

        is_leveraged_etf_like = any(keyword in normalized_name for keyword in leveraged_keywords)
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

        short_label = f"MA{settings.gc_short_ma_period}"
        long_label = f"MA{settings.gc_long_ma_period}"
        is_death_cross = ma_short < ma_long
        is_below_short_ma = current_price < ma_short

        if is_death_cross and is_below_short_ma:
            score = 10.0
            reasons.append(f"데드크로스 + 현재가 {short_label} 하회")
        elif is_death_cross:
            score = 7.0
            reasons.append(f"데드크로스 발생 ({short_label} < {long_label})")
        elif is_below_short_ma:
            score = 5.0
            reasons.append(f"현재가 {short_label} 하회 ({current_price:,.0f} < {ma_short:,.0f})")

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
        sell_mode: str = "hybrid",  # "legacy", "simple", "hybrid"
    ) -> SellSignalAnalysisDTO:
        """
        매도 시그널 분석

        종목의 기술적 지표를 분석하여 매도 시그널을 판단합니다.
        - 단기/장기 MA 데드크로스 확인 (config 기간)
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

        # 1~3. OHLCV 로딩 + 기술적 지표/보조 컨텍스트
        ctx = await self._load_analysis_context(
            symbol=symbol,
            entry_price=entry_price,
            highest_price=highest_price,
            force_refresh=force_refresh,
        )

        # 3-2~3-3. 개인 수급 / 시장 신용 overlay
        await self._build_overlays(ctx, symbol=symbol, market=market)

        # 4~8. 수익률/Phase/Stage/점수/근거 종합
        self._score_and_stage(
            ctx,
            symbol=symbol,
            stoch_overbought=stoch_overbought,
            rsi_overbought=rsi_overbought,
            entry_price=entry_price,
            highest_price=highest_price,
            trailing_stop_activated=trailing_stop_activated,
            use_scoring=use_scoring,
            merge_strategy=merge_strategy,
            name=name,
            market=market,
            sell_mode=sell_mode,
        )

        # 9. DTO 조립
        return self._to_sell_dto(
            ctx,
            symbol=symbol,
            name=name,
            analyzed_at=analyzed_at,
            entry_price=entry_price,
            highest_price=highest_price,
            trailing_stop_activated=trailing_stop_activated,
            merge_strategy=merge_strategy,
        )

    async def _load_analysis_context(
        self,
        *,
        symbol: str,
        entry_price: float | None,
        highest_price: float | None,
        force_refresh: bool,
    ) -> _SellAnalysisContext:
        """OHLCV 로딩 + 기술적 지표/스토캐스틱/거래량/ADX/52주 신고가 계산."""
        # 1. OHLCV 데이터 로딩
        data_loader = self._get_data_loader()

        # 매수 스캔과 동일한 config MA 기간 사용(라이브 정합: 매수 GC와 매도 DC가
        # 같은 크로스오버를 판정하도록). ETF 모드면 50/200, 기본이면 55/165.
        short_ma_period = settings.gc_short_ma_period
        long_ma_period = settings.gc_long_ma_period

        try:
            df = await data_loader.load_ohlcv_dataframe(
                symbol=symbol,
                days=max(300, int((long_ma_period + 20) * 1.6)),  # 장기 MA + 충분한 버퍼
                interval="1d",
                min_candles=long_ma_period + 20,
                force_refresh=force_refresh,
            )
        except ValueError as e:
            raise StrategyError(str(e))

        # 방어: 로더 계약(ascending 정렬·필수 컬럼)을 신뢰하되 무결성 재확인.
        if (
            df is None
            or df.empty
            or not {"high", "low", "close", "timestamp"}.issubset(df.columns)
        ):
            raise StrategyError(f"{symbol}: OHLCV 데이터 부족/무결성 오류")
        df = df.sort_values("timestamp").reset_index(drop=True)

        ctx = _SellAnalysisContext(df=df)
        ctx.candle_count = len(df)

        # 2. 기술적 지표 계산 (config MA short/long + Stochastic)
        df = TechnicalIndicators.prepare_golden_cross_indicators(
            df,
            short_ma_period=short_ma_period,
            long_ma_period=long_ma_period,
            stoch_k_period=14,
            stoch_d_period=3,
        )

        # RSI 계산 추가
        close_prices = df["close"].tolist()
        rsi_value = TechnicalIndicators.calculate_rsi(close_prices, period=14)
        df["rsi"] = rsi_value if rsi_value is not None else 50.0

        # 2-1. 거래량 지표 계산 (ATR 포함)
        atr_value = self._calculate_atr(df, period=14)
        ctx.volume_indicators = self._calculate_volume_indicators(df, atr=atr_value)

        # 2-2. ADX 지표 계산
        ctx.adx_indicators = self._calculate_adx_indicators(df, period=14)

        # 3. 최신 값 추출
        latest = df.iloc[-1]
        ctx.close = float(latest["close"])
        ctx.ma_short = float(latest["ma_short"]) if pd.notna(latest["ma_short"]) else 0
        ctx.ma_long = float(latest["ma_long"]) if pd.notna(latest["ma_long"]) else 0
        ctx.rsi_raw = float(latest["rsi"]) if pd.notna(latest["rsi"]) else None

        stoch_data = self._calculate_stochastic_indicators(df)
        ctx.stoch_k_raw = stoch_data.get("stoch_k")
        ctx.stoch_d_raw = stoch_data.get("stoch_d")
        ctx.prev_stoch_k = stoch_data.get("prev_stoch_k")
        ctx.prev_stoch_d = stoch_data.get("prev_stoch_d")
        ctx.is_stoch_dead_cross = bool(stoch_data.get("is_stoch_dead_cross", False))
        ctx.stoch_cross_type = stoch_data.get("stoch_cross_type")

        ctx.stoch_k = ctx.stoch_k_raw if ctx.stoch_k_raw is not None else 50
        ctx.stoch_d = ctx.stoch_d_raw if ctx.stoch_d_raw is not None else 50
        ctx.rsi = ctx.rsi_raw if ctx.rsi_raw is not None else 50

        # === New: Compute simple sell for comparison/hybrid ===
        ctx.simple_sell_info = self.compute_simple_sell_signal(
            df=df,
            rsi=ctx.rsi,
            current_price=ctx.close,
            entry_price=entry_price,
            highest_price=highest_price,
        )

        # 3-1. 52주 신고가 체크
        (
            ctx.is_52week_high,
            ctx.high_52week_score,
            ctx.high_52week_reason,
            ctx.high_52week_note,
        ) = self._check_52week_high(
            symbol=symbol,
            current_price=ctx.close,
            df=df,
        )
        if ctx.high_52week_note == "raw" and "high" in df.columns and len(df) > 0:
            lookback = min(252, len(df))
            high_52week_raw = df["high"].tail(lookback).max()
            if high_52week_raw is not None and pd.notna(high_52week_raw):
                ctx.high_52week_value = float(high_52week_raw)
                if ctx.high_52week_value > 0:
                    ctx.high_52week_ratio = ctx.close / ctx.high_52week_value

        ctx.df = df
        return ctx

    async def _build_overlays(
        self,
        ctx: _SellAnalysisContext,
        *,
        symbol: str,
        market: str | None,
    ) -> None:
        """개인 수급 / 시장 신용 등 외부 overlay 신호 수집."""
        # 3-2. 개인 수급 과열 체크 (정확한 신용잔고 API 확보 전 보조지표)
        ctx.personal_flow_data = await self._get_personal_flow_data(symbol)
        (
            ctx.is_personal_buying_overheated,
            ctx.personal_flow_reasons,
        ) = self._is_personal_buying_overheated(ctx.personal_flow_data)

        # 3-3. 시장 신용 과열 체크 (KOFIA)
        ctx.market_credit_data = await self._get_market_credit_trend(market)
        ctx.is_market_credit_overheated = bool(
            ctx.market_credit_data and ctx.market_credit_data.is_overheated
        )
        ctx.market_credit_reasons = (
            ctx.market_credit_data.reasons if ctx.market_credit_data else []
        )
        ctx.overlay_signals = SellPeakRuleResearchService.evaluate_peak_rule_inputs(
            personal_buy_days_5d=(
                ctx.personal_flow_data.days_positive_count if ctx.personal_flow_data else None
            ),
            personal_buy_ratio_5d_to_volume=(
                ctx.personal_flow_data.recent_5d_buy_ratio_to_volume
                if ctx.personal_flow_data
                else None
            ),
            market_credit_change_ratio=(
                ctx.market_credit_data.balance_change_ratio if ctx.market_credit_data else None
            ),
            market_credit_recent_high_ratio=(
                ctx.market_credit_data.recent_5d_high_ratio if ctx.market_credit_data else None
            ),
            stoch_k=ctx.stoch_k,
            is_52week_high=ctx.is_52week_high,
            high_52week_ratio=ctx.high_52week_ratio,
        )

    def _score_and_stage(
        self,
        ctx: _SellAnalysisContext,
        *,
        symbol: str,
        stoch_overbought: float,
        rsi_overbought: float,
        entry_price: float | None,
        highest_price: float | None,
        trailing_stop_activated: bool,
        use_scoring: bool,
        merge_strategy: str,
        name: str | None,
        market: str | None,
        sell_mode: str,
    ) -> None:
        """수익률/Phase/Stage/점수/근거를 종합해 최종 Stage와 근거를 확정."""
        volume_indicators = ctx.volume_indicators
        adx_indicators = ctx.adx_indicators

        # 4. 기본 지표 계산
        ctx.is_gc_active = ctx.ma_short > ctx.ma_long
        ctx.is_death_cross = ctx.ma_short < ctx.ma_long
        ctx.ma_gap_ratio = (
            ((ctx.ma_short - ctx.ma_long) / ctx.ma_long * 100) if ctx.ma_long > 0 else 0
        )

        # 5. 수익률 계산 및 동적 임계값 적용
        ctx.profit_ratio = None
        ctx.dynamic_stoch = stoch_overbought
        ctx.dynamic_rsi = rsi_overbought
        ctx.is_stop_loss_triggered = False
        ctx.is_take_profit_triggered = False

        if entry_price is not None and entry_price > 0:
            ctx.profit_ratio = (ctx.close - entry_price) / entry_price

            # 긴급 손절 체크
            if ctx.profit_ratio <= self.dynamic_config.emergency_stop_ratio:
                ctx.is_stop_loss_triggered = True

            # 익절 목표 체크
            if ctx.profit_ratio >= self.dynamic_config.high_profit_threshold:
                ctx.is_take_profit_triggered = True

            # 동적 임계값 조정
            ctx.dynamic_stoch, ctx.dynamic_rsi = self._get_dynamic_thresholds(ctx.profit_ratio)

        # 6. 적용된 임계값으로 과매수 판정
        ctx.is_stoch_overbought = ctx.stoch_k > ctx.dynamic_stoch
        ctx.is_rsi_overbought = ctx.rsi > ctx.dynamic_rsi

        # 7. Phase 분석 (선제적 매도 시그널)
        ctx.sell_phase, phase_reasons = self._analyze_sell_phase(
            is_gc_active=ctx.is_gc_active,
            is_death_cross=ctx.is_death_cross,
            ma_gap_ratio=ctx.ma_gap_ratio,
            stoch_k=ctx.stoch_k,
            rsi=ctx.rsi,
        )

        # 7-1. 비중축소 Stage 결정
        ctx.sell_stage, stage_reasons = self._determine_sell_stage(
            sell_phase=ctx.sell_phase,
            is_death_cross=ctx.is_death_cross,
            is_gc_active=ctx.is_gc_active,
            stoch_k=ctx.stoch_k,
            rsi=ctx.rsi,
            ma_gap_ratio=ctx.ma_gap_ratio,
            adx=adx_indicators.get("adx"),
            plus_di=adx_indicators.get("plus_di"),
            minus_di=adx_indicators.get("minus_di"),
            is_volume_sell_signal=volume_indicators.get("is_volume_sell_signal", False),
            profit_ratio=ctx.profit_ratio,
            is_volume_spike=volume_indicators.get("is_volume_spike", False),
            is_volume_peak=volume_indicators.get("is_volume_peak", False),
            is_stoch_dead_cross=ctx.is_stoch_dead_cross,
            is_52week_high=ctx.is_52week_high,
            high_52week_ratio=ctx.high_52week_ratio,
            dynamic_stoch_threshold=ctx.dynamic_stoch,
            dynamic_rsi_threshold=ctx.dynamic_rsi,
            name=name,
            market=market,
        )
        # 오버레이 단계강화는 아래 최종 단계(final_stage)에 '최대 1회'만 적용한다.
        # 여기(rule stage)서 중복 적용하면 end-to-end 2단계 상승이 되어 문서/테스트
        # 불변식('실전 overlay는 최대 1회만 강화')을 위반하므로 rule stage에는 적용하지 않는다.
        # ctx.sell_stage는 순수 rule 결과로 유지되어 merge(rule vs score) 입력으로 쓰인다.

        ctx.sell_score_result = self.calculate_sell_score(
            stoch_k=ctx.stoch_k_raw,
            stoch_d=ctx.stoch_d_raw,
            prev_stoch_k=ctx.prev_stoch_k,
            prev_stoch_d=ctx.prev_stoch_d,
            rsi=ctx.rsi_raw,
            volume_ratio=volume_indicators.get("volume_ratio"),
            volume_peak_score=volume_indicators.get("volume_peak_score"),
            adx=adx_indicators.get("adx"),
            plus_di=adx_indicators.get("plus_di"),
            minus_di=adx_indicators.get("minus_di"),
            is_death_cross=ctx.is_death_cross,
            current_price=ctx.close,
            ma_short=ctx.ma_short,
            ma_long=ctx.ma_long,
            ma_gap_ratio=ctx.ma_gap_ratio,
            is_volume_peak=volume_indicators.get("is_volume_peak", False),
            is_volume_sell_signal=volume_indicators.get("is_volume_sell_signal", False),
            is_52week_high=ctx.is_52week_high,
            high_52week_score=ctx.high_52week_score if ctx.high_52week_value is not None else None,
            high_52week_reason=(
                ctx.high_52week_reason if ctx.high_52week_value is not None else None
            ),
            personal_buy_days_5d=(
                ctx.personal_flow_data.days_positive_count if ctx.personal_flow_data else None
            ),
            personal_buy_ratio_5d_to_volume=(
                ctx.personal_flow_data.recent_5d_buy_ratio_to_volume
                if ctx.personal_flow_data
                else None
            ),
            recent_5d_personal_net_buy=(
                ctx.personal_flow_data.recent_5d_net_buy if ctx.personal_flow_data else None
            ),
            market_credit_change_ratio=(
                ctx.market_credit_data.balance_change_ratio if ctx.market_credit_data else None
            ),
            market_credit_recent_high_ratio=(
                ctx.market_credit_data.recent_5d_high_ratio if ctx.market_credit_data else None
            ),
            risk_combo_peak=bool(ctx.overlay_signals.get("risk_combo_peak", False)),
            risk_combo_extreme=bool(ctx.overlay_signals.get("risk_combo_extreme", False)),
        )

        ctx.drawdown_from_high = None
        if highest_price is not None and highest_price > 0:
            ctx.drawdown_from_high = (highest_price - ctx.close) / highest_price

        final_stage = self.determine_final_stage(
            rule_stage=ctx.sell_stage,
            score_stage=ctx.sell_score_result.recommended_stage,
            use_scoring=use_scoring,
            merge_strategy=merge_strategy,
        )
        final_stage, position_stage_reasons = self._apply_position_risk_stage(
            final_stage,
            is_take_profit_triggered=ctx.is_take_profit_triggered,
            trailing_stop_activated=trailing_stop_activated,
            drawdown_from_high=ctx.drawdown_from_high,
        )
        stage_reasons.extend(position_stage_reasons)

        final_stage, final_overlay_stage_reasons = self._apply_overlay_stage_upgrade(
            final_stage,
            is_personal_buying_overheated=ctx.is_personal_buying_overheated,
            overlay_signals=ctx.overlay_signals,
        )
        stage_reasons.extend(final_overlay_stage_reasons)

        # sell_mode 기계적 보호 반영(simple/hybrid): compute_simple_sell_signal의 기계적 규칙을
        # final_stage에 실제 반영한다. 특히 '85% 피크수익 보호'는 메인 파이프라인의
        # take-profit(현재수익 ≥20%)/트레일링(활성화 임계 필요)으로 커버되지 않는 저수익 피크
        # 감쇠를 잡는데, 기존에는 reason 텍스트로만 남고 final_stage/비율에 미반영되어
        # 알림 심각도와 근거가 불일치했다. 단계는 '올리기만' 하며 legacy 모드는 영향 없음.
        if sell_mode in ("simple", "hybrid") and ctx.simple_sell_info:
            _simple_reasons = ctx.simple_sell_info.get("reasons", [])
            _mechanical = ctx.simple_sell_info.get("should_sell") and any(
                ("하드 손절" in r) or ("추세 이탈" in r) or ("85% 수익 보호" in r)
                for r in _simple_reasons
            )
            _rsi_decline = any("RSI 과매수 + 하락 시작" in r for r in _simple_reasons)
            if _mechanical and SELL_STAGE_ORDER.index(final_stage) < SELL_STAGE_ORDER.index(
                SellStageEnum.REDUCE_2
            ):
                final_stage = SellStageEnum.REDUCE_2
                stage_reasons.append(f"[MODE:{sell_mode}] 기계적 보호 규칙 → REDUCE_2")
            if _rsi_decline and final_stage == SellStageEnum.REDUCE_1:
                # 실제 상승(REDUCE_1→REDUCE_2)이 일어날 때만 '가속'으로 기재한다.
                final_stage = SellStageEnum.REDUCE_2
                stage_reasons.append(f"[MODE:{sell_mode}] RSI+하락 확인 → 가속(REDUCE_2)")

        ctx.final_stage = final_stage

        ctx.final_ratio_min, ctx.final_ratio_max = SELL_STAGE_RATIOS.get(final_stage, (0.0, 0.0))

        # Stage 기반 매도 비율 계산
        sell_ratios = SELL_STAGE_RATIOS.get(ctx.sell_stage, (0.0, 0.0))
        ctx.sell_ratio_min, ctx.sell_ratio_max = sell_ratios

        # Stage 정보
        ctx.stage_info = SELL_STAGE_INFO.get(ctx.sell_stage.value, SELL_STAGE_INFO["HOLD"])

        # 과매수 매도 차단 여부 (ADX 강한 상승 추세)
        ctx.overbought_sell_blocked = (
            adx_indicators.get("is_strong_uptrend", False)
            and not ctx.is_death_cross
            and not volume_indicators.get("is_volume_sell_signal", False)
            and ctx.sell_stage == SellStageEnum.HOLD
        )

        # 8. 매도 근거 수집
        sell_reasons = self._collect_sell_reasons(
            is_death_cross=ctx.is_death_cross,
            is_stoch_overbought=ctx.is_stoch_overbought,
            is_rsi_overbought=ctx.is_rsi_overbought,
            ma_short=ctx.ma_short,
            ma_long=ctx.ma_long,
            stoch_k=ctx.stoch_k,
            stoch_overbought=ctx.dynamic_stoch,
            rsi=ctx.rsi,
            rsi_overbought=ctx.dynamic_rsi,
            ma_gap_ratio=ctx.ma_gap_ratio,
            profit_ratio=ctx.profit_ratio,
            is_stop_loss_triggered=ctx.is_stop_loss_triggered,
            is_take_profit_triggered=ctx.is_take_profit_triggered,
        )

        # Phase 근거 추가
        sell_reasons.extend(phase_reasons)
        sell_reasons.extend(ctx.personal_flow_reasons)
        sell_reasons.extend(ctx.market_credit_reasons)
        sell_reasons.extend(ctx.overlay_signals.get("combo_reasons", []))

        if not sell_reasons:
            sell_reasons.append("현재 매도 시그널 없음 - 보유 유지")

        # Phase 정보
        ctx.phase_info = SELL_PHASE_INFO.get(ctx.sell_phase.value, SELL_PHASE_INFO["NONE"])

        logger.info(
            f"[Sell Signal] {symbol}: phase={ctx.sell_phase.value}, "
            f"stage={ctx.sell_stage.value}, "
            f"phase_name={ctx.phase_info['name']}, profit_ratio={ctx.profit_ratio}, "
            f"adx={adx_indicators.get('adx')}, "
            f"volume_spike={volume_indicators.get('is_volume_spike')}"
        )

        # Mode support (simple/hybrid) - simple_compute already injected earlier
        # For full hybrid stage upgrade, use analyze_sell_signal_hybrid or post-process the DTO
        simple_sell_info = ctx.simple_sell_info
        if sell_mode in ("simple", "hybrid") and simple_sell_info is not None:
            if simple_sell_info.get("should_sell"):
                # Append to reasons for visibility
                sell_reasons = list(sell_reasons) + [
                    "[MODE:" + sell_mode + "] " + r for r in simple_sell_info.get("reasons", [])
                ]

        ctx.stage_reasons = stage_reasons
        ctx.sell_reasons = sell_reasons

    def _to_sell_dto(
        self,
        ctx: _SellAnalysisContext,
        *,
        symbol: str,
        name: str | None,
        analyzed_at: datetime,
        entry_price: float | None,
        highest_price: float | None,
        trailing_stop_activated: bool,
        merge_strategy: str,
    ) -> SellSignalAnalysisDTO:
        """확정된 컨텍스트를 매도 시그널 DTO로 직렬화."""
        volume_indicators = ctx.volume_indicators
        adx_indicators = ctx.adx_indicators
        personal_flow_data = ctx.personal_flow_data
        market_credit_data = ctx.market_credit_data
        sell_score_result = ctx.sell_score_result

        return SellSignalAnalysisDTO(
            symbol=symbol,
            name=name,
            current_price=Decimal(str(ctx.close)),
            analyzed_at=analyzed_at,
            ma_short=Decimal(str(round(ctx.ma_short, 2))),
            ma_long=Decimal(str(round(ctx.ma_long, 2))),
            ma_gap_ratio=round(ctx.ma_gap_ratio, 2),
            is_death_cross=ctx.is_death_cross,
            is_gc_active=ctx.is_gc_active,
            stoch_k=round(ctx.stoch_k, 2),
            stoch_d=round(ctx.stoch_d, 2),
            is_stoch_overbought=ctx.is_stoch_overbought,
            is_stoch_dead_cross=ctx.is_stoch_dead_cross,
            stoch_cross_type=ctx.stoch_cross_type,
            prev_stoch_k=round(ctx.prev_stoch_k, 2) if ctx.prev_stoch_k is not None else None,
            prev_stoch_d=round(ctx.prev_stoch_d, 2) if ctx.prev_stoch_d is not None else None,
            rsi=round(ctx.rsi, 2),
            is_rsi_overbought=ctx.is_rsi_overbought,
            # 52주 신고가 관련
            is_52week_high=ctx.is_52week_high,
            high_52week=(
                Decimal(str(ctx.high_52week_value)) if ctx.high_52week_value is not None else None
            ),
            high_52week_ratio=(
                round(ctx.high_52week_ratio, 4) if ctx.high_52week_ratio is not None else None
            ),
            high_52week_data_note=ctx.high_52week_note,
            # Phase 기반 매도 시그널
            sell_phase=ctx.sell_phase.value,
            sell_phase_name=ctx.phase_info["name"],
            sell_phase_action=ctx.phase_info["action"],
            sell_reasons=ctx.sell_reasons,
            # 수익률 관련
            entry_price=Decimal(str(entry_price)) if entry_price else None,
            profit_ratio=round(ctx.profit_ratio, 4) if ctx.profit_ratio is not None else None,
            dynamic_stoch_threshold=round(ctx.dynamic_stoch, 1),
            dynamic_rsi_threshold=round(ctx.dynamic_rsi, 1),
            # 손절/익절 상태
            is_stop_loss_triggered=ctx.is_stop_loss_triggered,
            is_take_profit_triggered=ctx.is_take_profit_triggered,
            # 트레일링 스탑 관련
            highest_price=Decimal(str(highest_price)) if highest_price else None,
            drawdown_from_high=(
                round(ctx.drawdown_from_high, 4) if ctx.drawdown_from_high is not None else None
            ),
            trailing_stop_activated=trailing_stop_activated,
            # === 비중축소 관련 신규 필드 ===
            sell_stage=ctx.sell_stage.value,
            sell_stage_name=ctx.stage_info["name"],
            sell_ratio_min=ctx.sell_ratio_min,
            sell_ratio_max=ctx.sell_ratio_max,
            sell_quantity_suggested=None,  # 보유 수량 정보가 있을 때 별도 계산
            holding_quantity=None,  # 보유 수량은 외부에서 제공
            sold_ratio=0.0,
            sell_stage_reasons=ctx.stage_reasons,
            sell_score_result=sell_score_result,
            score_based_stage=(
                sell_score_result.recommended_stage.value
                if hasattr(sell_score_result.recommended_stage, "value")
                else str(sell_score_result.recommended_stage)
            ),
            final_stage=ctx.final_stage,
            final_ratio_min=ctx.final_ratio_min,
            final_ratio_max=ctx.final_ratio_max,
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
            overbought_sell_blocked=ctx.overbought_sell_blocked,
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
                if personal_flow_data
                and personal_flow_data.recent_5d_buy_ratio_to_volume is not None
                else None
            ),
            is_personal_buying_overheated=ctx.is_personal_buying_overheated,
            market_credit_label=(market_credit_data.market_label if market_credit_data else None),
            market_credit_balance_million=(
                market_credit_data.latest_balance_million if market_credit_data else None
            ),
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
            is_market_credit_overheated=ctx.is_market_credit_overheated,
            candle_count=ctx.candle_count,
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

        # MA 상태 점수 (service 헬퍼로 산출 후 규칙으로 래핑)
        ma_score, ma_reasons = self._calculate_ma_position_score(
            current_price=current_price,
            ma_short=ma_short,
            ma_long=ma_long,
            ma_gap_ratio=ma_gap_ratio,
        )

        # Stoch 데드크로스 감지 (stoch_k/stoch_d 모두 존재할 때만)
        cross_detection: tuple[bool, float, str] | None = None
        if stoch_k is not None and stoch_d is not None:
            cross_detection = self._check_stoch_dead_cross(
                stoch_k, stoch_d, prev_stoch_k, prev_stoch_d
            )

        # ADX 강세 감점 (service 헬퍼로 산출 후 규칙으로 래핑)
        adx_penalty, adx_penalty_reason = self._calculate_adx_penalty(
            adx, plus_di, minus_di, config
        )

        # 각 규칙이 점수(points)와 가용 최대치(max_points)를 한 곳에서 함께 산출한다.
        # 총점/가용 최대치를 동일한 규칙 리스트에서 합산하여 기존 available_max 미러를 제거.
        # 리스트 순서 = 기존 total_score 누적 순서(부동소수 결과 보존).
        rules: list[ScoreRule] = [
            stoch_rule(stoch_k, config),
            rsi_rule(rsi, config),
            volume_rule(
                volume_ratio,
                volume_peak_score,
                is_volume_peak,
                is_volume_sell_signal,
                config,
            ),
            high_52week_rule(high_52week_score, high_52week_reason),
            personal_flow_rule(
                recent_5d_personal_net_buy,
                personal_buy_days_5d,
                personal_buy_ratio_5d_to_volume,
                config,
            ),
            market_credit_rule(
                market_credit_change_ratio,
                market_credit_recent_high_ratio,
                config,
            ),
            adx_rule(adx, config),
            ma_rule(ma_score, ma_reasons, config),
            cross_rule(stoch_k, stoch_d, cross_detection, config),
            overbought_bonus_rule(is_52week_high, stoch_k),
            risk_combo_rule(risk_combo_peak, risk_combo_extreme, config),
            adx_penalty_rule(adx_penalty, adx_penalty_reason),
        ]

        total_score = 0.0
        for rule in rules:
            total_score += rule.points
        # 개별 max 항을 순서대로 누적하여 기존 인라인 available_max 누적과
        # bit-identical 하게 유지(거래량 weight 후 피크 +5 등 규칙 내 다중 항 포함).
        available_max = 0.0
        for rule in rules:
            for term in rule.max_contributions():
                available_max += term
        for rule in rules:
            score_reasons.extend(rule.reasons)

        merged_breakdown: dict[str, float] = {}
        for rule in rules:
            merged_breakdown.update(rule.breakdown)

        normalized_score = (total_score / available_max) * 100 if available_max > 0 else 0.0

        if normalized_score >= config.exit_all_threshold:
            recommended_stage = SellStageEnum.EXIT_ALL
        elif normalized_score >= config.reduce_2_threshold:
            recommended_stage = SellStageEnum.REDUCE_2
        elif normalized_score >= config.reduce_1_threshold:
            recommended_stage = SellStageEnum.REDUCE_1
        else:
            recommended_stage = SellStageEnum.HOLD

        # 기존 키 순서를 그대로 유지 (dict 동등성 및 출력 안정성 보존)
        score_breakdown = {
            "stoch_score": merged_breakdown["stoch_score"],
            "rsi_score": merged_breakdown["rsi_score"],
            "volume_score": merged_breakdown["volume_score"],
            "volume_peak_score": merged_breakdown["volume_peak_score"],
            "high_52week_score": merged_breakdown["high_52week_score"],
            "high_52week_bonus": merged_breakdown["high_52week_bonus"],
            "personal_flow_score": merged_breakdown["personal_flow_score"],
            "market_credit_score": merged_breakdown["market_credit_score"],
            "risk_combo_bonus": merged_breakdown["risk_combo_bonus"],
            "adx_score": merged_breakdown["adx_score"],
            "ma_score": merged_breakdown["ma_score"],
            "cross_score": merged_breakdown["cross_score"],
            "adx_penalty": merged_breakdown["adx_penalty"],
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

        return max(rule_stage, score_stage, key=lambda s: SELL_STAGE_ORDER.index(s))

    def _apply_position_risk_stage(
        self,
        stage: SellStageEnum,
        *,
        is_take_profit_triggered: bool,
        trailing_stop_activated: bool,
        drawdown_from_high: float | None,
        trailing_stop_distance: float = 0.07,
    ) -> tuple[SellStageEnum, list[str]]:
        """익절/트레일링 상태를 최종 Stage에 반영한다."""
        reasons: list[str] = []

        if (
            trailing_stop_activated
            and drawdown_from_high is not None
            and drawdown_from_high >= trailing_stop_distance
        ):
            if stage != SellStageEnum.EXIT_ALL:
                reasons.append(
                    f"트레일링 스탑 발동: 고점 대비 {drawdown_from_high * 100:.1f}% 하락"
                )
            return SellStageEnum.EXIT_ALL, reasons

        if not is_take_profit_triggered:
            return stage, reasons

        target_stage = SellStageEnum.REDUCE_2
        if SELL_STAGE_ORDER.index(stage) < SELL_STAGE_ORDER.index(target_stage):
            reasons.append("익절 목표 도달로 최종 Stage를 2차 비중 축소로 강화")
            return target_stage, reasons

        return stage, reasons

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
        if is_52week_high or (
            high_52week_ratio is not None
            and high_52week_ratio >= DEFAULT_PEAK_RULE_THRESHOLDS.near_high_ratio
        ):
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
                reasons.append("[sharp v1] ETF/레버리지 계열은 이익 보호 기준을 더 엄격하게 적용")
            reasons.extend(top_signals[:4])
            return SellStageEnum.REDUCE_2, reasons

        if profit_ratio >= early_profit_threshold and signal_count >= reduce_1_signal_threshold:
            reasons.append(
                f"[sharp v1] 수익 구간 선제 축소: 상단 경고 {signal_count}개 정렬 "
                f"(수익률 {profit_ratio * 100:.1f}%)"
            )
            if is_etf_like:
                reasons.append("[sharp v1] ETF/레버리지 계열은 수익 종목 우선 현금화 대상")
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
            is_gc_active: 골든크로스 활성 여부 (단기 MA > 장기 MA)
            is_death_cross: 데드크로스 여부 (단기 MA < 장기 MA)
            ma_gap_ratio: MA 갭 비율 (%)
            stoch_k: Stochastic %K
            rsi: RSI

        Returns:
            tuple[SellPhaseEnum, list[str]]: (Phase, 근거 리스트)

        Note:
            단기 MA == 장기 MA인 경우 is_gc_active=False, is_death_cross=False로 처리됨
        """
        reasons: list[str] = []

        # PHASE_5: 데드크로스 + 극단적 과열
        if is_death_cross and stoch_k > 90 and rsi > 85:
            reasons.append(
                f"[Phase 5] 데드크로스 + 극단적 과열 (Stoch {stoch_k:.1f}, RSI {rsi:.1f})"
            )
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
            reasons.append(
                f"[Phase 1] 골든크로스 유지 + 극심한 과열 (Stoch {stoch_k:.1f}, RSI {rsi:.1f})"
            )
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
            sell_reasons.append(
                f"데드크로스 발생 (MA{settings.gc_short_ma_period} {ma_short:,.0f} "
                f"< MA{settings.gc_long_ma_period} {ma_long:,.0f})"
            )

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

        volume_ma_20 = TechnicalIndicators.calculate_volume_ma(valid_volumes, period=20)

        if volume_ma_20 is None or volume_ma_20 <= 0:
            result["current_volume"] = current_volume
            result["prev_volume"] = prev_volume
            return result

        # 거래량 비율 및 급증 여부
        volume_ratio = TechnicalIndicators.calculate_volume_ratio(current_volume, volume_ma_20)
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

    def compute_simple_sell_signal(
        self,
        df: pd.DataFrame,
        rsi: float,
        current_price: float,
        entry_price: float | None = None,
        highest_price: float | None = None,
    ) -> dict:
        """
        단순 매도 규칙 (사용자 지정, 수정됨 2026-07-31):
        - RSI >= 70 **AND** 하락 시작 확인 (RSI만으로는 선제 매도 안 함)
        - 최근 20일 고점(일봉 종가) 대비 15% 이탈
        - 85% 수익 지키기 (peak profit의 85% 보호)
        """
        reasons = []
        should_sell = False

        # 1. RSI >=70 + 하락 시작 확인 (#6: 1틱 whipsaw 방지 — 3일선 하회 & 2봉 연속 하락)
        if rsi is not None and rsi >= 70:
            decline_confirmed = False
            decline_detail = ""

            if len(df) >= 2 and "close" in df.columns:
                closes = df["close"].astype(float)
                prev_close = float(closes.iloc[-2])
                ma_window = min(3, len(closes))
                ma_short = float(closes.tail(ma_window).mean())
                below_ma = current_price < ma_short
                rolling_down = False
                if len(closes) >= 3:
                    prev2_close = float(closes.iloc[-3])
                    rolling_down = prev2_close >= prev_close >= current_price
                # 히스토리 부족 시(3봉 미만) 단일 하락 폴백
                if (below_ma and rolling_down) or (len(closes) < 3 and current_price < prev_close):
                    decline_confirmed = True
                    decline_detail = f" (3일선 {ma_short:.0f} 하회 + 연속 하락)"

            if decline_confirmed:
                should_sell = True
                reasons.append(f"RSI 과매수 + 하락 시작 (RSI={rsi:.1f}){decline_detail}")
            else:
                # RSI 70 넘었지만 하락 미확인 → 매도 사유로 추가하지 않음 (승자 유지)
                reasons.append(f"RSI 과매수 상태 (RSI={rsi:.1f}) — 하락 시작 미확인 (매도 보류)")
        # 참고: RSI < 70이면 이 블록 스킵

        # 2. 기계적 손절 (#7): 진입가 하드 손절 + 장기추세(장기 MA) 이탈.
        #    기존 '20일 고점 -15%' 고아 규칙 제거 — 85% 트레일링과 중복/오작동(회복장 조기청산).
        if entry_price and current_price < entry_price * (1 - settings.sell_hard_stop_pct):
            should_sell = True
            dd = (entry_price - current_price) / entry_price
            reasons.append(f"하드 손절: 진입가 대비 {dd:.1%} 하락")
        if "ma_long" in df.columns and len(df) >= 1:
            ma_long_last = df["ma_long"].iloc[-1]
            if (
                pd.notna(ma_long_last)
                and float(ma_long_last) > 0
                and current_price < float(ma_long_last) * (1 - settings.sell_trend_stop_pct)
            ):
                should_sell = True
                reasons.append(
                    f"추세 이탈: MA{settings.gc_long_ma_period} {settings.sell_trend_stop_pct:.0%} 하회"
                )

        # 3. 85% 수익 지키기 — 기계적 보호
        if entry_price and highest_price and highest_price > entry_price and current_price:
            peak_profit = (highest_price - entry_price) / entry_price
            curr_profit = (current_price - entry_price) / entry_price
            if curr_profit < peak_profit * 0.85:
                should_sell = True
                reasons.append(
                    f"85% 수익 보호 트리거 (peak={peak_profit:.1%}, 현재={curr_profit:.1%})"
                )

        return {
            "should_sell": should_sell,
            "reasons": reasons or ["단순 규칙 미발동"],
            "recent_20d_high": (
                float(df["close"].tail(20).max())
                if len(df) >= 20 and "close" in df.columns
                else None
            ),
        }

    async def analyze_sell_signal_hybrid(
        self,
        symbol: str,
        **kwargs,
    ) -> dict:
        """하이브리드: 기존 Legacy Phase + 단순 규칙 (보수적 overlay)

        - 20일 15% 이탈, 85% 수익보호: 기계적 강제 (리스크 관리)
        - RSI >=70 + 하락 시작: Legacy가 이미 약한 매도 신호를 낼 때만 업그레이드
        - 전체적으로 Legacy의 보수성을 최대한 유지 (적은 거래 선호)
        """
        # analyze_sell_signal은 df 파라미터가 없으므로 forward 전에 분리(TypeError 방지)
        df = kwargs.pop("df", None)
        legacy_result = await self.analyze_sell_signal(symbol, **kwargs)
        simple = self.compute_simple_sell_signal(
            df=df if df is not None else pd.DataFrame(),
            rsi=legacy_result.rsi,
            current_price=float(legacy_result.current_price),
            entry_price=kwargs.get("entry_price"),
            highest_price=kwargs.get("highest_price"),
        )

        final_stage = legacy_result.final_stage
        added_reasons = []

        if simple.get("should_sell"):
            simple_reasons = simple.get("reasons", [])

            # 기계적 보호 규칙 (15% DD, 85% 보호)은 강하게 적용
            mechanical = any(
                ("하드 손절" in r) or ("추세 이탈" in r) or ("85% 수익 보호" in r)
                for r in simple_reasons
            )
            rsi_decline = any("RSI 과매수 + 하락 시작" in r for r in simple_reasons)

            if mechanical:
                # 기계적 리스크는 강제 업그레이드
                if final_stage in (SellStageEnum.HOLD, SellStageEnum.REDUCE_1):
                    final_stage = SellStageEnum.REDUCE_2
                added_reasons.append("[HYBRID] 기계적 보호 규칙 트리거")

            if rsi_decline:
                # RSI + 하락은 Legacy가 이미 매도 기운일 때만 업그레이드
                if final_stage != SellStageEnum.HOLD:
                    # 이미 약한 매도 신호(REDUCE_1 이상)면 한 단계 더 강하게
                    if final_stage == SellStageEnum.REDUCE_1:
                        final_stage = SellStageEnum.REDUCE_2
                    added_reasons.append("[HYBRID] RSI+하락 확인 → 가속")
                else:
                    # Legacy가 HOLD면 그냥 이유만 추가 (강제 업그레이드 안 함)
                    added_reasons.append("[HYBRID] RSI+하락 감지 (Legacy HOLD 유지)")

            if added_reasons:
                legacy_result.sell_reasons = (
                    list(legacy_result.sell_reasons) + added_reasons + simple_reasons
                )

        return {
            "legacy": legacy_result,
            "simple": simple,
            "hybrid_stage": final_stage,
        }
