# -*- coding: utf-8 -*-
"""Telegram 알림 메시지 빌더 단위 테스트

매수/매도 알림 메시지가 '알림만 보고 행동 판단이 가능한' 수준의
핵심 정보(종목/가격/신호 근거/권장 액션)를 포함하는지 검증한다.
"""

from src.adapters.external.telegram.notifier import (
    build_golden_cross_recommendations_message,
    build_no_sell_signals_message,
    build_sell_signals_summary_message,
)


class TestBuildSellSignalsSummaryMessage:
    def _full_stock(self) -> dict:
        return {
            "symbol": "005930",
            "name": "삼성전자",
            "current_price": 70000.0,
            "entry_price": 60800.0,
            "profit_ratio": 15.13,
            "stoch_k": 88.2,
            "rsi": 76.4,
            "ma_gap_ratio": 8.1,
            "sell_phase": "PHASE_5",
            "final_stage": "EXIT_ALL",
            "sell_stage_name": "전량 청산",
            "sell_reasons": ["데드크로스 임박", "Stochastic 과매수"],
            "volume_ratio": 1.7,
            "is_volume_sell_signal": True,
            "is_volume_spike": True,
            "is_volume_peak": False,
            "is_personal_buying_overheated": True,
            "market_credit_label": "KOSPI",
            "is_market_credit_overheated": True,
        }

    def test_contains_core_decision_fields(self):
        message = build_sell_signals_summary_message(
            [self._full_stock()], slot_label="09:30"
        )

        assert "매도 신호 알림 (09:30)" in message
        assert "삼성전자" in message and "005930" in message
        assert "70,000원" in message
        assert "단계: 전량 청산" in message
        assert "수익률: +15.1%" in message
        assert "진입 60,800원" in message
        assert "Stoch K 88.2" in message
        assert "RSI 76.4" in message
        assert "MA55/165갭 +8.1%" in message
        assert "거래량: 1.70x" in message
        assert "하락 동반 매도 신호" in message
        assert "개인수급 과열" in message
        assert "시장신용 과열(KOSPI)" in message
        # 권장 액션 한 줄
        assert "👉 즉시 전량 매도 검토" in message
        # 강한 매도 신호 이모지
        assert "🔴" in message

    def test_reduce_stage_shows_partial_sell_action(self):
        stock = self._full_stock()
        stock.update(
            {"sell_phase": "PHASE_3", "final_stage": "REDUCE_1", "sell_stage_name": "1차 비중 축소"}
        )
        message = build_sell_signals_summary_message([stock])

        assert "단계: 1차 비중 축소" in message
        assert "👉 보유분 20~30% 매도 검토" in message
        assert "🟠" in message

    def test_minimal_fields_do_not_crash(self):
        message = build_sell_signals_summary_message(
            [{"symbol": "000660", "name": "SK하이닉스", "final_stage": "REDUCE_2"}]
        )

        assert "SK하이닉스" in message
        assert "수익률" not in message
        assert "지표:" not in message
        assert "👉 보유분 30~40% 매도 권장" in message

    def test_stochastic_reasons_filtered_but_others_kept(self):
        stock = self._full_stock()
        message = build_sell_signals_summary_message([stock])

        assert "데드크로스 임박" in message
        assert "Stochastic 과매수" not in message

    def test_html_escapes_name(self):
        stock = self._full_stock()
        stock["name"] = "위험<태그>종목"
        message = build_sell_signals_summary_message([stock])

        assert "위험&lt;태그&gt;종목" in message
        assert "위험<태그>종목" not in message

    def test_status_summary_appended(self):
        message = build_sell_signals_summary_message(
            [self._full_stock()],
            status_summary=["삼성전자: 전량 청산", "SK하이닉스: 보유 유지"],
        )
        assert "추적 종목 현황" in message
        assert "SK하이닉스: 보유 유지" in message


