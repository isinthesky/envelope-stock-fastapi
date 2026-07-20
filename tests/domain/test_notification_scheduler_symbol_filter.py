# -*- coding: utf-8 -*-
"""알림 스케줄러의 메모 행(비종목코드) 필터링 회귀 테스트

analysis_history에 MEMO-BROADCAST-* 같은 메모 행이 있어도
sell 데이터 갱신/알림 파이프라인이 실패하지 않아야 한다.
"""

from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import src.application.domain.strategy.notification_scheduler as scheduler_module
from src.application.domain.strategy.notification_scheduler import NotificationScheduler

MEMO_ROWS = [
    {"symbol": "MEMO-BROADCAST-1", "name": "투자 메모 1", "market": None},
    {"symbol": "MEMO-BROADCAST-2", "name": "투자 메모 2", "market": None},
]
VALID_ROWS = [
    {"symbol": "005930", "name": "삼성전자", "market": "KOSPI"},
    {"symbol": "0117V0", "name": "TIGER 코리아AI전력기기TOP3플러스", "market": None},
]


@asynccontextmanager
async def _dummy_session():
    yield object()


@pytest.mark.asyncio
async def test_sell_data_update_job_skips_memo_rows(monkeypatch: pytest.MonkeyPatch):
    """메모 행은 warmup 대상에서 제외되고 잡은 성공해야 한다."""
    scheduler = NotificationScheduler()
    captured_symbols: list[list[str]] = []

    class DummyAnalysisHistoryRepository:
        def __init__(self, session):
            self.session = session

        async def get_active_symbols_with_names(self, analysis_type: str):
            assert analysis_type == "sell"
            return MEMO_ROWS + VALID_ROWS

    class DummyWarmupService:
        def __init__(self, session):
            self.session = session

        async def warmup_symbols(self, request, concurrency: int):
            captured_symbols.append(list(request.symbols))
            return SimpleNamespace(
                success_count=len(request.symbols),
                failed_count=0,
                errors=[],
                api_calls_made=len(request.symbols),
                duration_seconds=1.0,
            )

    monkeypatch.setattr(
        scheduler_module, "AnalysisHistoryRepository", DummyAnalysisHistoryRepository
    )
    monkeypatch.setattr(scheduler_module, "OHLCVWarmupService", DummyWarmupService)
    monkeypatch.setattr(scheduler_module, "get_async_session", lambda: _dummy_session())
    monkeypatch.setattr(scheduler, "_refresh_external_risk_caches", AsyncMock(return_value={}))

    result = await scheduler._sell_data_update_job(slot_label="09:30")

    assert captured_symbols == [["005930", "0117V0"]]
    assert result["success"] is True
    assert result["tracked_count"] == 2
    assert result["skipped_non_symbol_count"] == 2
    assert result["failed_count"] == 0


@pytest.mark.asyncio
async def test_sell_data_update_job_with_only_memo_rows_records_empty(
    monkeypatch: pytest.MonkeyPatch,
):
    """메모 행만 있으면 warmup 없이 성공(추적 0건)으로 기록된다."""
    scheduler = NotificationScheduler()

    class DummyAnalysisHistoryRepository:
        def __init__(self, session):
            self.session = session

        async def get_active_symbols_with_names(self, analysis_type: str):
            return list(MEMO_ROWS)

    monkeypatch.setattr(
        scheduler_module, "AnalysisHistoryRepository", DummyAnalysisHistoryRepository
    )
    monkeypatch.setattr(scheduler_module, "get_async_session", lambda: _dummy_session())

    result = await scheduler._sell_data_update_job(slot_label="09:30")

    assert result["success"] is True
    assert result["tracked_count"] == 0
    assert result["updated_count"] == 0


@pytest.mark.asyncio
async def test_sell_notification_job_excludes_memo_rows_from_tracked(
    monkeypatch: pytest.MonkeyPatch,
):
    """메모 행은 tracked_count에 포함되지 않아야 한다."""
    scheduler = NotificationScheduler()

    class DummyAnalysisHistoryRepository:
        def __init__(self, session):
            self.session = session

        async def get_active_symbols_with_names(self, analysis_type: str):
            return MEMO_ROWS + [{"symbol": "005930", "name": "삼성전자", "market": "KOSPI"}]

    class DummyStrategyService:
        async def refresh_analysis_history(self, analysis_type: str):
            return SimpleNamespace(
                items=[
                    SimpleNamespace(
                        symbol="005930",
                        name="삼성전자",
                        current_price=Decimal("70000"),
                        sell_phase="PHASE_1",
                        sell_stage="HOLD",
                        sell_stage_name="보유 유지",
                        sell_reasons=[],
                        volume_ratio=1.0,
                        is_volume_sell_signal=False,
                        is_volume_spike=False,
                    )
                ],
                errors=[],
            )

    notifier = SimpleNamespace(
        send_sell_signals_summary=AsyncMock(return_value=True),
        send_no_sell_signals_alert=AsyncMock(return_value=True),
    )

    monkeypatch.setattr(
        scheduler_module, "AnalysisHistoryRepository", DummyAnalysisHistoryRepository
    )
    monkeypatch.setattr(scheduler_module, "StrategyService", DummyStrategyService)
    monkeypatch.setattr(scheduler_module, "get_telegram_notifier", lambda: notifier)
    monkeypatch.setattr(scheduler_module, "get_async_session", lambda: _dummy_session())

    result = await scheduler.execute_sell_notification_now(slot_label="manual")

    assert result["success"] is True
    assert result["tracked_count"] == 1


