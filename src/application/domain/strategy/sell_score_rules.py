# -*- coding: utf-8 -*-
"""
Sell score rules - 매도 점수 규칙 단위

``calculate_sell_score`` 의 12개 지표 블록을 각각 하나의 :class:`ScoreRule`
로 표현한다. 핵심 목적은 **각 규칙이 점수(points)와 가용 최대치(max_points)를
한 곳에서 함께 산출** 하도록 하여, 기존 코드에서 별도로 재구현되던
``available_max`` 미러(mirror)를 제거하는 것이다.

동작 보존(behavior preservation):
- 각 규칙의 산식/문구/반올림은 기존 ``calculate_sell_score`` 와 문자 단위로 동일하다.
- 총점은 규칙 순서대로(stoch→rsi→volume→...→penalty) 누적되어 기존 누적 순서를 유지한다.
- 가용 최대치는 각 규칙의 ``max_points`` 합으로 계산된다. 기본 가중치는 모두 정수
  값이라 합산 순서와 무관하게 부동소수 결과가 동일하다.
"""

from dataclasses import dataclass, field

from src.application.common.indicators import TechnicalIndicators
from src.settings.sell_score_settings import (
    DEFAULT_PEAK_RULE_THRESHOLDS,
    SellScoreSettings,
)


@dataclass(frozen=True, slots=True)
class ScoreRule:
    """단일 매도 점수 규칙의 결과.

    ``points`` 와 ``max_points`` 를 한 객체에서 함께 보유하므로, 총점과 가용
    최대치를 동일한 규칙 리스트에서 합산할 수 있다(미러 제거).

    Attributes:
        points: 규칙이 총점에 기여하는 값(감점이면 음수).
        max_points: 규칙이 가용 최대치(available_max)에 기여하는 값.
        reasons: 점수 근거 문구(누적 순서 보존용, 리스트 순서 유지).
        breakdown: ``score_breakdown`` 에 병합될 키/값(반올림 완료).
        max_terms: available_max 합산 시 순차 누적할 개별 항(부동소수 결합순서
            보존용). ``None`` 이면 ``(max_points,)`` 단일 항으로 간주한다. 기존
            인라인 코드가 한 규칙 안에서 여러 번 ``available_max += ...`` 하던
            경우(예: 거래량 weight 후 피크 +5)를 bit-identical 하게 재현한다.
    """

    points: float
    max_points: float
    reasons: list[str] = field(default_factory=list)
    breakdown: dict[str, float] = field(default_factory=dict)
    max_terms: tuple[float, ...] | None = None

    def max_contributions(self) -> tuple[float, ...]:
        """available_max 누적에 사용할 순서 있는 항들."""
        return self.max_terms if self.max_terms is not None else (self.max_points,)


def stoch_rule(stoch_k: float | None, config: SellScoreSettings) -> ScoreRule:
    """Stoch 과열 점수."""
    points = 0.0
    reasons: list[str] = []
    if stoch_k is not None:
        if stoch_k > 95:
            points = config.stoch_weight
            reasons.append(f"Stoch 매우 과열 (K={stoch_k:.1f} > 95)")
        elif stoch_k > 85:
            points = config.stoch_weight * (20.0 / 30.0)
            reasons.append(f"Stoch 과열 (K={stoch_k:.1f} > 85)")
        elif stoch_k > 70:
            points = config.stoch_weight * (10.0 / 30.0)
            reasons.append(f"Stoch 과열 초기 (K={stoch_k:.1f} > 70)")
    max_points = config.stoch_weight if stoch_k is not None else 0.0
    return ScoreRule(points, max_points, reasons, {"stoch_score": round(points, 2)})


def rsi_rule(rsi: float | None, config: SellScoreSettings) -> ScoreRule:
    """RSI 과열 점수."""
    points = 0.0
    reasons: list[str] = []
    if rsi is not None:
        if rsi > 80:
            points = config.rsi_weight
            reasons.append(f"RSI 매우 과열 (RSI={rsi:.1f} > 80)")
        elif rsi > 70:
            points = config.rsi_weight * (15.0 / 25.0)
            reasons.append(f"RSI 과열 (RSI={rsi:.1f} > 70)")
        elif rsi > 65:
            points = config.rsi_weight * (5.0 / 25.0)
            reasons.append(f"RSI 과열 초기 (RSI={rsi:.1f} > 65)")
    max_points = config.rsi_weight if rsi is not None else 0.0
    return ScoreRule(points, max_points, reasons, {"rsi_score": round(points, 2)})


