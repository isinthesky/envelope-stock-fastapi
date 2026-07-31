from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import src.application.domain.strategy.notification_scheduler as scheduler_module
from src.application.domain.strategy.notification_scheduler import NotificationScheduler


class _DummyScheduler:
    def __init__(self, *args, **kwargs):
        self.jobs = []
        self.started = False

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})

    def start(self):
        self.started = True

    def shutdown(self, wait=False):
        self.started = False


@pytest.mark.asyncio
async def test_start_registers_four_notifications_and_four_updates():
    scheduler = NotificationScheduler()

    with (
        patch(
            "apscheduler.schedulers.asyncio.AsyncIOScheduler",
            side_effect=lambda *args, **kwargs: _DummyScheduler(*args, **kwargs),
        ),
        patch.object(scheduler_module.settings, "buy_notification_enabled", True),
        patch.object(scheduler_module.settings, "sell_notification_enabled", True),
    ):
        await scheduler.start()

    assert scheduler.scheduler is not None
    assert scheduler.is_running is True
    assert scheduler.scheduler.started is True
    assert len(scheduler.scheduler.jobs) == 8

    job_ids = {job["id"] for job in scheduler.scheduler.jobs}
    assert job_ids == {
        "sell_data_update_0930",
        "sell_notification_0930",
        "buy_data_update_1130",
        "buy_notification_1130",
        "sell_data_update_1230",
        "sell_notification_1230",
        "buy_data_update_1430",
        "buy_notification_1430",
    }


@pytest.mark.asyncio
async def test_start_skips_buy_jobs_when_buy_notification_disabled():
    """BUY_NOTIFICATION_ENABLED=false면 매수 잡을 등록하지 않는다(매도는 유지)."""
    scheduler = NotificationScheduler()

    with (
        patch(
            "apscheduler.schedulers.asyncio.AsyncIOScheduler",
            side_effect=lambda *args, **kwargs: _DummyScheduler(*args, **kwargs),
        ),
        patch.object(scheduler_module.settings, "buy_notification_enabled", False),
        patch.object(scheduler_module.settings, "sell_notification_enabled", True),
    ):
        await scheduler.start()

    job_ids = {job["id"] for job in scheduler.scheduler.jobs}
    assert job_ids == {
        "sell_data_update_0930",
        "sell_notification_0930",
        "sell_data_update_1230",
        "sell_notification_1230",
    }
    assert not any(job_id.startswith("buy_") for job_id in job_ids)


@pytest.mark.asyncio
async def test_execute_buy_notification_now_uses_manual_slot_label():
    scheduler = NotificationScheduler()
    scheduler._buy_notification_job = AsyncMock(return_value={"success": True, "slot": "manual"})

    result = await scheduler.execute_buy_notification_now()

    scheduler._buy_notification_job.assert_awaited_once_with(slot_label="manual")
    assert result == {"success": True, "slot": "manual"}


@pytest.mark.asyncio
async def test_execute_sell_notification_now_uses_manual_slot_label():
    scheduler = NotificationScheduler()
    scheduler._sell_notification_job = AsyncMock(return_value={"success": True, "slot": "manual"})

    result = await scheduler.execute_sell_notification_now()

    scheduler._sell_notification_job.assert_awaited_once_with(slot_label="manual")
    assert result == {"success": True, "slot": "manual"}


