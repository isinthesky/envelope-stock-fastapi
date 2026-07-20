# -*- coding: utf-8 -*-
"""종목코드 형식 검증 유틸 테스트

analysis_history에 사용자가 넣은 메모 행(MEMO-BROADCAST-1 등)이
종목코드로 취급되어 알림 파이프라인 전체가 실패하는 회귀를 방지한다.
"""

from src.application.domain.strategy.symbol_validation import (
    filter_tradable_items,
    is_valid_krx_symbol,
    split_valid_symbol_pairs,
    split_valid_symbols,
)


class TestIsValidKrxSymbol:
    def test_accepts_numeric_6digit_codes(self):
        assert is_valid_krx_symbol("005930") is True
        assert is_valid_krx_symbol("000660") is True
        assert is_valid_krx_symbol("495060") is True

    def test_accepts_alphanumeric_new_krx_codes(self):
        # 2026년 이후 신형 KRX 단축코드 (영문 대문자 포함, 예: TIGER ETF 0117V0)
        assert is_valid_krx_symbol("0117V0") is True

    def test_rejects_memo_rows(self):
        assert is_valid_krx_symbol("MEMO-BROADCAST-1") is False
        assert is_valid_krx_symbol("MEMO-BROADCAST-2") is False
        assert is_valid_krx_symbol("CXMT-MEMO") is False
        assert is_valid_krx_symbol("HALLOWEEN-STRAT") is False

    def test_rejects_wrong_length_or_type(self):
        assert is_valid_krx_symbol("5930") is False
        assert is_valid_krx_symbol("0059301") is False
        assert is_valid_krx_symbol("") is False
        assert is_valid_krx_symbol(None) is False
        assert is_valid_krx_symbol(5930) is False

    def test_rejects_lowercase_codes(self):
        assert is_valid_krx_symbol("0117v0") is False

    def test_strips_whitespace(self):
        assert is_valid_krx_symbol(" 005930 ") is True


class TestSplitValidSymbols:
    def test_splits_valid_and_skipped(self):
        valid, skipped = split_valid_symbols(
            ["005930", "MEMO-BROADCAST-1", "0117V0", "CXMT-MEMO"]
        )
        assert valid == ["005930", "0117V0"]
        assert skipped == ["MEMO-BROADCAST-1", "CXMT-MEMO"]

    def test_empty_input(self):
        assert split_valid_symbols([]) == ([], [])

    def test_valid_symbols_are_strip_normalized(self):
        # 검증은 strip 후 수행되므로, 반환값도 strip 정규화되어야
        # " 005930 " 같은 값이 그대로 KIS 조회에 전달되지 않는다
        valid, skipped = split_valid_symbols([" 005930 ", "\t0117V0\n", "MEMO-1"])
        assert valid == ["005930", "0117V0"]
        assert skipped == ["MEMO-1"]


class TestFilterTradableItems:
    def test_filters_items_by_symbol_key(self):
        items = [
            {"symbol": "005930", "name": "삼성전자", "market": "KOSPI"},
            {"symbol": "MEMO-BROADCAST-1", "name": "투자 메모", "market": None},
            {"symbol": "0117V0", "name": "TIGER ETF", "market": None},
        ]
        valid_items, skipped = filter_tradable_items(items)
        assert [item["symbol"] for item in valid_items] == ["005930", "0117V0"]
        assert skipped == ["MEMO-BROADCAST-1"]

    def test_missing_symbol_key_is_skipped(self):
        valid_items, skipped = filter_tradable_items([{"name": "이름만 있는 행"}])
        assert valid_items == []
        assert skipped == ["None"]

    def test_valid_item_symbol_is_strip_normalized_without_mutation(self):
        original = {"symbol": " 005930 ", "name": "삼성전자", "market": "KOSPI"}
        valid_items, skipped = filter_tradable_items([original])

        assert skipped == []
        assert valid_items[0]["symbol"] == "005930"
        assert valid_items[0]["name"] == "삼성전자"
        # 원본 dict는 변형되지 않는다 (shallow copy 반환)
        assert original["symbol"] == " 005930 "
        assert valid_items[0] is not original


class TestSplitValidSymbolPairs:
    def test_preserves_whitespace_variant_rows(self):
        pairs, skipped = split_valid_symbol_pairs(
            ["005930", " 005930 ", "MEMO-BROADCAST-1"]
        )
        assert pairs == [("005930", "005930"), (" 005930 ", "005930")]
        assert skipped == ["MEMO-BROADCAST-1"]

    def test_empty_input(self):
        pairs, skipped = split_valid_symbol_pairs([])
        assert pairs == []
        assert skipped == []