class TestBuildGoldenCrossRecommendationsMessage:
    def _recommendations(self) -> dict:
        return {
            "top_stocks": [
                {
                    "symbol": "005930",
                    "name": "삼성전자",
                    "current_price": "70000",
                    "gc_state": "OPTIMAL_BUY",
                    "stoch_k": 22.1,
                    "ma_gap_ratio": 3.2,
                    "recommendation_score": 82.5,
                    "recommendation_reasons": ["골든크로스 유지", "눌림목 도달"],
                    "industry_name": "반도체",
                },
                {
                    "symbol": "042660",
                    "name": "한화오션",
                    "current_price": "55000",
                    "gc_state": "READY_TO_BUY",
                    "stoch_k": 28.4,
                    "ma_gap_ratio": 1.1,
                    "recommendation_score": 61.0,
                    "recommendation_reasons": [],
                    "industry_name": None,
                },
            ],
            "top_industries": [
                {"industry_code": "278", "industry_name": "반도체", "count": 2}
            ],
            "buy_candidate_count": 4,
            "scan_time": "2026-07-20T11:25:00",
            "errors": [],
        }

    def test_contains_ranked_candidates_with_score_and_action(self):
        message = build_golden_cross_recommendations_message(
            self._recommendations(), slot_label="11:30"
        )

        assert "매수 신호 알림 (11:30)" in message
        assert "🟢" in message
        assert "매수 적기 후보: 4개" in message
        assert "1. <b>삼성전자</b> (005930) — 70,000원" in message
        assert "2. <b>한화오션</b> (042660)" in message
        assert "점수: 82.5" in message
        assert "Stoch K 22.1" in message
        assert "MA55/165갭 +3.2%" in message
        assert "근거: 골든크로스 유지, 눌림목 도달" in message
        assert "👉 신규 매수 검토" in message
        assert "👉 매수 준비 — 눌림목 진입 대기" in message
        assert "반도체 (278) : 2종목" in message

    def test_fear_buy_candidate_is_labeled_and_not_mislabeled_as_gc(self):
        # FEAR_BUY 후보는 '공포 매수'로 라벨링되고, 골든크로스로 오라벨되지 않아야 한다.
        reco = self._recommendations()
        reco["top_stocks"].append(
            {
                "symbol": "999999",
                "name": "공포주",
                "current_price": "12000",
                "gc_state": "FEAR_BUY",
                "stoch_k": 15.0,
                "ma_gap_ratio": -6.0,
                "recommendation_score": 65.0,
                "recommendation_reasons": ["시장 공포 + 개별 과매도"],
                "industry_name": None,
            }
        )
        message = build_golden_cross_recommendations_message(reco, slot_label="11:30")

        assert "공포 매수" in message  # 번역된 라벨
        assert "FEAR_BUY" not in message  # 원시 상태 문자열이 노출되지 않음
        assert "+ Fear Buy:" in message  # 헤더에 fear-buy 전략 라벨 추가
        assert "시장 공포 구간 과매도" in message  # FEAR_BUY 액션

    def test_no_candidates_message_is_explicit(self):
        recommendations = self._recommendations()
        recommendations["top_stocks"] = []
        recommendations["top_industries"] = []
        recommendations["buy_candidate_count"] = 0

        message = build_golden_cross_recommendations_message(
            recommendations, slot_label="11:30"
        )

        assert "⚪" in message
        assert "오늘은 매수 후보 종목이 없습니다." in message
        assert "👉 오늘은 신규 매수 없이 관망" in message

    def test_no_candidates_with_errors_avoids_absolute_all_clear(self):
        recommendations = self._recommendations()
        recommendations["top_stocks"] = []
        recommendations["top_industries"] = []
        recommendations["buy_candidate_count"] = 0
        recommendations["errors"] = ["042670: Insufficient data for 042670"]

        message = build_golden_cross_recommendations_message(recommendations)

        assert "분석 성공 종목 기준 매수 후보 종목이 없습니다." in message
        assert "경고 종목은 수동 확인 필요" in message
        assert "오늘은 신규 매수 없이 관망" not in message

    def test_max_stocks_limit(self):
        recommendations = self._recommendations()
        recommendations["top_stocks"] = [
            {
                "symbol": f"{idx:06d}",
                "name": f"종목{idx}",
                "current_price": "10000",
                "gc_state": "OPTIMAL_BUY",
            }
            for idx in range(7)
        ]
        message = build_golden_cross_recommendations_message(
            recommendations, max_stocks=5
        )

        # 1~5위: 상세 블록, 6~7위: 한 줄 요약 (상세 마커 없이)
        assert "5. <b>종목4</b>" in message
        assert "6. 종목5 (000005) — 10,000원" in message
        assert "6. <b>" not in message
        assert "7. 종목6 (000006) — 10,000원" in message
        assert "... 외" not in message

    def test_ranks_6_to_10_one_line_and_11_plus_truncated(self):
        recommendations = self._recommendations()
        recommendations["top_stocks"] = [
            {
                "symbol": f"{idx:06d}",
                "name": f"종목{idx}",
                "current_price": "10000",
                "recommendation_score": 90.0 - idx,
                "gc_state": "OPTIMAL_BUY",
            }
            for idx in range(12)
        ]
        message = build_golden_cross_recommendations_message(
            recommendations, max_stocks=5
        )

        # 1~5위: 상세 블록
        assert "5. <b>종목4</b>" in message
        # 6~10위: `순위. 이름 (코드) — 가격 | 점수` 한 줄 요약
        assert "6. 종목5 (000005) — 10,000원 | 점수 85.0" in message
        assert "10. 종목9 (000009) — 10,000원 | 점수 81.0" in message
        assert "10. <b>" not in message
        # 11위 이상만 축약
        assert "11." not in message
        assert "... 외 2개" in message

    def test_errors_are_summarized(self):
        recommendations = self._recommendations()
        recommendations["errors"] = ["005380: No candle data available for 005380"]
        message = build_golden_cross_recommendations_message(recommendations)

        assert "데이터/분석 경고: 1건" in message
        assert "경고 요약" in message

    def test_scan_time_string_is_displayed_as_kst(self):
        recommendations = self._recommendations()
        recommendations["scan_time"] = "2026-07-21T05:30:00Z"

        message = build_golden_cross_recommendations_message(recommendations)

        assert "스캔 시각: 2026-07-21 14:30 KST" in message


