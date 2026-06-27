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
                for i in range(0, len(line), limit):
                    chunks.append(line[i:i + limit])
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

    # ==================== 매수 알림 포맷 ====================

    async def send_buy_signal_alert(
        self,
        symbol: str,
        name: str,
        current_price: float,
        ma_short: float,
        ma_long: float,
        stoch_k: float,
        gc_state: str,
    ) -> bool:
        """
        매수 신호 알림 전송

        Args:
            symbol: 종목코드
            name: 종목명
            current_price: 현재가
            ma_short: 단기 MA
            ma_long: 장기 MA
            stoch_k: Stochastic K
            gc_state: 골든크로스 상태
        """
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        state_label = {
            "OPTIMAL_BUY": "매수 적기",
            "BUY_INTEREST": "매수 관심",
            "READY_TO_BUY": "매수 관심",
        }.get(gc_state, gc_state)

        safe_name = html_mod.escape(name or symbol)
        safe_symbol = html_mod.escape(symbol)

        message = f"""🟢 <b>{state_label} 종목 알림</b>

📅 {now}

<b>종목:</b> {safe_name} ({safe_symbol})
<b>현재가:</b> {current_price:,.0f}원
<b>MA55:</b> {ma_short:,.0f} | <b>MA165:</b> {ma_long:,.0f}
<b>Stochastic K:</b> {stoch_k:.1f}

<b>상태:</b> {state_label} ({gc_state})"""

        return await self.send_message(message)

    async def send_buy_signals_summary(
        self,
        stocks: list[dict],
    ) -> bool:
        """
        매수 신호 요약 알림 전송

        Args:
            stocks: 매수 준비 종목 리스트 [{symbol, name, current_price, stoch_k, ...}]
        """
        if not stocks:
            return False

        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        optimal_count = sum(1 for stock in stocks if stock.get("gc_state") == "OPTIMAL_BUY")
        interest_count = sum(1 for stock in stocks if stock.get("gc_state") == "BUY_INTEREST")
        ready_count = sum(1 for stock in stocks if stock.get("gc_state") == "READY_TO_BUY")

        lines = [
            "🟢 <b>매수 신호 종목 알림</b>",
            f"📅 {now}",
            f"총 {len(stocks)}개 종목 (매수 적기 {optimal_count}, 매수 관심 {interest_count + ready_count})",
            "",
        ]

        for stock in stocks[:10]:  # 최대 10개
            state_label = {
                "OPTIMAL_BUY": "매수 적기",
                "BUY_INTEREST": "매수 관심",
                "READY_TO_BUY": "매수 관심",
            }.get(stock.get("gc_state"), stock.get("gc_state", "-"))
            s_name = html_mod.escape(stock.get("name") or stock.get("symbol") or "")
            s_symbol = html_mod.escape(stock.get("symbol", ""))
            lines.append(
                f"• <b>{s_name}</b> ({s_symbol})\n"
                f"  상태: {state_label} | 현재가: {stock['current_price']:,.0f}원 | K: {stock['stoch_k']:.1f}"
            )

        if len(stocks) > 10:
            lines.append(f"\n... 외 {len(stocks) - 10}개")

        message = "\n".join(lines)
        return await self.send_message(message)


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

        top_stocks = recommendations.get("top_stocks") or []
        top_industries = recommendations.get("top_industries") or []
        buy_candidate_count = recommendations.get("buy_candidate_count")
        scan_time = recommendations.get("scan_time")
        errors = recommendations.get("errors") or []

        # scan_time 표기 정리
        scan_time_str = ""
        try:
            if hasattr(scan_time, "strftime"):
                scan_time_str = scan_time.strftime("%Y-%m-%d %H:%M")
            elif isinstance(scan_time, str) and scan_time:
                scan_time_str = scan_time.replace("T", " ")[:16]
        except Exception:
            scan_time_str = ""

        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

        slot_part = f" ({slot_label})" if slot_label else ""
        lines: list[str] = [
            f"🧭 <b>매수 추천 알림{slot_part}</b>",
            f"📅 {now}",
        ]

        if buy_candidate_count is not None:
            lines.append(f"매수 적기 후보: {buy_candidate_count}개")

        if scan_time_str:
            lines.append(f"스캔 시각: {scan_time_str}")

        if errors:
            lines.append(f"⚠️ 데이터/분석 경고: {len(errors)}건")

        lines.append("")

        if top_industries:
            lines.append("🏷️ <b>Top 업종</b>")
            for ind in top_industries:
                code = html_mod.escape(str(ind.get("industry_code") or ""))
                name = html_mod.escape(ind.get("industry_name") or "(unknown)")
                cnt = ind.get("count")
                if code and cnt is not None:
                    lines.append(f"• {name} ({code}) : {cnt}")
                else:
                    lines.append(f"• {name}")
            lines.append("")

        if top_stocks:
            lines.append("📌 <b>Top 종목</b>")
            for s in top_stocks[:10]:
                symbol = html_mod.escape(s.get("symbol") or "")
                name = html_mod.escape(s.get("name") or "")
                gc_state = s.get("gc_state")
                ind_name = html_mod.escape(s.get("industry_name") or "")
                ind_part = f" | 업종: {ind_name}" if ind_name else ""
                state_label = {
                    "OPTIMAL_BUY": "매수 적기",
                    "BUY_INTEREST": "매수 관심",
                    "READY_TO_BUY": "매수 준비",
                }.get(gc_state, gc_state or "-")
                price = s.get("current_price")
                price_part = f" | 현재가: {float(price):,.0f}원" if price is not None else ""
                lines.append(
                    f"• <b>{name}</b> ({symbol})\n"
                    f"  상태: {state_label}{price_part}{ind_part}"
                )

            if len(top_stocks) > 10:
                lines.append(f"\n... 외 {len(top_stocks) - 10}개")

        if errors:
            lines.append("")
            lines.append("⚠️ <b>경고 요약</b>")
            for error in errors[:3]:
                lines.append(f"• {html_mod.escape(str(error))}")
            if len(errors) > 3:
                lines.append(f"• ... 외 {len(errors) - 3}건")

        message = "\n".join(lines)
        return await self.send_message(message)

    async def send_no_buy_signals_alert(self, total_scanned: int = 0) -> bool:
        """
        매수 권장 종목 없음 알림 전송

        Args:
            total_scanned: 스캔한 총 종목 수
        """
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

        message = f"""⚪ <b>매수 신호 종목 알림</b>

📅 {now}

오늘은 매수 권장 종목이 없습니다.
(총 {total_scanned}개 종목 스캔)

골든크로스 활성 + Stochastic 과매도 조건을
충족하는 종목이 없습니다."""

        return await self.send_message(message)

    # ==================== 매도 알림 포맷 ====================

    async def send_sell_signal_alert(
        self,
        symbol: str,
        name: str | None,
        current_price: float,
        sell_phase: str,
        sell_phase_name: str,
        sell_phase_action: str,
        sell_reasons: list[str],
    ) -> bool:
        """
        매도 권장 알림 전송

        Args:
            symbol: 종목코드
            name: 종목명
            current_price: 현재가
            sell_phase: 매도 Phase (PHASE_1~5)
            sell_phase_name: Phase 이름
            sell_phase_action: Phase 권장 행동
            sell_reasons: 매도 근거 리스트
        """
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        display_name = html_mod.escape(name or symbol)
        safe_symbol = html_mod.escape(symbol)

        # Phase에 따른 이모지
        emoji_map = {
            "PHASE_5": "🔴",
            "PHASE_4": "🟠",
            "PHASE_3": "🟡",
            "PHASE_2": "🟡",
            "PHASE_1": "⚪",
        }
        emoji = emoji_map.get(sell_phase, "⚪")

        reasons_text = "\n".join(f"• {html_mod.escape(r)}" for r in sell_reasons[:5])

        message = f"""{emoji} <b>매도 권장 알림</b>

📅 {now}

<b>종목:</b> {display_name} ({safe_symbol})
<b>현재가:</b> {current_price:,.0f}원
<b>Phase:</b> {html_mod.escape(sell_phase_name)}
<b>권장:</b> {html_mod.escape(sell_phase_action)}

<b>매도 근거:</b>
{reasons_text}"""

        return await self.send_message(message)

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
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

        slot_part = f" ({slot_label})" if slot_label else ""
        fail_part = f"\n⚠️ {failed_count}개 종목 분석 실패" if failed_count else ""
        summary_part = ""
        if failed_summary:
            summary_lines = "\n".join([f"- {item}" for item in failed_summary[:3]])
            summary_part = f"\n원인 요약:\n{summary_lines}"
        status_part = ""
        if status_summary:
            status_lines = "\n".join([f"- {item}" for item in status_summary[:4]])
            status_part = f"\n\nℹ️ 시스템 상태\n{status_lines}"
        message = f"""⚪ <b>매도 권장 종목 알림{slot_part}</b>

📅 {now}

오늘은 매도 권장 종목이 없습니다.
(총 {total_tracked}개 종목 추적 중)

PHASE_4/5(매도 권장/강력 매도) 또는
REDUCE_2/EXIT_ALL(강한 매도 단계)에
해당하는 종목이 없습니다.{fail_part}{summary_part}{status_part}"""

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

        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

        slot_part = f" ({slot_label})" if slot_label else ""
        lines = [
            f"🔴 <b>매도 권장 종목 알림{slot_part}</b>",
            f"📅 {now} (KST)",
            f"총 {len(stocks)}개 종목",
            "",
        ]

        # final_stage → 표시 이름/행동 매핑 (알림 기준을 Stage로 단일화)
        stage_display = {
            "HOLD": ("보유 유지", "현 상태 유지"),
            "REDUCE_1": ("1차 비중 축소", "20~30% 매도 고려"),
            "REDUCE_2": ("2차 비중 축소", "30~40% 매도 권장"),
            "EXIT_ALL": ("전량 청산", "즉시 전량 매도"),
        }
        etf_keywords = ("ETF", "ETN", "TIGER", "KODEX", "RISE", "SOL", "KOSEF", "ACE", "HANARO", "TIMEFOLIO")

        for stock in stocks[:10]:  # 최대 10개
            is_strong = stock.get("sell_phase") == "PHASE_5" or stock.get("final_stage") == "EXIT_ALL"
            emoji = "🔴" if is_strong else "🟠"
            raw_name = stock.get("name") or stock.get("symbol") or ""
            name = html_mod.escape(raw_name)

            # Stochastic/RSI 과매수 관련 메시지 필터링
            reasons = stock.get("sell_reasons", [])
            filtered_reasons = [
                r for r in reasons
                if "Stochastic" not in r and "stochastic" not in r
                and "RSI 과매수" not in r and "RSI 극단적" not in r
            ]
            reasons_text = html_mod.escape(", ".join(filtered_reasons[:3])) if filtered_reasons else ""

            # final_stage 기반으로 핵심 권고를 단일 표시 (phase와 혼용 금지)
            final_stage_val = str(stock.get("final_stage") or "")
            stage_name_raw, stage_action_raw = stage_display.get(
                final_stage_val,
                (stock.get("sell_stage_name") or final_stage_val or "-", "")
            )
            stage_name = html_mod.escape(stage_name_raw)
            stage_action = html_mod.escape(stage_action_raw)
            heat_tags: list[str] = []
            if stock.get("is_personal_buying_overheated"):
                heat_tags.append("개인수급 과열")
            market_credit_label = html_mod.escape(stock.get("market_credit_label") or "")
            if stock.get("is_market_credit_overheated"):
                heat_tags.append(f"시장신용 과열({market_credit_label})")

            current_price = stock.get("current_price")
            price_part = f" | 현재가: {float(current_price):,.0f}원" if current_price is not None else ""
            symbol = html_mod.escape(stock.get("symbol", ""))
            action_part = f" - {stage_action}" if stage_action else ""
            heat_part = " | ".join(heat_tags)
            block = f"{emoji} <b>{name}</b> ({symbol})\n  {stage_name}{action_part}{price_part}"

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
                    if any(keyword in upper_name for keyword in etf_keywords):
                        volume_note += " · ETF라 보조지표로 참고"

                    block += f"\n  {html_mod.escape(volume_note)}"
                except (TypeError, ValueError):
                    pass

            if heat_part:
                block += f"\n  {heat_part.strip()}"
            leader_summary = stock.get("leader_summary")
            if leader_summary:
                block += f"\n  보조확인: {html_mod.escape(str(leader_summary))}"
            if reasons_text:
                block += f"\n  💡 {reasons_text}"
            lines.append(block)

        if len(stocks) > 10:
            lines.append(f"\n... 외 {len(stocks) - 10}개")

        if status_summary:
            lines.append("")
            lines.append("ℹ️ 시스템 상태")
            for item in status_summary[:4]:
                lines.append(f"- {item}")

        message = "\n".join(lines)
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
