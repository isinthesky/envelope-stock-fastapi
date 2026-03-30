# -*- coding: utf-8 -*-

from src.application.domain.order.order_id import build_order_id, split_order_id


def test_build_order_id() -> None:
    assert build_order_id("12345", "67890") == "12345+67890"


def test_split_order_id_with_plus() -> None:
    assert split_order_id("12345+67890") == ("12345", "67890")


def test_split_order_id_with_hyphen() -> None:
    assert split_order_id("12345-67890") == ("12345", "67890")


def test_split_order_id_with_legacy_compact() -> None:
    assert split_order_id("1234567890") == ("12345", "67890")


def test_split_order_id_invalid() -> None:
    assert split_order_id("12+345") == ("", "")