@pytest.mark.asyncio
async def test_sell_notification_job_sends_summary_and_records_result(
    monkeypatch: pytest.MonkeyPatch,
):
    scheduler = NotificationScheduler()

    active_items = [
        {"symbol": "396500", "name": "TIGER ETF", "market": "ETF"},
        {"symbol": "005930", "name": "삼성전자", "market": "KOSPI"},
        {"symbol": "000660", "name": "SK하이닉스", "market": "KOSPI"},
    ]

    class DummyAnalysisHistoryRepository:
        def __init__(self, session):
            self.session = session

        async def get_active_symbols_with_names(self, analysis_type: str):
            assert analysis_type == "sell"
            return active_items

    class DummyStrategyService:
        async def refresh_analysis_history(self, analysis_type: str):
            assert analysis_type == "sell"
            return SimpleNamespace(
                items=[
                    SimpleNamespace(
                        symbol="396500",
                        name="TIGER ETF",
                        current_price=Decimal("10000"),
                        sell_phase="PHASE_4",
                        sell_stage="EXIT_ALL",
                        sell_stage_name="전량 청산",
                        sell_reasons=["ETF 약세"],
                        volume_ratio=1.7,
                        is_volume_sell_signal=True,
                        is_volume_spike=True,
                        is_personal_buying_overheated=True,
                        market_credit_label="KOSPI",
                        is_market_credit_overheated=True,
                    ),
                    SimpleNamespace(
                        symbol="005930",
                        name="삼성전자",
                        current_price=Decimal("70000"),
                        sell_phase="PHASE_4",
                        sell_stage="REDUCE_2",
                        sell_stage_name="2차 비중 축소",
                        sell_reasons=["대장주 약세"],
                        volume_ratio=1.2,
                        is_volume_sell_signal=False,
                        is_volume_spike=False,
                    ),
                    SimpleNamespace(
                        symbol="000660",
                        name="SK하이닉스",
                        current_price=Decimal("200000"),
                        sell_phase="PHASE_2",
                        sell_stage="REDUCE_1",
                        sell_stage_name="1차 비중 축소",
                        sell_reasons=["대장주 관찰"],
                        volume_ratio=1.1,
                        is_volume_sell_signal=False,
                        is_volume_spike=False,
                    ),
                ],
                errors=[],
            )

    notifier = SimpleNamespace(
        send_sell_signals_summary=AsyncMock(return_value=True),
        send_no_sell_signals_alert=AsyncMock(return_value=False),
    )

    @asynccontextmanager
    async def _dummy_session():
        yield object()

    monkeypatch.setattr(
        scheduler_module, "AnalysisHistoryRepository", DummyAnalysisHistoryRepository
    )
    monkeypatch.setattr(scheduler_module, "StrategyService", DummyStrategyService)
    monkeypatch.setattr(scheduler_module, "get_telegram_notifier", lambda: notifier)
    monkeypatch.setattr(scheduler_module, "get_async_session", lambda: _dummy_session())

    result = await scheduler.execute_sell_notification_now(slot_label="manual")

    assert result["success"] is True
    assert result["sent"] is True
    assert result["tracked_count"] == 3
    assert result["alert_count"] == 1
    assert result["top_alert_symbols"] == ["396500"]

    notifier.send_sell_signals_summary.assert_awaited_once()
    sent_payload = notifier.send_sell_signals_summary.await_args.args[0]
    assert sent_payload[0]["symbol"] == "396500"
    assert sent_payload[0]["is_personal_buying_overheated"] is True
    assert sent_payload[0]["market_credit_label"] == "KOSPI"
    assert sent_payload[0]["is_market_credit_overheated"] is True
    assert "leader_summary" in sent_payload[0]
    assert scheduler.get_status()["last_job_results"][0]["job_type"] == "sell_notification"


@pytest.mark.asyncio
async def test_sell_notification_job_marks_delivery_failure_when_notifier_returns_false(
    monkeypatch: pytest.MonkeyPatch,
):
    scheduler = NotificationScheduler()

    class DummyAnalysisHistoryRepository:
        def __init__(self, session):
            self.session = session

        async def get_active_symbols_with_names(self, analysis_type: str):
            return [{"symbol": "005930", "name": "삼성전자", "market": "KOSPI"}]

    class DummyStrategyService:
        async def refresh_analysis_history(self, analysis_type: str):
            return SimpleNamespace(
                items=[
                    SimpleNamespace(
                        symbol="005930",
                        name="삼성전자",
                        current_price=Decimal("70000"),
                        sell_phase="PHASE_4",
                        sell_stage="REDUCE_2",
                        sell_stage_name="2차 비중 축소",
                        sell_reasons=["약세"],
                        volume_ratio=1.0,
                        is_volume_sell_signal=False,
                        is_volume_spike=False,
                        is_personal_buying_overheated=False,
                        market_credit_label=None,
                        is_market_credit_overheated=False,
                    )
                ],
                errors=[],
            )

    notifier = SimpleNamespace(
        send_sell_signals_summary=AsyncMock(return_value=False),
        send_no_sell_signals_alert=AsyncMock(return_value=False),
    )

    @asynccontextmanager
    async def _dummy_session():
        yield object()

    monkeypatch.setattr(
        scheduler_module, "AnalysisHistoryRepository", DummyAnalysisHistoryRepository
    )
    monkeypatch.setattr(scheduler_module, "StrategyService", DummyStrategyService)
    monkeypatch.setattr(scheduler_module, "get_telegram_notifier", lambda: notifier)
    monkeypatch.setattr(scheduler_module, "get_async_session", lambda: _dummy_session())

    result = await scheduler.execute_sell_notification_now(slot_label="manual")

    assert result["executed"] is True
    assert result["success"] is False
    assert result["sent"] is False
    assert scheduler.get_status()["last_job_results"][0]["success"] is False


