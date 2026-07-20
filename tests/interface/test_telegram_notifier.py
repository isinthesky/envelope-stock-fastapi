import pytest

from src.adapters.external.telegram.notifier import TelegramNotifier


@pytest.mark.asyncio
async def test_sell_signals_summary_uses_stage_only_message(monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def fake_send_message(self, message: str) -> bool:
        captured["message"] = message
        return True

    monkeypatch.setattr(TelegramNotifier, "send_message", fake_send_message)

    notifier = TelegramNotifier(bot_token="x", chat_id="y", enabled=True)
    stocks = [
        {
            "symbol": "270810",
            "name": "RISE 코스닥150",
            "current_price": 19210,
            "sell_phase": "NONE",
            "sell_phase_name": "보유 유지",
            "sell_phase_action": "현 상태 유지",
            "sell_stage_name": "2차 비중 축소",
            "final_stage": "REDUCE_2",
            "is_personal_buying_overheated": True,
            "is_market_credit_overheated": False,
            "market_credit_label": "전체",
            "volume_ratio": 1.13,
            "is_volume_spike": False,
            "is_volume_sell_signal": False,
            "is_volume_peak": False,
            "leader_summary": "대장주 확인: 1/2 약세 (강매도 1) | 알테오젠:REDUCE_2, 에코프로비엠:HOLD",
            "sell_reasons": [
                "개인 순매수 집중 (4/5일, 5일 합계 29,366주)",
                "개인 매수 비중 확대 (11.0% of 최근 거래량)",
                "시장 신용잔고가 최근 5일 고점권",
                "Stochastic 과매수 (K=95.0 > 70.0)",
            ],
        }
    ]

    sent = await notifier.send_sell_signals_summary(stocks, slot_label="12:30")

    assert sent is True
    message = captured["message"]
    assert "RISE 코스닥150" in message
    assert "단계: 2차 비중 축소" in message
    assert "— 19,210원" in message
    assert "👉 보유분 30~40% 매도 권장" in message
    assert "거래량: 1.13x (20일 평균 대비) · ETF라 보조지표로 참고" in message
    assert "개인수급 과열" in message
    assert "보조확인: 대장주 확인: 1/2 약세 (강매도 1) | 알테오젠:REDUCE_2, 에코프로비엠:HOLD" in message
    assert "Stage:" not in message
    assert "보유 유지 - 현 상태 유지" not in message
    assert "Stochastic 과매수" not in message