def volume_rule(
    volume_ratio: float | None,
    volume_peak_score: float | None,
    is_volume_peak: bool,
    is_volume_sell_signal: bool,
    config: SellScoreSettings,
) -> ScoreRule:
    """거래량 점수 + 거래량 피크 보너스(둘의 max는 volume_weight + 5.0)."""
    volume_score = 0.0
    reasons: list[str] = []
    if volume_ratio is not None:
        if volume_ratio >= config.volume_ratio_high:
            volume_score = config.volume_weight
            reasons.append(f"거래량 폭증 ({volume_ratio:.2f}x)")
        elif volume_ratio >= config.volume_ratio_mid:
            volume_score = config.volume_weight * (15.0 / 20.0)
            reasons.append(f"거래량 급증 ({volume_ratio:.2f}x)")
        elif volume_ratio >= config.volume_ratio_low:
            volume_score = config.volume_weight * (10.0 / 20.0)
            reasons.append(f"거래량 증가 ({volume_ratio:.2f}x)")

    peak_score_raw = volume_peak_score if volume_peak_score is not None else 0.0
    peak_score = peak_score_raw if is_volume_peak else 0.0
    if is_volume_peak:
        if is_volume_sell_signal and volume_score > 0 and peak_score > 0:
            volume_score = max(volume_score, peak_score)
            reasons.append("거래량 매도/피크 중복 → 높은 점수 적용")
        elif peak_score > 0:
            volume_score = max(volume_score, peak_score)
            reasons.append("거래량 피크 점수 반영")

        volume_score += 5.0
        reasons.append("거래량 피크 보너스 (+5)")

    # 기존 인라인 순서(available_max += volume_weight → += 5.0)를 그대로
    # 재현하기 위해 개별 항을 순서대로 보존한다(부동소수 결합순서 보존).
    max_term_list: list[float] = []
    if volume_ratio is not None:
        max_term_list.append(config.volume_weight)
    if is_volume_peak:
        max_term_list.append(5.0)
    max_points = 0.0
    for term in max_term_list:
        max_points += term

    return ScoreRule(
        volume_score,
        max_points,
        reasons,
        {
            "volume_score": round(volume_score, 2),
            "volume_peak_score": round(peak_score_raw, 2),
        },
        max_terms=tuple(max_term_list),
    )


def high_52week_rule(
    high_52week_score: float | None,
    high_52week_reason: str | None,
) -> ScoreRule:
    """52주 신고가 점수."""
    high_score = 0.0
    reasons: list[str] = []
    if high_52week_score is not None and high_52week_score > 0:
        high_score = high_52week_score
        if high_52week_reason:
            reasons.append(high_52week_reason)
    max_points = 10.0 if high_52week_score is not None else 0.0
    return ScoreRule(high_score, max_points, reasons, {"high_52week_score": round(high_score, 2)})


def personal_flow_rule(
    recent_5d_personal_net_buy: int | None,
    personal_buy_days_5d: int | None,
    personal_buy_ratio_5d_to_volume: float | None,
    config: SellScoreSettings,
) -> ScoreRule:
    """개인 수급 과열 점수."""
    personal_flow_score = 0.0
    reasons: list[str] = []
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
            reasons.append("개인 수급 과열 강함 (연속 순매수 + 거래량 대비 비중 높음)")
        elif (
            personal_buy_ratio_5d_to_volume is not None
            and personal_buy_days_5d >= config.personal_buy_days_threshold
            and personal_buy_ratio_5d_to_volume >= config.personal_buy_ratio_mid
        ):
            personal_flow_score = config.personal_flow_weight * 0.7
            reasons.append("개인 수급 과열 경고 (최근 5일 순매수 집중)")
        elif personal_buy_days_5d >= config.personal_buy_days_threshold:
            personal_flow_score = config.personal_flow_weight * 0.4
            reasons.append("개인 수급 쏠림 경고 (최근 5일 순매수 우세)")
    max_points = (
        config.personal_flow_weight
        if recent_5d_personal_net_buy is not None and recent_5d_personal_net_buy > 0
        else 0.0
    )
    return ScoreRule(
        personal_flow_score,
        max_points,
        reasons,
        {"personal_flow_score": round(personal_flow_score, 2)},
    )


def market_credit_rule(
    market_credit_change_ratio: float | None,
    market_credit_recent_high_ratio: float | None,
    config: SellScoreSettings,
) -> ScoreRule:
    """시장 신용 과열 점수."""
    market_credit_score = 0.0
    reasons: list[str] = []
    peak = DEFAULT_PEAK_RULE_THRESHOLDS
    if market_credit_change_ratio is not None and market_credit_recent_high_ratio is not None:
        if (
            market_credit_change_ratio >= peak.credit_extreme_change
            and market_credit_recent_high_ratio >= peak.credit_extreme_recent_high
        ):
            market_credit_score = config.market_credit_weight
            reasons.append("시장 신용 과열 강함 (일간 증가율 + 고점권)")
        elif (
            market_credit_change_ratio >= peak.credit_hot_change
            and market_credit_recent_high_ratio >= peak.credit_hot_recent_high
        ):
            market_credit_score = config.market_credit_weight * 0.625
            reasons.append("시장 신용 과열 경고 (증가율/고점권)")
    max_points = (
        config.market_credit_weight
        if market_credit_change_ratio is not None and market_credit_recent_high_ratio is not None
        else 0.0
    )
    return ScoreRule(
        market_credit_score,
        max_points,
        reasons,
        {"market_credit_score": round(market_credit_score, 2)},
    )


