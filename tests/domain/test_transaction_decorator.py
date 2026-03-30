# -*- coding: utf-8 -*-

import pytest

import src.application.common.decorators as decorators_module
from src.application.common.decorators import transaction


class _FakeAsyncSession:
    def __init__(self) -> None:
        self.committed = 0
        self.rolled_back = 0

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


class _FakeSessionContext:
    def __init__(self, session: _FakeAsyncSession, counter: dict[str, int]) -> None:
        self._session = session
        self._counter = counter

    async def __aenter__(self) -> _FakeAsyncSession:
        self._counter["opened"] += 1
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _Service:
    @transaction
    async def do_work(self, session, value: int) -> int:  # noqa: ANN001
        return value + 1


@pytest.mark.asyncio
async def test_transaction_uses_owned_session_for_external_call(monkeypatch: pytest.MonkeyPatch) -> None:
    owned_session = _FakeAsyncSession()
    counter = {"opened": 0}

    monkeypatch.setattr(decorators_module, "AsyncSession", _FakeAsyncSession)
    monkeypatch.setattr(
        decorators_module,
        "AsyncSessionLocal",
        lambda: _FakeSessionContext(owned_session, counter),
    )

    service = _Service()
    result = await service.do_work(1)

    assert result == 2
    assert counter["opened"] == 1
    assert owned_session.committed == 1
    assert owned_session.rolled_back == 0


@pytest.mark.asyncio
async def test_transaction_does_not_open_or_commit_when_session_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned_session = _FakeAsyncSession()
    external_session = _FakeAsyncSession()
    counter = {"opened": 0}

    monkeypatch.setattr(decorators_module, "AsyncSession", _FakeAsyncSession)
    monkeypatch.setattr(
        decorators_module,
        "AsyncSessionLocal",
        lambda: _FakeSessionContext(owned_session, counter),
    )

    service = _Service()
    result = await service.do_work(external_session, 1)

    assert result == 2
    assert counter["opened"] == 0
    assert owned_session.committed == 0
    assert owned_session.rolled_back == 0