@pytest.mark.asyncio
async def test_buy_notification_job_marks_delivery_failure_when_notifier_returns_false(
    monkeypatch: pytest.MonkeyPatch,
):
    scheduler = NotificationScheduler()

    class DummyStrategyService:
        async def get_golden_cross_recommendations(self, **kwargs):
            _ = kwargs
            return SimpleNamespace(
                buy_candidate_count=1,
                top_stocks=[{"symbol": "005930"}],
                top_industries=[],
                errors=[],
                model_dump=lambda mode="json": {
                    "buy_candidate_count": 1,
                    "top_stocks": [{"symbol": "005930"}],
                    "top_industries": [],
                    "errors": [],
                },
            )

    notifier = SimpleNamespace(
        send_golden_cross_recommendations_summary=AsyncMock(return_value=False),
    )

    monkeypatch.setattr(scheduler_module, "StrategyService", DummyStrategyService)
    monkeypatch.setattr(scheduler_module, "get_telegram_notifier", lambda: notifier)

    result = await scheduler.execute_buy_notification_now(slot_label="manual")

    assert result["success"] is False
    assert result["sent"] is False
    assert scheduler.get_status()["last_job_results"][0]["success"] is False


@pytest.mark.asyncio
async def test_scheduled_buy_notification_skips_when_update_failed(
    monkeypatch: pytest.MonkeyPatch,
):
    scheduler = NotificationScheduler()
    scheduler._record_job_result(
        "buy_data_update",
        "11:30",
        result={"success": False, "slot": "11:30", "error": "warmup failed"},
        error="warmup failed",
    )

    class DummyStrategyService:
        async def get_golden_cross_recommendations(self, **kwargs):
            _ = kwargs
            raise AssertionError("notification should not scan after failed update")

    notifier = SimpleNamespace(
        send_golden_cross_recommendations_summary=AsyncMock(return_value=True),
    )

    monkeypatch.setattr(scheduler_module, "StrategyService", DummyStrategyService)
    monkeypatch.setattr(scheduler_module, "get_telegram_notifier", lambda: notifier)

    result = await scheduler.execute_buy_notification_now(slot_label="11:30")

    assert result["success"] is False
    assert result["executed"] is False
    assert result["skipped"] is True
    assert result["freshness"]["status"] == "failed"
    notifier.send_golden_cross_recommendations_summary.assert_not_awaited()


@pytest.mark.asyncio
async def test_buy_data_update_records_warmup_partial_failure_as_failed(
    monkeypatch: pytest.MonkeyPatch,
):
    scheduler = NotificationScheduler()

    class DummyWarmupService:
        def __init__(self, session):
            self.session = session

        async def update_stale_symbols(self, freshness_days: int, concurrency: int):
            _ = freshness_days, concurrency
            return SimpleNamespace(
                success_count=9,
                failed_count=1,
                errors=["005930 warmup failed"],
                api_calls_made=10,
                duration_seconds=1.5,
            )

    @asynccontextmanager
    async def _dummy_session():
        yield object()

    monkeypatch.setattr(scheduler_module, "OHLCVWarmupService", DummyWarmupService)
    monkeypatch.setattr(scheduler_module, "get_async_session", lambda: _dummy_session())
    monkeypatch.setattr(scheduler, "_refresh_external_risk_caches", AsyncMock(return_value={}))

    result = await scheduler._buy_data_update_job(slot_label="11:30")

    assert result["success"] is False
    assert result["failed_count"] == 1
    last_result = scheduler.get_status()["last_job_results"][0]
    assert last_result["success"] is False
    assert last_result["error"] == "005930 warmup failed"


