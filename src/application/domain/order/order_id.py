# -*- coding: utf-8 -*-
"""
Order ID Helpers - 주문 ID 포맷 SSOT
"""


def build_order_id(org_no: str, odno: str) -> str:
    """
    ORGNO + ODNO 형식으로 주문 ID를 생성한다.
    """
    if not org_no or not odno:
        return ""
    return f"{org_no}+{odno}"


def split_order_id(order_id: str) -> tuple[str, str]:
    """
    주문 ID를 (ORGNO, ODNO)로 분리한다.

    허용 형식:
    - ORGNO+ODNO
    - ORGNO-ODNO
    - ORGNOODNO (ORGNO 5자리 + 나머지)

    실패 시 ('', '') 반환.
    """
    if not order_id:
        return "", ""

    org_no = ""
    odno = ""

    if "+" in order_id:
        org_no, odno = order_id.split("+", 1)
    elif "-" in order_id:
        org_no, odno = order_id.split("-", 1)
    elif len(order_id) > 5:
        org_no, odno = order_id[:5], order_id[5:]

    if len(org_no) == 5 and odno:
        return org_no, odno

    return "", ""