@pytest.mark.asyncio
async def test_refresh_external_risk_caches_skips_memo_rows(monkeypatch: pytest.MonkeyPatch):
    """개인 수급 캐시 갱신도 메모 행을 건너뛴다."""
    scheduler = NotificationScheduler()
    refreshed: list[str] = []

    class DummyAnalysisHistoryRepository:
        def __init__(self, session):
            self.session = session

        async def get_active_symbols_with_names(self, analysis_type: str):
            return MEMO_ROWS + VALID_ROWS

    async def _refresh_market_credit_cache(**kwargs):
        return {"refreshed": True}

    class DummyNaverClient:
        async def refresh_personal_flow_cache(self, symbol: str):
            refreshed.append(symbol)

    monkeypatch.setattr(
        scheduler_module, "AnalysisHistoryRepository", DummyAnalysisHistoryRepository
    )
    monkeypatch.setattr(scheduler_module, "get_async_session", lambda: _dummy_session())
    monkeypatch.setattr(
        scheduler_module,
        "get_kofia_client",
        lambda: SimpleNamespace(refresh_market_credit_cache=_refresh_market_credit_cache),
    )
    monkeypatch.setattr(
        scheduler_module, "get_naver_stock_client", lambda: DummyNaverClient()
    )

    result = await scheduler._refresh_external_risk_caches()

    assert sorted(refreshed) == ["005930", "0117V0"]
    assert result["personal_flow_refreshed"] == 2
    assert sorted(result["personal_flow_symbols"]) == ["005930", "0117V0"]


@pytest.mark.asyncio
async def test_start_sets_misfire_grace_time_and_coalesce():
    """이벤트 루프 지연으로 잡이 초 단위 지각해도 skip되지 않도록 설정 확인."""
    scheduler = NotificationScheduler()
    captured_kwargs: dict = {}

    class DummyScheduler:
        def __init__(self, *args, **kwargs):
            captured_kwargs.update(kwargs)
            self.jobs = []

        def add_job(self, func, trigger, **kwargs):
            self.jobs.append({"func": func, "trigger": trigger, **kwargs})

        def start(self):
            pass

    with patch(
        "apscheduler.schedulers.asyncio.AsyncIOScheduler",
        side_effect=lambda *args, **kwargs: DummyScheduler(*args, **kwargs),
    ):
        await scheduler.start()

    job_defaults = captured_kwargs.get("job_defaults") or {}
    assert job_defaults.get("coalesce") is True
    assert job_defaults.get("misfire_grace_time", 0) >= 60


class TestEtfLeaderMapWhitespaceNormalization:
    """공백 변형 심볼도 ETF 대장주 맵/요약 조회에 매칭되어야 한다 (R4 회귀)."""

    def test_filter_duplicate_leader_alerts_with_padded_etf_symbol(self):
        cls = scheduler_module.NotificationScheduler
        etf_symbol = next(iter(cls.ETF_LEADER_MAP))
        leaders = cls.ETF_LEADER_MAP[etf_symbol]
        alerts = [
            {"symbol": f" {etf_symbol} "},
            {"symbol": leaders[0]},
        ]

        result = cls._filter_duplicate_leader_alerts(alerts)

        # 공백 변형 ETF 본체가 맵에 매칭되어 대장주 개별 알림이 숨겨져야 한다
        assert [a["symbol"] for a in result] == [f" {etf_symbol} "]

    def test_build_etf_leader_summary_with_padded_symbol(self):
        cls = scheduler_module.NotificationScheduler
        etf_symbol = next(iter(cls.ETF_LEADER_MAP))
        leaders = cls.ETF_LEADER_MAP[etf_symbol]
        analyzed = {
            leaders[0]: {
                "symbol": leaders[0],
                "name": "리더",
                "final_stage": "REDUCE_2",
            },
        }

        summary = cls._build_etf_leader_summary(f" {etf_symbol} ", analyzed)

        assert summary is not None
        assert "대장주 확인" in summary