def adx_rule(adx: float | None, config: SellScoreSettings) -> ScoreRule:
    """ADX 약화 점수."""
    adx_score = 0.0
    reasons: list[str] = []
    if adx is not None:
        adx_score, adx_label = TechnicalIndicators.calculate_adx_weakness_score(adx)
        if adx_score > 0:
            reasons.append(f"ADX {adx_label} (ADX={adx:.1f})")
    max_points = config.adx_weight if adx is not None else 0.0
    return ScoreRule(adx_score, max_points, reasons, {"adx_score": round(adx_score, 2)})


def ma_rule(
    ma_score: float,
    ma_reasons: list[str],
    config: SellScoreSettings,
) -> ScoreRule:
    """MA 상태 점수(점수는 service._calculate_ma_position_score 에서 산출)."""
    reasons = list(ma_reasons) if ma_reasons else []
    max_points = config.ma_weight + 3.0
    return ScoreRule(ma_score, max_points, reasons, {"ma_score": round(ma_score, 2)})


def cross_rule(
    stoch_k: float | None,
    stoch_d: float | None,
    cross_detection: tuple[bool, float, str] | None,
    config: SellScoreSettings,
) -> ScoreRule:
    """Stoch 데드크로스 보너스.

    ``cross_detection`` 은 stoch_k/stoch_d 가 모두 존재할 때만
    ``service._check_stoch_dead_cross(...)`` 결과가 전달된다.
    """
    cross_score = 0.0
    reasons: list[str] = []
    if stoch_k is not None and stoch_d is not None and cross_detection is not None:
        is_dead_cross, raw_cross_score, cross_reason = cross_detection
        if is_dead_cross and raw_cross_score > 0:
            cross_score = raw_cross_score * (config.cross_bonus / 10.0)
            if cross_reason:
                reasons.append(cross_reason)
    max_points = config.cross_bonus if stoch_d is not None else 0.0
    return ScoreRule(cross_score, max_points, reasons, {"cross_score": round(cross_score, 2)})


def overbought_bonus_rule(is_52week_high: bool, stoch_k: float | None) -> ScoreRule:
    """52주 신고가 + 과매수 조합 보너스."""
    overbought_bonus = 0.0
    reasons: list[str] = []
    if is_52week_high and stoch_k is not None and stoch_k > 85:
        overbought_bonus = 5.0
        reasons.append("신고가 + 과매수 조합 (+5)")
    max_points = overbought_bonus if overbought_bonus > 0 else 0.0
    return ScoreRule(
        overbought_bonus,
        max_points,
        reasons,
        {"high_52week_bonus": round(overbought_bonus, 2)},
    )


def risk_combo_rule(
    risk_combo_peak: bool,
    risk_combo_extreme: bool,
    config: SellScoreSettings,
) -> ScoreRule:
    """개인 수급+시장 신용(+고점권) 조합 보너스."""
    risk_combo_bonus = 0.0
    reasons: list[str] = []
    if risk_combo_extreme:
        risk_combo_bonus = config.risk_combo_weight
        reasons.append("개인 수급+시장 신용+고점권 피크 보너스")
    elif risk_combo_peak:
        risk_combo_bonus = config.risk_combo_weight * 0.5
        reasons.append("개인 수급+시장 신용 동시 과열 보너스")
    max_points = config.risk_combo_weight if (risk_combo_peak or risk_combo_extreme) else 0.0
    return ScoreRule(
        risk_combo_bonus,
        max_points,
        reasons,
        {"risk_combo_bonus": round(risk_combo_bonus, 2)},
    )


def adx_penalty_rule(adx_penalty: float, adx_penalty_reason: str | None) -> ScoreRule:
    """ADX 강세 감점(점수는 service._calculate_adx_penalty 에서 산출).

    감점은 가용 최대치(max_points)에 기여하지 않는다(기존 동작 보존).
    """
    reasons: list[str] = []
    if adx_penalty != 0.0 and adx_penalty_reason:
        reasons.append(adx_penalty_reason)
    return ScoreRule(adx_penalty, 0.0, reasons, {"adx_penalty": round(adx_penalty, 2)})
