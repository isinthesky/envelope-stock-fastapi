# -*- coding: utf-8 -*-
"""
KRX KIND Client - 상장법인 목록 다운로드 (순수 I/O)

kind.krx.co.kr의 corpList.do(엑셀 다운로드) 엔드포인트를 호출해
(종목코드, 회사명) 목록을 반환한다. 비즈니스 규칙/정책 결정은 하지 않는다.
"""

import re

import httpx


async def fetch_kind_corp_list(market_type: str) -> list[tuple[str, str]]:
    """KRX KIND 상장법인 목록 조회

    Args:
        market_type: "stockMkt"(KOSPI) 또는 "kosdaqMkt"(KOSDAQ)

    Returns:
        (6자리 종목코드, 회사명) 튜플 리스트
    """
    url = (
        "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download"
        f"&marketType={market_type}"
    )
    async with httpx.AsyncClient(
        timeout=20.0,
        headers={"User-Agent": "Mozilla/5.0"},
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        html = resp.content.decode("euc-kr", errors="ignore")

    # <tr><td>회사명</td><td>종목코드</td> ... 형태
    pairs = re.findall(
        r"<tr>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>",
        html,
        flags=re.IGNORECASE,
    )

    items: list[tuple[str, str]] = []
    for name, code in pairs:
        code = re.sub(r"\D", "", code or "")
        if not code:
            continue
        items.append((code.zfill(6), (name or "").strip()))
    return items
