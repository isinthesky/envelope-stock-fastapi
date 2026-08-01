# -*- coding: utf-8 -*-
"""
Telegram Notifier - Telegram Bot API 클라이언트

Telegram Bot API를 사용하여 메시지를 전송합니다.
https://core.telegram.org/bots/api
"""

import html as html_mod
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

# 한국 시간대
KST = ZoneInfo("Asia/Seoul")

from src.settings.config import settings


logger = logging.getLogger(__name__)


# ==================== 메시지 빌더 (순수 함수, 단위 테스트 대상) ====================

GC_STATE_LABELS: dict[str, str] = {
    "OPTIMAL_BUY": "매수 적기",
    "BUY_INTEREST": "매수 관심",
    "READY_TO_BUY": "매수 준비",
    "FEAR_BUY": "공포 매수",
}

GC_STATE_ACTIONS: dict[str, str] = {
    "OPTIMAL_BUY": "신규 매수 검토 (골든크로스 + 눌림목 도달)",
    "READY_TO_BUY": "매수 준비 — 눌림목 진입 대기",
    "BUY_INTEREST": "관심 종목 등록 후 관찰",
    "FEAR_BUY": "시장 공포 구간 과매도(비-GC) — 분할 매수 검토",
}

# final_stage → (표시 이름, 권장 행동) 매핑 (알림 기준을 Stage로 단일화)
SELL_STAGE_DISPLAY: dict[str, tuple[str, str]] = {
    "HOLD": ("보유 유지", "현 상태 유지"),
    "REDUCE_1": ("1차 비중 축소", "보유분 20~30% 매도 검토"),
    "REDUCE_2": ("2차 비중 축소", "보유분 30~40% 매도 권장"),
    "EXIT_ALL": ("전량 청산", "즉시 전량 매도 검토"),
}

_ETF_KEYWORDS = (
    "ETF", "ETN", "TIGER", "KODEX", "RISE", "SOL", "KOSEF", "ACE", "HANARO", "TIMEFOLIO",
)


