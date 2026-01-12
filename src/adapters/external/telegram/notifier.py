# -*- coding: utf-8 -*-
"""
Telegram Notifier - Telegram Bot API 클라이언트

Telegram Bot API를 사용하여 메시지를 전송합니다.
https://core.telegram.org/bots/api
"""

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

    async def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
    ) -> bool:
        """
        메시지 전송

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
            "READY_TO_BUY": "매수 준비",
        }.get(gc_state, gc_state)

        message = f"""🟢 <b>{state_label} 종목 알림</b>

📅 {now}

<b>종목:</b> {name} ({symbol})
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
        ready_count = sum(1 for stock in stocks if stock.get("gc_state") == "READY_TO_BUY")

        lines = [
            "🟢 <b>매수 신호 종목 알림</b>",
            f"📅 {now}",
            f"총 {len(stocks)}개 종목 (매수 적기 {optimal_count}, 매수 준비 {ready_count})",
            "",
        ]

        for stock in stocks[:10]:  # 최대 10개
            state_label = {
                "OPTIMAL_BUY": "매수 적기",
                "READY_TO_BUY": "매수 준비",
            }.get(stock.get("gc_state"), stock.get("gc_state", "-"))
            lines.append(
                f"• <b>{stock['name']}</b> ({stock['symbol']})\n"
                f"  상태: {state_label} | 현재가: {stock['current_price']:,.0f}원 | K: {stock['stoch_k']:.1f}"
            )

        if len(stocks) > 10:
            lines.append(f"\n... 외 {len(stocks) - 10}개")

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
        sell_recommendation: str,
        sell_signal_strength: int,
        sell_reasons: list[str],
    ) -> bool:
        """
        매도 권장 알림 전송

        Args:
            symbol: 종목코드
            name: 종목명
            current_price: 현재가
            sell_recommendation: 매도 추천 등급
            sell_signal_strength: 매도 시그널 강도 (0-5)
            sell_reasons: 매도 근거 리스트
        """
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        display_name = name or symbol

        # 추천 등급에 따른 이모지
        emoji_map = {
            "STRONG_SELL": "🔴",
            "SELL": "🟠",
            "CONSIDER_SELL": "🟡",
            "WEAK_SELL": "⚪",
        }
        emoji = emoji_map.get(sell_recommendation, "⚪")

        reasons_text = "\n".join(f"• {r}" for r in sell_reasons[:5])

        message = f"""{emoji} <b>매도 권장 알림</b>

📅 {now}

<b>종목:</b> {display_name} ({symbol})
<b>현재가:</b> {current_price:,.0f}원
<b>추천:</b> {sell_recommendation} (강도: {sell_signal_strength})

<b>매도 근거:</b>
{reasons_text}"""

        return await self.send_message(message)

    async def send_sell_signals_summary(
        self,
        stocks: list[dict],
    ) -> bool:
        """
        매도 권장 종목 요약 알림 전송

        Args:
            stocks: 매도 권장 종목 리스트
        """
        if not stocks:
            return False

        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

        lines = [f"🔴 <b>매도 권장 종목 알림</b>", f"📅 {now} (KST)", f"총 {len(stocks)}개 종목", ""]

        for stock in stocks[:10]:  # 최대 10개
            emoji = "🔴" if stock.get("sell_recommendation") == "STRONG_SELL" else "🟠"
            name = stock.get("name") or stock.get("symbol")

            # Stochastic/RSI 과매수 관련 메시지 필터링
            reasons = stock.get("sell_reasons", [])
            filtered_reasons = [
                r for r in reasons
                if "Stochastic" not in r and "stochastic" not in r
                and "RSI 과매수" not in r and "RSI 극단적" not in r
            ]
            reasons_text = ", ".join(filtered_reasons[:3]) if filtered_reasons else ""

            if reasons_text:
                lines.append(
                    f"{emoji} <b>{name}</b> ({stock['symbol']})\n"
                    f"  {stock['sell_recommendation']} (강도: {stock.get('sell_signal_strength', 0)})\n"
                    f"  💡 {reasons_text}"
                )
            else:
                lines.append(
                    f"{emoji} <b>{name}</b> ({stock['symbol']})\n"
                    f"  {stock['sell_recommendation']} (강도: {stock.get('sell_signal_strength', 0)})"
                )

        if len(stocks) > 10:
            lines.append(f"\n... 외 {len(stocks) - 10}개")

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
