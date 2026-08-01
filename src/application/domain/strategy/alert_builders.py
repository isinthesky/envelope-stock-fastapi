# -*- coding: utf-8 -*-
"""
Alert Builders - 알림 페이로드 조립 (순수 함수)

NotificationScheduler에서 분리한 ETF 대장주 판정 + 매수/매도 알림
페이로드 조립 로직. 분석 결과(analyzed data)를 받아 Telegram 발송/서명용
dict를 만들어 반환하는 순수 함수만 모은다. I/O나 스케줄러 상태에 의존하지 않는다.

동작은 기존 NotificationScheduler 내부 구현과 동일하게 보존한다.
단일 소스는 settings.etf_leader_map.
"""

from src.settings.config import settings


def build_etf_leader_summary(symbol: str, analyzed_results: dict[str, dict]) -> str | None:
    """ETF 본체 알림에 붙일 대장주 보조 판정 요약 생성"""
    leader_symbols = settings.etf_leader_map.get((symbol or "").strip())
    if not leader_symbols:
        return None

    analyzed_leaders = [analyzed_results.get(leader_symbol) for leader_symbol in leader_symbols]
    analyzed_leaders = [item for item in analyzed_leaders if item]
    if not analyzed_leaders:
        return None

    weak_count = 0
    strong_sell_count = 0
    parts: list[str] = []
    for item in analyzed_leaders:
        final_stage = str(item.get("final_stage") or "")
        name = item.get("name") or item.get("symbol") or "-"
        parts.append(f"{name}:{final_stage or '-'}")
        if final_stage in {"REDUCE_1", "REDUCE_2", "EXIT_ALL"}:
            weak_count += 1
        if final_stage in {"REDUCE_2", "EXIT_ALL"}:
            strong_sell_count += 1

    return (
        f"대장주 확인: {weak_count}/{len(analyzed_leaders)} 약세"
        f" (강매도 {strong_sell_count}) | " + ", ".join(parts)
    )


def filter_duplicate_leader_alerts(pending_sell_alerts: list[dict]) -> list[dict]:
    """ETF 본체가 알림 대상이면 해당 대장주 개별 알림은 숨긴다."""
    etf_alert_symbols = {
        (item.get("symbol") or "").strip()
        for item in pending_sell_alerts
        if (item.get("symbol") or "").strip() in settings.etf_leader_map
    }
    hidden_leader_symbols = {
        leader_symbol
        for etf_symbol in etf_alert_symbols
        for leader_symbol in settings.etf_leader_map.get(etf_symbol, ())
    }

    return [
        item
        for item in pending_sell_alerts
        if (item.get("symbol") or "").strip() not in hidden_leader_symbols
    ]


def build_buy_signature_payload(notification_payload: dict) -> dict[str, object]:
    """매수 알림 중복 억제용 서명 페이로드 부분집합 생성"""
    return {
        "top_stocks": notification_payload.get("top_stocks", []),
        "top_industries": notification_payload.get("top_industries", []),
        "buy_candidate_count": notification_payload.get("buy_candidate_count"),
        "errors": notification_payload.get("errors", []),
    }


def assemble_sell_alerts(analyzed_items: list) -> tuple[list[dict], list[str]]:
    """재분석 결과에서 매도 알림 페이로드와 상태 요약을 조립한다.

    - 강한 매도 단계(REDUCE_2/EXIT_ALL) 또는 상위 매도 Phase(PHASE_4/5) 종목만 알림 대상
    - ETF 본체 알림 시 대장주 개별 알림 숨김 + ETF 본체에 대장주 요약 부착
    반환: (pending_sell_alerts, status_summary)
    """
    pending_sell_alerts: list[dict] = []
    analyzed_results: dict[str, dict] = {}
    status_summary: list[str] = []

    for item in analyzed_items:
        stage_value = str(item.sell_stage or "HOLD")
        # ETF 대장주 맵/요약 조회 키와 일치하도록 strip 정규화 키 사용
        analyzed_results[(item.symbol or "").strip()] = {
            "symbol": item.symbol,
            "name": item.name,
            "final_stage": stage_value,
        }

        stage_name = item.sell_stage_name or stage_value
        if len(status_summary) < 4:
            status_summary.append(f"{item.name or item.symbol}: {stage_name}")

        qualifies = stage_value in {"REDUCE_2", "EXIT_ALL"} or item.sell_phase in {
            "PHASE_4",
            "PHASE_5",
        }
        if not qualifies:
            continue

        entry_price = getattr(item, "entry_price", None)
        profit_ratio = None
        try:
            if entry_price:
                profit_ratio = (
                    (float(item.current_price) - float(entry_price))
                    / float(entry_price)
                    * 100.0
                )
        except (TypeError, ValueError, ZeroDivisionError):
            profit_ratio = None

        pending_sell_alerts.append(
            {
                "symbol": item.symbol,
                "name": item.name,
                "current_price": float(item.current_price),
                "entry_price": float(entry_price) if entry_price else None,
                "profit_ratio": profit_ratio,
                "stoch_k": getattr(item, "stoch_k", None),
                "rsi": getattr(item, "rsi", None),
                "ma_gap_ratio": getattr(item, "ma_gap_ratio", None),
                "sell_ratio_min": getattr(item, "sell_ratio_min", None),
                "sell_ratio_max": getattr(item, "sell_ratio_max", None),
                "sell_phase": item.sell_phase,
                "sell_reasons": item.sell_reasons or [],
                "final_stage": stage_value,
                "sell_stage_name": item.sell_stage_name,
                "volume_ratio": item.volume_ratio,
                "is_volume_sell_signal": bool(item.is_volume_sell_signal),
                "is_volume_spike": bool(item.is_volume_spike),
                "is_volume_peak": False,
                "is_personal_buying_overheated": bool(
                    getattr(item, "is_personal_buying_overheated", False)
                ),
                "market_credit_label": getattr(item, "market_credit_label", None),
                "is_market_credit_overheated": bool(
                    getattr(item, "is_market_credit_overheated", False)
                ),
            }
        )

    pending_sell_alerts = filter_duplicate_leader_alerts(pending_sell_alerts)
    for alert in pending_sell_alerts:
        leader_summary = build_etf_leader_summary(alert["symbol"], analyzed_results)
        if leader_summary:
            alert["leader_summary"] = leader_summary

    return pending_sell_alerts, status_summary
