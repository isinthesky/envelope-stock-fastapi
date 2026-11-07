# -*- coding: utf-8 -*-
"""
Price-only exit overlays (research opt-in, H5).

하이브리드 매도 규칙(`sell_strategy_service.compute_simple_sell_signal`)의 **가격만으로
판정 가능한 하드 컴포넌트**를 백테스트 청산 오버레이로 재현한다. FSM(라이브 parity)
청산에 **추가로** 적용되며, 기본 엔진은 오버레이 없음(기존 동작).

컴포넌트(각각 on/off):
    - trend_stop_pct      : 종가 < MA_long × (1 − pct)       (라이브 sell_trend_stop_pct, 기본 15%)
    - breakdown_20d_pct   : 종가 < 최근 20봉 최고 종가 × (1 − pct)  ("20일 15% 이탈")
    - profit_protect      : 피크수익 ≥ min_peak 이고 현재수익 < 피크수익 × keep_ratio
                            (85% 수익 보호, 최소 피크 5%)

보유 최고가 −15% 하드 손절은 이미 FSM(`process_price_stop`)에 있으므로 여기서 중복하지
않는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

OVERLAY_TREND_STOP = "overlay_trend_stop"
OVERLAY_BREAKDOWN_20D = "overlay_breakdown_20d"
OVERLAY_PROFIT_PROTECT = "overlay_profit_protect"

# TradeDTO.exit_reason 패턴 호환 매핑(사유 상세는 엔진 카운터로 별도 집계)
OVERLAY_TRADE_EXIT_REASON = {
    OVERLAY_TREND_STOP: "stop_loss",
    OVERLAY_BREAKDOWN_20D: "stop_loss",
    OVERLAY_PROFIT_PROTECT: "trailing_stop",
}


@dataclass(frozen=True, slots=True)
class ExitOverlay:
    trend_stop_pct: float | None = None
    breakdown_20d_pct: float | None = None
    breakdown_lookback: int = 20
    profit_protect: bool = False
    profit_protect_min_peak: float = 0.05
    profit_protect_keep_ratio: float = 0.85

    def describe(self) -> str:
        parts: list[str] = []
        if self.trend_stop_pct is not None:
            parts.append(f"trend<MA×{1 - self.trend_stop_pct:.2f}")
        if self.breakdown_20d_pct is not None:
            parts.append(f"{self.breakdown_lookback}d-high−{self.breakdown_20d_pct:.0%}")
        if self.profit_protect:
            parts.append(
                f"profit_keep{self.profit_protect_keep_ratio:.0%}"
                f"(peak≥{self.profit_protect_min_peak:.0%})"
            )
        return "+".join(parts) if parts else "no-overlay"

    def check(
        self,
        *,
        close: Decimal,
        entry_price: Decimal | None,
        highest_price: Decimal | None,
        ma_long: Decimal | None,
        recent_closes: Sequence[Decimal],
    ) -> str | None:
        """첫 번째로 발동한 오버레이 사유를 반환(없으면 None)."""
        c = float(close)
        if c <= 0:
            return None
        if self.trend_stop_pct is not None and ma_long is not None and float(ma_long) > 0:
            if c < float(ma_long) * (1.0 - self.trend_stop_pct):
                return OVERLAY_TREND_STOP
        if self.breakdown_20d_pct is not None and len(recent_closes) >= self.breakdown_lookback:
            window = recent_closes[-self.breakdown_lookback :]
            hi = max(float(x) for x in window)
            if hi > 0 and c < hi * (1.0 - self.breakdown_20d_pct):
                return OVERLAY_BREAKDOWN_20D
        if self.profit_protect and entry_price is not None and float(entry_price) > 0:
            e = float(entry_price)
            peak = max(float(highest_price) if highest_price is not None else e, c)
            if peak > e:
                peak_profit = (peak - e) / e
                curr_profit = (c - e) / e
                if (
                    peak_profit >= self.profit_protect_min_peak
                    and curr_profit < peak_profit * self.profit_protect_keep_ratio
                ):
                    return OVERLAY_PROFIT_PROTECT
        return None