@pytest.mark.asyncio
async def test_scheduled_buy_notification_skips_duplicate_payload(
    monkeypatch: pytest.MonkeyPatch,
):
    scheduler = NotificationScheduler()
    scheduler._record_job_result(
        "buy_data_update",
        "11:30",
        result={"success": True, "slot": "11:30"},
    )

    class DummyStrategyService:
        async def get_golden_cross_recommendations(self, **kwargs):
            _ = kwargs
            return SimpleNamespace(
                buy_candidate_count=1,
                top_stocks=[{"symbol": "005930"}],
                top_industries=[],
                errors=[],
                model_dump=lambda mode="json": {
                    "buy_candidate_count": 1,
                    "top_stocks": [{"symbol": "005930"}],
                    "top_industries": [],
                    "errors": [],
                },
            )

    notifier = SimpleNamespace(
        send_golden_cross_recommendations_summary=AsyncMock(return_value=True),
    )

    monkeypatch.setattr(scheduler_module, "StrategyService", DummyStrategyService)
    monkeypatch.setattr(scheduler_module, "get_telegram_notifier", lambda: notifier)

    first = await scheduler.execute_buy_notification_now(slot_label="11:30")
    second = await scheduler.execute_buy_notification_now(slot_label="11:30")

    assert first["sent"] is True
    assert second["success"] is True
    assert second["sent"] is False
    assert second["duplicate_skipped"] is True
    notifier.send_golden_cross_recommendations_summary.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduled_sell_notification_dedupes_no_tracked_symbols(
    monkeypatch: pytest.MonkeyPatch,
):
    scheduler = NotificationScheduler()
    scheduler._record_job_result(
        "sell_data_update",
        "09:30",
        result={"success": True, "slot": "09:30", "tracked_count": 0},
    )

    class DummyAnalysisHistoryRepository:
        def __init__(self, session):
            self.session = session

        async def get_active_symbols_with_names(self, analysis_type: str):
            _ = analysis_type
            return []

    notifier = SimpleNamespace(
        send_no_sell_signals_alert=AsyncMock(return_value=True),
    )

    @asynccontextmanager
    async def _dummy_session():
        yield object()

    monkeypatch.setattr(
        scheduler_module, "AnalysisHistoryRepository", DummyAnalysisHistoryRepository
    )
    monkeypatch.setattr(scheduler_module, "get_telegram_notifier", lambda: notifier)
    monkeypatch.setattr(scheduler_module, "get_async_session", lambda: _dummy_session())

    first = await scheduler.execute_sell_notification_now(slot_label="09:30")
    second = await scheduler.execute_sell_notification_now(slot_label="09:30")

    assert first["sent"] is True
    assert second["success"] is True
    assert second["sent"] is False
    assert second["duplicate_skipped"] is True
    notifier.send_no_sell_signals_alert.assert_awaited_once()


def test_notification_signature_uses_full_list_not_status_truncated_list():
    scheduler = NotificationScheduler()
    first_payload = {"alerts": [{"symbol": f"{idx:06d}"} for idx in range(10)]}
    second_payload = {"alerts": [{"symbol": f"{idx:06d}"} for idx in range(11)]}

    assert scheduler._build_notification_signature(
        first_payload
    ) != scheduler._build_notification_signature(second_payload)


@pytest.mark.asyncio
async def test_sell_notification_job_with_no_tracked_symbols_sends_no_signal_alert(
    monkeypatch: pytest.MonkeyPatch,
):
    scheduler = NotificationScheduler()

    class DummyAnalysisHistoryRepository:
        def __init__(self, session):
            self.session = session

        async def get_active_symbols_with_names(self, analysis_type: str):
            return []

    notifier = SimpleNamespace(
        send_sell_signals_summary=AsyncMock(return_value=False),
        send_no_sell_signals_alert=AsyncMock(return_value=True),
    )

    @asynccontextmanager
    async def _dummy_session():
        yield object()

    monkeypatch.setattr(
        scheduler_module, "AnalysisHistoryRepository", DummyAnalysisHistoryRepository
    )
    monkeypatch.setattr(scheduler_module, "get_telegram_notifier", lambda: notifier)
    monkeypatch.setattr(scheduler_module, "get_async_session", lambda: _dummy_session())

    result = await scheduler.execute_sell_notification_now(slot_label="manual")

    assert result["executed"] is True
    assert result["success"] is True
    assert result["tracked_count"] == 0
    notifier.send_no_sell_signals_alert.assert_awaited_once()


@pytest.mark.asyncio
async def test_sell_data_update_job_records_empty_tracked_result(monkeypatch: pytest.MonkeyPatch):
    scheduler = NotificationScheduler()

    class DummyAnalysisHistoryRepository:
        def __init__(self, session):
            self.session = session

        async def get_active_symbols_with_names(self, analysis_type: str):
            return []

    @asynccontextmanager
    async def _dummy_session():
        yield object()

    monkeypatch.setattr(
        scheduler_module, "AnalysisHistoryRepository", DummyAnalysisHistoryRepository
    )
    monkeypatch.setattr(scheduler_module, "get_async_session", lambda: _dummy_session())

    result = await scheduler._sell_data_update_job(slot_label="manual")

    assert result == {"success": True, "slot": "manual", "updated_count": 0, "tracked_count": 0}
    assert scheduler.get_status()["last_job_results"][0]["job_type"] == "sell_data_update"
