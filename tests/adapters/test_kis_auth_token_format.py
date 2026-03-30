# -*- coding: utf-8 -*-

from src.adapters.external.kis_api.auth import format_token_expires_in


class _TokenInfoWithNoneRemaining:
    remaining_seconds = None


class _TokenInfoWithNegativeRemaining:
    remaining_seconds = -7


class _TokenInfoWithValidRemaining:
    remaining_seconds = 42


def test_format_token_expires_in_with_none_token_info() -> None:
    assert format_token_expires_in(None) == "unknown"


def test_format_token_expires_in_with_none_remaining_seconds() -> None:
    assert format_token_expires_in(_TokenInfoWithNoneRemaining()) == "unknown"


def test_format_token_expires_in_with_negative_remaining_seconds() -> None:
    assert format_token_expires_in(_TokenInfoWithNegativeRemaining()) == "0s"


def test_format_token_expires_in_with_valid_remaining_seconds() -> None:
    assert format_token_expires_in(_TokenInfoWithValidRemaining()) == "42s"
