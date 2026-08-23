"""매수·매도·백테스트가 공유하는 가격 기반 손절 계약."""

from decimal import Decimal

DEFAULT_PEAK_DRAWDOWN_STOP_RATIO = 0.15


def effective_peak_price(
    *,
    current_price: Decimal | float,
    entry_price: Decimal | float | None,
    highest_price: Decimal | float | None,
) -> float | None:
    """현재가를 포함해 단조 증가하는 유효 보유 고점을 반환한다."""
    candidates = [current_price, entry_price, highest_price]
    positive = [float(value) for value in candidates if value is not None and float(value) > 0]
    return max(positive) if positive else None


def peak_drawdown_ratio(
    *,
    current_price: Decimal | float,
    entry_price: Decimal | float | None,
    highest_price: Decimal | float | None,
) -> float | None:
    """진입 이후 최고가 대비 현재 낙폭을 반환한다.

    최고가는 최소 진입가 이상이어야 하며, 현재가가 새 고점이면 낙폭은 0이다.
    진입가와 최고가가 모두 없으면 손절을 판정할 근거가 없으므로 ``None``이다.
    """
    if entry_price is None and highest_price is None:
        return None
    current = float(current_price)
    peak = effective_peak_price(
        current_price=current_price,
        entry_price=entry_price,
        highest_price=highest_price,
    )
    if peak is None or current <= 0:
        return None
    return max(0.0, (peak - current) / peak)


def is_peak_drawdown_stop_triggered(
    *,
    current_price: Decimal | float,
    entry_price: Decimal | float | None,
    highest_price: Decimal | float | None,
    stop_ratio: float = DEFAULT_PEAK_DRAWDOWN_STOP_RATIO,
) -> bool:
    """현재가가 보유 중 최고가에서 손절 비율 이상 하락했는지 판정한다."""
    drawdown = peak_drawdown_ratio(
        current_price=current_price,
        entry_price=entry_price,
        highest_price=highest_price,
    )
    return drawdown is not None and drawdown >= abs(stop_ratio)
