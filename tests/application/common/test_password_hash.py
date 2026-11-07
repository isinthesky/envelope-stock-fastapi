from src.application.common.password_hash import hash_password, verify_password


def test_hash_roundtrip_and_salted() -> None:
    first = hash_password("correct horse battery")
    second = hash_password("correct horse battery")

    assert first != second  # 랜덤 salt
    assert "$" not in first  # docker compose .env 보간 안전
    assert verify_password("correct horse battery", first)
    assert verify_password("correct horse battery", second)
    assert not verify_password("wrong", first)


def test_verify_rejects_malformed_or_abusive_hash() -> None:
    assert not verify_password("x", "")
    assert not verify_password("x", "plain-text-password")
    assert not verify_password("x", "bcrypt:1:2:3:aa:bb")
    assert not verify_password("x", "scrypt:16384:8:1:zz:bb")
    # DoS 방지: 과도한 cost 파라미터는 계산하지 않고 거부
    assert not verify_password("x", "scrypt:1073741824:8:1:aa:bb")
