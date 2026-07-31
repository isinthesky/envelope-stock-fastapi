from unittest.mock import patch

from src.application.domain.strategy import notification_scheduler as scheduler_module
from src.application.domain.strategy.notification_scheduler import NotificationScheduler


def test_notification_scheduler_status_includes_slots_and_runtime_state() -> None:
    scheduler = NotificationScheduler()

    # 매도 알림 available 여부는 sell_notification_enabled 플래그를 따른다(기본 OFF).
    with patch.object(scheduler_module.settings, "sell_notification_enabled", True):
        status = scheduler.get_status()

    assert status["is_running"] is False
    assert status["execution_lock_locked"] is False
    assert len(status["buy_slots"]) == 2
    assert len(status["sell_slots"]) == 2
    assert status["buy_slots"][0]["notify_time"] == "11:30"
    assert status["sell_slots"][0]["notify_time"] == "09:30"
    assert status["sell_notification_available"] is True
