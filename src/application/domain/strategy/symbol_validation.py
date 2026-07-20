# -*- coding: utf-8 -*-
"""
Symbol Validation - 종목코드 형식 검증 유틸

analysis_history 등 사용자 편집이 가능한 테이블에는 종목코드 자리에
메모 행(예: MEMO-BROADCAST-1, HALLOWEEN-STRAT)이 들어올 수 있다.
알림/분석 파이프라인이 이런 행을 종목코드로 취급해 KIS/네이버 조회를
시도하면 실패가 누적되어 데이터 갱신 잡 전체가 실패 처리되므로,
파이프라인 진입 시점에 이 모듈로 형식 검증을 수행한다.

KRX 단축코드 규칙:
- 6자리 영숫자 (예: 005930, 000660)
- 2026년 이후 신규 상장분은 영문 대문자가 포함될 수 있음 (예: 0117V0)

KIS 국내주식 API의 FID_INPUT_ISCD는 6자리 단축코드만 받으므로,
6자리 초과 코드는 어차피 조회가 불가능해 걸러내는 것이 올바른 동작이다
(DB 실데이터도 전부 6자리, 2026-07 검증).
"""

import re

# KRX 단축코드: 6자리 대문자 영숫자 (예: 005930, 0117V0)
KRX_SYMBOL_PATTERN = re.compile(r"^[0-9A-Z]{6}$")


def is_valid_krx_symbol(symbol: object) -> bool:
    """종목코드 형식 검증 (6자리 영숫자)

    메모 행(MEMO-BROADCAST-1 등)처럼 종목코드 형식이 아닌 값을 걸러낸다.
    stock_universe 미등록 수동 추가 종목(ETF/ETN 등)도 허용해야 하므로
    형식 검증만 수행하고 마스터 존재 여부는 확인하지 않는다.
    """
    if not isinstance(symbol, str):
        return False
    return bool(KRX_SYMBOL_PATTERN.fullmatch(symbol.strip()))


def split_valid_symbols(symbols: list[str]) -> tuple[list[str], list[str]]:
    """종목코드 리스트를 (유효, 제외) 로 분리 (순서/중복 유지 없음: 입력 순서 유지)

    유효 항목은 strip 정규화된 값으로 반환한다 (" 005930 " → "005930").
    검증은 strip 후 수행하므로 원본 그대로 반환하면 공백 포함 값이
    KIS 조회에 전달될 수 있다.
    """
    valid: list[str] = []
    skipped: list[str] = []
    for symbol in symbols:
        if is_valid_krx_symbol(symbol):
            valid.append(symbol.strip())
        else:
            skipped.append(symbol)
    return valid, skipped


def split_valid_symbol_pairs(
    symbols: list[str],
) -> tuple[list[tuple[str, str]], list[str]]:
    """(raw, stripped) 쌍 리스트와 제외 목록으로 분리

    공백만 다른 원본 행이 공존해도 각 행을 개별 보존해야 하는 호출자용.
    DB 행 조회/갱신에는 raw를, 외부(KIS/유니버스 등) 조회에는 stripped를 쓴다.
    """
    pairs: list[tuple[str, str]] = []
    skipped: list[str] = []
    for symbol in symbols:
        if is_valid_krx_symbol(symbol):
            pairs.append((symbol, symbol.strip()))
        else:
            skipped.append(str(symbol))
    return pairs, skipped


def filter_tradable_items(
    items: list[dict], symbol_key: str = "symbol"
) -> tuple[list[dict], list[str]]:
    """symbol 키를 가진 dict 리스트에서 종목코드 형식이 아닌 항목 제외

    유효 항목의 symbol 값은 strip 정규화해 반환한다. 원본 dict는 변형하지
    않도록 shallow copy 후 symbol_key만 교체한다.

    Returns:
        (유효 항목 리스트, 제외된 symbol 값 리스트)
    """
    valid_items: list[dict] = []
    skipped: list[str] = []
    for item in items:
        symbol = item.get(symbol_key)
        if is_valid_krx_symbol(symbol):
            normalized = dict(item)
            normalized[symbol_key] = symbol.strip()
            valid_items.append(normalized)
        else:
            skipped.append(str(symbol))
    return valid_items, skipped