def _to_float(value: object) -> float | None:
    """Decimal/str/int 등을 float로 안전 변환 (실패 시 None)"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_kst_minute(value: object) -> str:
    """datetime/ISO 문자열을 알림 표시용 KST 분 단위 문자열로 변환."""
    try:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str) and value:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            return ""

        if dt.tzinfo is not None:
            dt = dt.astimezone(KST)
        return dt.strftime("%Y-%m-%d %H:%M KST")
    except Exception:
        return ""


def build_golden_cross_recommendations_message(
    recommendations: dict,
    slot_label: str | None = None,
    max_stocks: int = 5,
) -> str:
    """골든크로스 매수 추천 요약 메시지 생성 (HTML)

    Args:
        recommendations: GoldenCrossRecommendationDTO를 dict로 dump한 값
        slot_label: 알림 슬롯 라벨 (예: "11:30")
        max_stocks: 표시할 최대 종목 수
    """
    top_stocks = recommendations.get("top_stocks") or []
    top_industries = recommendations.get("top_industries") or []
    buy_candidate_count = recommendations.get("buy_candidate_count")
    scan_time = recommendations.get("scan_time")
    errors = recommendations.get("errors") or []

    scan_time_str = _format_kst_minute(scan_time)

    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    slot_part = f" ({slot_label})" if slot_label else ""
    header_emoji = "🟢" if top_stocks else "⚪"

    ma_label = f"MA{settings.gc_short_ma_period}/{settings.gc_long_ma_period}"
    lines: list[str] = [
        f"{header_emoji} <b>매수 신호 알림{slot_part}</b>",
        f"📅 {now} KST",
        f"전략: {ma_label} 골든크로스 + Stochastic 눌림목",
    ]
    # fear-buy 후보가 섞여 있으면 별도 전략 라벨을 추가(골든크로스로 오라벨 방지)
    if any(str(s.get("gc_state") or "") == "FEAR_BUY" for s in top_stocks):
        lines.append("+ Fear Buy: 시장 공포 윈도우 내 개별 과매도(비-GC)")
    if buy_candidate_count is not None:
        lines.append(f"매수 적기 후보: {buy_candidate_count}개")
    if scan_time_str:
        lines.append(f"스캔 시각: {scan_time_str}")
    if errors:
        lines.append(f"⚠️ 데이터/분석 경고: {len(errors)}건")
    lines.append("")

    if not top_stocks:
        if errors:
            lines.append("분석 성공 종목 기준 매수 후보 종목이 없습니다.")
            lines.append("(일부 종목은 데이터/분석 경고로 제외됨)")
            lines.append("")
            lines.append("👉 신규 매수 없이 관망 — 경고 종목은 수동 확인 필요")
        else:
            lines.append("오늘은 매수 후보 종목이 없습니다.")
            lines.append("(조건: 골든크로스 활성 + Stochastic 과매도 눌림목)")
            lines.append("")
            lines.append("👉 오늘은 신규 매수 없이 관망")
    else:
        shown = top_stocks[:max_stocks]
        lines.append(f"📌 <b>매수 후보 Top {len(shown)}</b> (점수순)")
        for rank, s in enumerate(shown, start=1):
            symbol = html_mod.escape(str(s.get("symbol") or ""))
            name = html_mod.escape(str(s.get("name") or symbol))
            gc_state = str(s.get("gc_state") or "")
            state_label = GC_STATE_LABELS.get(gc_state, gc_state or "-")

            price = _to_float(s.get("current_price"))
            price_part = f" — {price:,.0f}원" if price is not None else ""

            detail_bits: list[str] = [f"상태: {state_label}"]
            score = _to_float(s.get("recommendation_score"))
            if score is not None:
                detail_bits.append(f"점수: {score:.1f}")

            indicator_bits: list[str] = []
            stoch_k = _to_float(s.get("stoch_k"))
            if stoch_k is not None:
                indicator_bits.append(f"Stoch K {stoch_k:.1f}")
            ma_gap = _to_float(s.get("ma_gap_ratio"))
            if ma_gap is not None:
                indicator_bits.append(f"{ma_label}갭 {ma_gap:+.1f}%")
            industry_name = s.get("industry_name")
            if industry_name:
                indicator_bits.append(html_mod.escape(str(industry_name)))

            lines.append(f"{rank}. <b>{name}</b> ({symbol}){price_part}")
            lines.append("   ├ " + " | ".join(detail_bits))
            if indicator_bits:
                lines.append("   ├ 지표: " + " / ".join(indicator_bits))
            reasons = [str(r) for r in (s.get("recommendation_reasons") or []) if r]
            if reasons:
                lines.append("   ├ 근거: " + html_mod.escape(", ".join(reasons[:2])))
            action = GC_STATE_ACTIONS.get(gc_state, "차트 확인 후 판단")
            lines.append(f"   └ 👉 {action}")

        # 상세 표시(max_stocks) 다음 5개는 한 줄 요약으로 표시, 그 이상만 축약
        brief_limit = max_stocks + 5
        for rank, s in enumerate(
            top_stocks[max_stocks:brief_limit], start=max_stocks + 1
        ):
            symbol = html_mod.escape(str(s.get("symbol") or ""))
            name = html_mod.escape(str(s.get("name") or symbol))
            price = _to_float(s.get("current_price"))
            price_part = f" — {price:,.0f}원" if price is not None else ""
            score = _to_float(s.get("recommendation_score"))
            score_part = f" | 점수 {score:.1f}" if score is not None else ""
            lines.append(f"{rank}. {name} ({symbol}){price_part}{score_part}")

        if len(top_stocks) > brief_limit:
            lines.append(f"... 외 {len(top_stocks) - brief_limit}개")

    if top_industries:
        lines.append("")
        lines.append("🏷️ <b>Top 업종</b>")
        for ind in top_industries:
            code = html_mod.escape(str(ind.get("industry_code") or ""))
            ind_name = html_mod.escape(str(ind.get("industry_name") or "(unknown)"))
            cnt = ind.get("count")
            if code and cnt is not None:
                lines.append(f"• {ind_name} ({code}) : {cnt}종목")
            else:
                lines.append(f"• {ind_name}")

    if errors:
        lines.append("")
        lines.append("⚠️ <b>경고 요약</b>")
        for error in errors[:3]:
            lines.append(f"• {html_mod.escape(str(error))}")
        if len(errors) > 3:
            lines.append(f"• ... 외 {len(errors) - 3}건")

    return "\n".join(lines)


def build_sell_signals_summary_message(
    stocks: list[dict],
    slot_label: str | None = None,
    status_summary: list[str] | None = None,
) -> str:
    """매도 신호 요약 메시지 생성 (HTML)

    Args:
        stocks: 매도 신호 종목 리스트 (notification_scheduler의 pending_sell_alerts)
        slot_label: 알림 슬롯 라벨 (예: "09:30")
        status_summary: 추적 종목 현황 요약
    """
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    slot_part = f" ({slot_label})" if slot_label else ""
    lines: list[str] = [
        f"🔴 <b>매도 신호 알림{slot_part}</b>",
        f"📅 {now} KST",
        f"매도 신호 {len(stocks)}개 종목",
        "",
    ]

    for stock in stocks[:10]:  # 최대 10개
        is_strong = (
            stock.get("sell_phase") == "PHASE_5" or stock.get("final_stage") == "EXIT_ALL"
        )
        emoji = "🔴" if is_strong else "🟠"
        raw_name = str(stock.get("name") or stock.get("symbol") or "")
        name = html_mod.escape(raw_name)
        symbol = html_mod.escape(str(stock.get("symbol", "")))

        price = _to_float(stock.get("current_price"))
        price_part = f" — {price:,.0f}원" if price is not None else ""

        # final_stage 기반으로 핵심 권고를 단일 표시 (phase와 혼용 금지)
        final_stage_val = str(stock.get("final_stage") or "")
        stage_name_raw, stage_action_raw = SELL_STAGE_DISPLAY.get(
            final_stage_val,
            (stock.get("sell_stage_name") or final_stage_val or "-", ""),
        )
        stage_name = html_mod.escape(str(stage_name_raw))

        block_lines: list[str] = [f"{emoji} <b>{name}</b> ({symbol}){price_part}"]

        # 단계 + 보유 수익률
        stage_bits = [f"단계: {stage_name}"]
        profit_ratio = _to_float(stock.get("profit_ratio"))
        entry_price = _to_float(stock.get("entry_price"))
        if profit_ratio is not None:
            profit_part = f"수익률: {profit_ratio:+.1f}%"
            if entry_price is not None:
                profit_part += f" (진입 {entry_price:,.0f}원)"
            stage_bits.append(profit_part)
        block_lines.append("   ├ " + " | ".join(stage_bits))

        # 핵심 지표 값
        indicator_bits: list[str] = []
        stoch_k = _to_float(stock.get("stoch_k"))
        if stoch_k is not None:
            indicator_bits.append(f"Stoch K {stoch_k:.1f}")
        rsi = _to_float(stock.get("rsi"))
        if rsi is not None:
            indicator_bits.append(f"RSI {rsi:.1f}")
        ma_gap = _to_float(stock.get("ma_gap_ratio"))
        if ma_gap is not None:
            indicator_bits.append(f"MA55/165갭 {ma_gap:+.1f}%")
        if indicator_bits:
            block_lines.append("   ├ 지표: " + " / ".join(indicator_bits))

        # 거래량
        volume_ratio = stock.get("volume_ratio")
        if volume_ratio is not None:
            try:
                ratio = float(volume_ratio)
                volume_note = f"거래량: {ratio:.2f}x (20일 평균 대비)"
                if stock.get("is_volume_sell_signal"):
                    volume_note += ", 하락 동반 매도 신호"
                elif stock.get("is_volume_peak"):
                    volume_note += ", 피크 경고"
                elif stock.get("is_volume_spike"):
                    volume_note += ", 급증"

                upper_name = raw_name.upper().replace(" ", "")
                if any(keyword in upper_name for keyword in _ETF_KEYWORDS):
                    volume_note += " · ETF라 보조지표로 참고"
                block_lines.append("   ├ " + html_mod.escape(volume_note))
            except (TypeError, ValueError):
                pass

        # 과열 보조지표
        heat_tags: list[str] = []
        if stock.get("is_personal_buying_overheated"):
            heat_tags.append("개인수급 과열")
        if stock.get("is_market_credit_overheated"):
            market_credit_label = html_mod.escape(str(stock.get("market_credit_label") or ""))
            heat_tags.append(f"시장신용 과열({market_credit_label})")
        if heat_tags:
            block_lines.append("   ├ ⚠️ " + " | ".join(heat_tags))

        leader_summary = stock.get("leader_summary")
        if leader_summary:
            block_lines.append("   ├ 보조확인: " + html_mod.escape(str(leader_summary)))

        # 매도 사유 (Stochastic/RSI 과매수 문구는 지표 라인과 중복이라 제외)
        reasons = stock.get("sell_reasons", []) or []
        filtered_reasons = [
            r
            for r in reasons
            if "Stochastic" not in r
            and "stochastic" not in r
            and "RSI 과매수" not in r
            and "RSI 극단적" not in r
        ]
        if filtered_reasons:
            block_lines.append("   ├ 사유: " + html_mod.escape(", ".join(filtered_reasons[:3])))

        # 권장 액션 한 줄
        action = stage_action_raw or "차트 확인 후 판단"
        block_lines.append(f"   └ 👉 {html_mod.escape(str(action))}")

        lines.append("\n".join(block_lines))

    if len(stocks) > 10:
        lines.append(f"\n... 외 {len(stocks) - 10}개")

    if status_summary:
        lines.append("")
        lines.append("ℹ️ 추적 종목 현황")
        for item in status_summary[:4]:
            lines.append(f"- {html_mod.escape(str(item))}")

    return "\n".join(lines)


def build_no_sell_signals_message(
    total_tracked: int = 0,
    slot_label: str | None = None,
    failed_count: int = 0,
    failed_summary: list[str] | None = None,
    status_summary: list[str] | None = None,
) -> str:
    """매도 신호 없음 메시지 생성 (HTML)"""
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    slot_part = f" ({slot_label})" if slot_label else ""

    lines: list[str] = [
        f"⚪ <b>매도 신호 알림{slot_part}</b>",
        f"📅 {now} KST",
        "",
        f"오늘은 매도 신호 종목이 없습니다. (추적 {total_tracked}개 종목)",
        "기준: PHASE_4/5(매도 권장/강력 매도) 또는 REDUCE_2/EXIT_ALL(강한 매도 단계)",
        "",
    ]
    if failed_count:
        # 분석 실패 종목이 있으면 '전 종목 보유 유지'로 단정하지 않는다
        lines.append(
            f"👉 분석 성공 종목 기준 매도 신호 없음 — 실패 {failed_count}종목은 수동 확인 필요"
        )
    else:
        lines.append("👉 전 종목 보유 유지 — 오늘 매도 조치 불필요")

    if failed_count:
        lines.append("")
        lines.append(f"⚠️ {failed_count}개 종목 분석 실패")
        if failed_summary:
            for item in failed_summary[:3]:
                lines.append(f"- {html_mod.escape(str(item))}")

    if status_summary:
        lines.append("")
        lines.append("ℹ️ 추적 종목 현황")
        for item in status_summary[:4]:
            lines.append(f"- {html_mod.escape(str(item))}")

    return "\n".join(lines)


class TelegramNotifier:
    """
    Telegram 알림 클라이언트

    Telegram Bot API의 sendMessage 메서드를 사용하여 메시지를 전송합니다.
    """

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
        enabled: bool | None = None,
    ) -> None:
        """
        Args:
            bot_token: Telegram Bot Token (없으면 환경변수 사용)
            chat_id: Telegram Chat ID (없으면 환경변수 사용)
            enabled: 알림 활성화 여부 (없으면 환경변수 사용)
        """
        self.bot_token = bot_token or settings.telegram_bot_token
        self.chat_id = chat_id or settings.telegram_chat_id
        self.enabled = enabled if enabled is not None else settings.telegram_enabled

        self._client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        """설정 완료 여부"""
        return bool(self.bot_token and self.chat_id and self.enabled)

    async def _get_client(self) -> httpx.AsyncClient:
        """httpx.AsyncClient 인스턴스 반환 (Lazy 초기화)"""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def aclose(self) -> None:
        """리소스 정리"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    _TELEGRAM_MAX_LENGTH = 4096

    async def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
    ) -> bool:
        """
        메시지 전송 (4096자 초과 시 자동 분할)

        Args:
            text: 전송할 메시지 (HTML 또는 Markdown 지원)
            parse_mode: 파싱 모드 ("HTML", "Markdown", "MarkdownV2")
            disable_notification: 무음 알림 여부

        Returns:
            bool: 전송 성공 여부
        """
        if not self.is_configured:
            logger.debug("[Telegram] Not configured, skipping message")
            return False

        chunks = self._split_message(text)
        all_ok = True
        for chunk in chunks:
            ok = await self._send_single_message(chunk, parse_mode, disable_notification)
            if not ok:
                all_ok = False
        return all_ok

    async def _send_single_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
    ) -> bool:
        """단일 메시지 전송 (4096자 이내)"""
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_notification": disable_notification,
        }

        try:
            client = await self._get_client()
            response = await client.post(url, json=payload)

            if response.status_code == 200:
                logger.info("[Telegram] Message sent successfully")
                return True
            else:
                logger.warning(
                    f"[Telegram] Failed to send message: {response.status_code} - {response.text}"
                )
                return False

        except Exception as e:
            logger.error(f"[Telegram] Error sending message: {e}")
            return False

    def _split_message(self, text: str) -> list[str]:
        """메시지를 Telegram 최대 길이(4096자) 기준으로 줄 단위 분할"""
        limit = self._TELEGRAM_MAX_LENGTH
        if len(text) <= limit:
            return [text]

        chunks: list[str] = []
        current: list[str] = []
        current_len = 0

        for line in text.split("\n"):
            # 단일 라인이 limit 초과 시 강제 분할
            if len(line) > limit:
                if current:
                    chunks.append("\n".join(current))
                    current = []
                    current_len = 0
                start = 0
                while start < len(line):
                    end = min(start + limit, len(line))
                    if end < len(line):
                        # HTML entity(&...;)/태그(<...>) 중간 절단 시 Telegram이
                        # 해당 청크를 parse error로 거부하므로 경계를 보정한다.
                        end = self._html_safe_split_point(line, start, end)
                    chunks.append(line[start:end])
                    start = end
                continue

            line_len = len(line) + 1  # +1 for newline
            if current_len + line_len > limit and current:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
            current.append(line)
            current_len += line_len

        if current:
            chunks.append("\n".join(current))
        return chunks

    @staticmethod
    def _html_safe_split_point(line: str, start: int, end: int) -> int:
        """강제 분할 절단 지점이 HTML entity/태그 내부에 걸리지 않도록 보정

        end 직전 최대 64자 범위를 뒤로 스캔하며:
        - 아직 ';'로 닫히지 않은 마지막 '&' (entity 중간) 앞에서 절단
        - 아직 '>'로 닫히지 않은 마지막 '<' (태그 중간) 앞에서 절단
        64자 내에 안전 지점이 없으면 end를 그대로 반환한다 (무한루프 방지).
        반환값은 항상 start보다 크므로 분할 루프는 반드시 전진한다.
        """
        lower_bound = max(start + 1, end - 64)
        entity_start: int | None = None  # 아직 ';'로 닫히지 않은 '&' 위치
        tag_start: int | None = None  # 아직 '>'로 닫히지 않은 '<' 위치
        seen_entity_close = False
        seen_tag_close = False
        for i in range(end - 1, lower_bound - 1, -1):
            ch = line[i]
            if ch == ";":
                seen_entity_close = True
            elif ch == ">":
                seen_tag_close = True
            elif ch == "&" and not seen_entity_close and entity_start is None:
                entity_start = i
            elif ch == "<" and not seen_tag_close and tag_start is None:
                tag_start = i
            if entity_start is not None and tag_start is not None:
                break
        # 태그 내부의 entity처럼 두 토큰이 겹칠 수 있으므로 첫 후보에서 멈추지
        # 않고 더 이른 시작점 앞에서 절단한다 (예: <a href="...&amp 는 '<' 앞).
        candidates = [pos for pos in (entity_start, tag_start) if pos is not None]
        if candidates:
            return min(candidates)
        return end

    # ==================== 매수 알림 포맷 ====================

    async def send_golden_cross_recommendations_summary(
        self,
        recommendations: dict,
        slot_label: str | None = None,
    ) -> bool:
        """골든크로스 추천 요약(Top 종목 + Top 업종) 알림 전송

        Args:
            recommendations: GoldenCrossRecommendationDTO를 dict로 dump한 값
              - top_stocks: list
              - top_industries: list
              - buy_candidate_count: int
              - scan_time: str|datetime
        """
        if not recommendations:
            return False

        message = build_golden_cross_recommendations_message(
            recommendations, slot_label=slot_label
        )
        return await self.send_message(message)

    # ==================== 매도 알림 포맷 ====================

    async def send_no_sell_signals_alert(
        self,
        total_tracked: int = 0,
        slot_label: str | None = None,
        failed_count: int = 0,
        failed_summary: list[str] | None = None,
        status_summary: list[str] | None = None,
    ) -> bool:
        """
        매도 권장 종목 없음 알림 전송

        Args:
            total_tracked: 추적 중인 총 종목 수
            failed_count: 분석 실패 종목 수
        """
        message = build_no_sell_signals_message(
            total_tracked=total_tracked,
            slot_label=slot_label,
            failed_count=failed_count,
            failed_summary=failed_summary,
            status_summary=status_summary,
        )
        return await self.send_message(message)

    async def send_sell_signals_summary(
        self,
        stocks: list[dict],
        slot_label: str | None = None,
        status_summary: list[str] | None = None,
    ) -> bool:
        """
        매도 권장 종목 요약 알림 전송

        Args:
            stocks: 매도 권장 종목 리스트
        """
        if not stocks:
            return False

        message = build_sell_signals_summary_message(
            stocks, slot_label=slot_label, status_summary=status_summary
        )
        return await self.send_message(message)


# ==================== 싱글톤 인스턴스 ====================

_telegram_notifier_instance: TelegramNotifier | None = None


def get_telegram_notifier() -> TelegramNotifier:
    """
    TelegramNotifier 싱글톤 인스턴스 반환

    Returns:
        TelegramNotifier: 알림 클라이언트 인스턴스
    """
    global _telegram_notifier_instance
    if _telegram_notifier_instance is None:
        _telegram_notifier_instance = TelegramNotifier()
    return _telegram_notifier_instance