class TestBuildNoSellSignalsMessage:
    def test_explicit_no_action_message(self):
        message = build_no_sell_signals_message(total_tracked=15, slot_label="09:30")

        assert "매도 신호 알림 (09:30)" in message
        assert "오늘은 매도 신호 종목이 없습니다. (추적 15개 종목)" in message
        assert "👉 전 종목 보유 유지 — 오늘 매도 조치 불필요" in message

    def test_failed_and_status_sections(self):
        message = build_no_sell_signals_message(
            total_tracked=10,
            failed_count=2,
            failed_summary=["005930: timeout", "000660: api error"],
            status_summary=["삼성전자: 보유 유지"],
        )

        assert "⚠️ 2개 종목 분석 실패" in message
        assert "005930: timeout" in message
        assert "추적 종목 현황" in message
        assert "삼성전자: 보유 유지" in message

    def test_failed_count_changes_hold_all_guidance(self):
        # 분석 실패 종목이 있으면 '전 종목 보유 유지'로 단정하지 않아야 한다
        message = build_no_sell_signals_message(total_tracked=10, failed_count=2)

        assert "👉 분석 성공 종목 기준 매도 신호 없음 — 실패 2종목은 수동 확인 필요" in message
        assert "전 종목 보유 유지" not in message
        assert "⚠️ 2개 종목 분석 실패" in message

    def test_zero_failed_count_keeps_hold_all_guidance(self):
        message = build_no_sell_signals_message(total_tracked=10, failed_count=0)

        assert "👉 전 종목 보유 유지 — 오늘 매도 조치 불필요" in message
        assert "수동 확인 필요" not in message
