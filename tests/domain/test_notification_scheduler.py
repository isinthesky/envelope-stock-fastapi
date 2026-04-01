from unittest.mock import AsyncMock, patch

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


async def test_start_registers_four_notifications_and_four_updates():
    scheduler = NotificationScheduler()

    with patch(
        "apscheduler.schedulers.asyncio.AsyncIOScheduler",
        side_effect=lambda *args, **kwargs: _DummyScheduler(*args, **kwargs),
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


async def test_execute_buy_notification_now_uses_manual_slot_label():
    scheduler = NotificationScheduler()
    scheduler._buy_notification_job = AsyncMock(return_value={"success": True, "slot": "manual"})

    result = await scheduler.execute_buy_notification_now()

    scheduler._buy_notification_job.assert_awaited_once_with(slot_label="manual")
    assert result == {"success": True, "slot": "manual"}


async def test_execute_sell_notification_now_uses_manual_slot_label():
    scheduler = NotificationScheduler()
    scheduler._sell_notification_job = AsyncMock(return_value={"success": True, "slot": "manual"})

    result = await scheduler.execute_sell_notification_now()

    scheduler._sell_notification_job.assert_awaited_once_with(slot_label="manual")
    assert result == {"success": True, "slot": "manual"}
