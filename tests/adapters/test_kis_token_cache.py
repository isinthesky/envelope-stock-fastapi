"""KIS 토큰 캐시 회귀 테스트.

1) 파일명이 프로세스 시작일에 고정돼 다른 날 재기동하면 유효 토큰이 있어도 재발급하던 버그
2) KIS 만료 시각(KST)을 UTC naive now와 비교해 실제 만료 후 9시간 동안 유효로 오판하던 버그
3) KIS가 거부한 토큰을 캐시에서 다시 집어 재시도가 계속 실패하던 버그
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.adapters.external.kis_api import auth as auth_module
from src.adapters.external.kis_api.auth import KST, KISAuth, TokenInfo


def _write(path: Path, token: str, valid_date: Any) -> None:
    path.write_text(yaml.safe_dump({"token": token, "valid-date": valid_date}), encoding="utf-8")


@pytest.fixture()
def kis_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> KISAuth:
    monkeypatch.setattr(auth_module.Path, "home", lambda: tmp_path)
    instance = KISAuth()
    issued: list[str] = []

    async def _fake_issue() -> TokenInfo:
        token = f"issued-{len(issued) + 1}"
        issued.append(token)
        expires = (datetime.now(KST) + timedelta(hours=24)).replace(tzinfo=None)
        return TokenInfo(access_token=token, token_type="Bearer", expires_at=expires)

    monkeypatch.setattr(instance, "_request_new_token", _fake_issue)
    instance.issued = issued  # type: ignore[attr-defined]
    return instance


def test_naive_expiry_is_interpreted_as_kst_not_container_local_time() -> None:
    # KST 벽시계로 "지금 + 1시간"이면 TZ와 무관하게 약 1시간 남아야 한다(이전: UTC 컨테이너에서 +9h로 오판).
    naive_kst = (datetime.now(KST) + timedelta(hours=1)).replace(tzinfo=None)
    token = TokenInfo(access_token="t", token_type="Bearer", expires_at=naive_kst)

    assert 3500 <= token.remaining_seconds <= 3600

    expired_kst = (datetime.now(KST) - timedelta(minutes=1)).replace(tzinfo=None)
    assert TokenInfo(access_token="t", token_type="Bearer", expires_at=expired_kst).is_expired


@pytest.mark.asyncio
async def test_reuses_valid_token_from_older_dated_file_on_restart(kis_auth: KISAuth) -> None:
    # 장기 실행 프로세스가 시작일(10-28) 파일에 갱신 토큰을 써 둔 상황 → 다른 날 재기동해도 재사용해야 한다.
    valid = (datetime.now(KST) + timedelta(hours=10)).replace(tzinfo=None)
    _write(kis_auth.token_cache_dir / "KIS20261028", "long-running-token", valid)

    token = await kis_auth.refresh_token()

    assert token.access_token == "long-running-token"
    assert kis_auth.last_token_source == "cache"
    assert kis_auth.issued == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_picks_latest_expiry_and_ignores_expired_and_foreign_files(kis_auth: KISAuth) -> None:
    now = datetime.now(KST)
    d = kis_auth.token_cache_dir
    _write(d / "KIS20261101", "expired", (now - timedelta(hours=1)).replace(tzinfo=None))
    _write(d / "KIS20261102", "older", (now + timedelta(hours=2)).isoformat())
    _write(d / "KIS20261103", "newest", (now + timedelta(hours=20)).isoformat())
    _write(d / "notes.txt", "foreign", (now + timedelta(hours=99)).isoformat())
    (d / "KIS20261104").write_text("::: not yaml :::", encoding="utf-8")

    token = await kis_auth.refresh_token()

    assert token.access_token == "newest"


@pytest.mark.asyncio
async def test_rejected_token_is_not_reused_and_new_token_is_saved(kis_auth: KISAuth) -> None:
    valid = (datetime.now(KST) + timedelta(hours=10)).isoformat()
    _write(kis_auth.token_cache_dir / "KIS20261028", "server-rejected", valid)
    await kis_auth.refresh_token()

    token = await kis_auth.refresh_token(rejected_token="server-rejected")

    assert token.access_token == "issued-1"
    assert kis_auth.last_token_source == "issued"
    today = kis_auth.token_cache_dir / f"KIS{datetime.now(KST).strftime('%Y%m%d')}"
    assert today.exists() and oct(today.stat().st_mode & 0o777) == "0o600"
    saved = yaml.safe_load(today.read_text(encoding="utf-8"))
    assert saved["token"] == "issued-1" and "+09:00" in saved["valid-date"]
    assert not [p for p in kis_auth.token_cache_dir.iterdir() if p.name.startswith(".kis-token-")]

    # 재기동(새 인스턴스)도 방금 발급한 토큰을 재사용
    fresh = KISAuth()
    assert (await fresh.refresh_token()).access_token == "issued-1"


@pytest.mark.asyncio
async def test_concurrent_rejection_after_another_refresh_reuses_memory_token(
    kis_auth: KISAuth,
) -> None:
    await kis_auth.refresh_token()  # issued-1
    # 다른 코루틴이 이미 갱신한 뒤, 예전 토큰(old)으로 거부된 요청이 refresh를 부르면 재발급하지 않는다.
    token = await kis_auth.refresh_token(rejected_token="old")

    assert token.access_token == "issued-1"
    assert kis_auth.last_token_source == "memory"
    assert kis_auth.issued == ["issued-1"]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_proactive_refresh_issues_new_token_when_under_threshold(kis_auth: KISAuth) -> None:
    soon = (datetime.now(KST) + timedelta(minutes=30)).isoformat()
    _write(kis_auth.token_cache_dir / "KIS20261106", "expiring-soon", soon)
    assert (await kis_auth.refresh_token()).access_token == "expiring-soon"

    token = await kis_auth.refresh_token(min_valid_seconds=3600)

    assert token.access_token == "issued-1"
