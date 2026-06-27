from src.application.domain.strategy.notification_scheduler import NotificationScheduler


def test_build_etf_leader_summary_counts_weak_and_strong_sell() -> None:
    analyzed_results = {
        "196170": {"name": "알테오젠", "final_stage": "REDUCE_2"},
        "247540": {"name": "에코프로비엠", "final_stage": "HOLD"},
    }

    summary = NotificationScheduler._build_etf_leader_summary("270810", analyzed_results)

    assert summary is not None
    assert "대장주 확인: 1/2 약세" in summary
    assert "강매도 1" in summary
    assert "알테오젠:REDUCE_2" in summary
    assert "에코프로비엠:HOLD" in summary


def test_build_etf_leader_summary_returns_none_for_non_etf_symbol() -> None:
    summary = NotificationScheduler._build_etf_leader_summary("005930", {})

    assert summary is None


def test_filter_duplicate_leader_alerts_hides_leaders_when_etf_alert_exists() -> None:
    pending_sell_alerts = [
        {"symbol": "270810", "final_stage": "REDUCE_2"},
        {"symbol": "196170", "final_stage": "REDUCE_2"},
        {"symbol": "247540", "final_stage": "REDUCE_2"},
        {"symbol": "329180", "final_stage": "REDUCE_2"},
    ]

    filtered = NotificationScheduler._filter_duplicate_leader_alerts(pending_sell_alerts)

    symbols = {item["symbol"] for item in filtered}
    assert "270810" in symbols
    assert "196170" not in symbols
    assert "247540" not in symbols
    assert "329180" in symbols


def test_filter_duplicate_leader_alerts_keeps_leaders_when_etf_alert_missing() -> None:
    pending_sell_alerts = [
        {"symbol": "196170", "final_stage": "REDUCE_2"},
        {"symbol": "247540", "final_stage": "REDUCE_2"},
    ]

    filtered = NotificationScheduler._filter_duplicate_leader_alerts(pending_sell_alerts)

    symbols = {item["symbol"] for item in filtered}
    assert symbols == {"196170", "247540"}
