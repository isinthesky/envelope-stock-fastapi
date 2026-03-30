# -*- coding: utf-8 -*-

from decimal import Decimal

import pytest

from src.application.domain.order.dto import OrderCreateRequestDTO


def test_market_order_allows_zero_price() -> None:
    dto = OrderCreateRequestDTO(
        symbol="005930",
        order_type="buy",
        price_type="market",
        price=Decimal("0"),
        quantity=1,
    )
    assert dto.price == Decimal("0")


def test_limit_order_requires_positive_price() -> None:
    with pytest.raises(ValueError):
        OrderCreateRequestDTO(
            symbol="005930",
            order_type="buy",
            price_type="limit",
            price=Decimal("0"),
            quantity=1,
        )
