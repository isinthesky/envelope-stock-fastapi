# -*- coding: utf-8 -*-
"""
Password Hash - stdlib scrypt 기반 비밀번호 해시/검증

외부 의존성 없이 `hashlib.scrypt`만 사용한다. 저장 형식은 `$` 없이 콜론 구분으로 두어
docker compose `.env` 보간(`$VAR`)에 깨지지 않게 한다.

    scrypt:<n>:<r>:<p>:<salt_hex>:<hash_hex>
"""

import hashlib
import hmac
import secrets

__all__ = ["hash_password", "verify_password"]

_SCHEME = "scrypt"
_N = 2**14
_R = 8
_P = 1
_DKLEN = 32
_SALT_BYTES = 16
# 저장된 해시의 파라미터가 과도하면(DoS) 검증하지 않는다.
_MAX_N = 2**17


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=_DKLEN,
        maxmem=256 * 1024 * 1024,
    )


def hash_password(password: str) -> str:
    """비밀번호를 scrypt 해시 문자열로 변환한다."""
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _derive(password, salt, _N, _R, _P)
    return f"{_SCHEME}:{_N}:{_R}:{_P}:{salt.hex()}:{digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """비밀번호가 해시와 일치하는지 상수 시간 비교로 검증한다. 형식 오류는 False."""
    try:
        scheme, n_s, r_s, p_s, salt_hex, hash_hex = encoded.split(":")
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    if scheme != _SCHEME or not (1 < n <= _MAX_N) or r < 1 or p < 1 or not expected:
        return False
    try:
        actual = _derive(password, salt, n, r, p)
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(actual, expected)
