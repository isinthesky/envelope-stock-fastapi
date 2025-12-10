# -*- coding: utf-8 -*-
"""
News Trading Strategy Engine - 뉴스 기반 단타 전략 엔진

Phase 1~4 통합 구현:
- 타임라인: 전일 18:00~19:00 뉴스 분석 → 09:00~09:10 복합 조건 → 09:10 진입 → 10:40 청산
- 분할 익절 + 모멘텀 기반 동적 청산
- SafetyGuard 리스크 관리
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, time, date, timedelta
from decimal import Decimal
from typing import Any, Callable, Awaitable

from src.application.domain.news_trading.dto import (
    NewsEventType,
    NewsItemDTO,
    NewsAnalysisRequestDTO,
    NewsAnalysisResultDTO,
    StockCandidateDTO,
    StockSelectionResultDTO,
    ExitReason,
    TradingStatus,
    TradingSignalDTO,
    TradingResultDTO,
    NewsTradingStrategyConfigDTO,
    MomentumSignal,
)
from src.application.domain.news_trading.news_analyzer import NewsAnalyzer
from src.application.domain.news_trading.stock_selector import StockSelector
from src.application.domain.news_trading.exit_manager import ExitManager
from src.application.domain.news_trading.momentum_detector import MomentumDetector
from src.application.domain.news_trading.safety_guard import SafetyGuard


logger = logging.getLogger(__name__)


@dataclass
class TradingSession:
    """거래 세션 상태"""
    date: date
    status: str = "initialized"  # initialized, news_analyzed, selecting, trading, closed

    # 뉴스 분석 결과
    news_analysis: NewsAnalysisResultDTO | None = None
    candidate_symbols: list[str] = field(default_factory=list)

    # 종목 선별 결과
    stock_selection: StockSelectionResultDTO | None = None
    selected_symbols: list[str] = field(default_factory=list)
    is_no_trade_day: bool = False
    no_trade_reason: str | None = None

    # 거래 결과
    trades: list[TradingResultDTO] = field(default_factory=list)

    # 세션 통계
    total_trades: int = 0
    winning_trades: int = 0
    total_pnl: Decimal = Decimal("0")


class NewsTradingStrategyEngine:
    """
    뉴스 기반 단타 전략 엔진

    주요 기능:
    1. 뉴스 분석 및 종목 리스트 생성
    2. 복합 조건 필터링 및 종목 선별
    3. 진입/청산 관리
    4. 리스크 관리 (SafetyGuard)
    """

    def __init__(
        self,
        config: NewsTradingStrategyConfigDTO | None = None,
        initial_capital: Decimal = Decimal("10_000_000"),
        # 외부 의존성 (실시간 데이터 조회용)
        get_current_price: Callable[[str], Awaitable[Decimal]] | None = None,
        get_orderbook: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
        get_volume_data: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
        get_investor_trend: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
        execute_order: Callable[[str, str, int, Decimal], Awaitable[bool]] | None = None,
    ):
        """
        Args:
            config: 전략 설정
            initial_capital: 초기 자본
            get_current_price: 현재가 조회 함수
            get_orderbook: 호가 조회 함수
            get_volume_data: 거래량 조회 함수
            get_investor_trend: 투자자 동향 조회 함수
            execute_order: 주문 실행 함수
        """
        self.config = config or NewsTradingStrategyConfigDTO()
        self.initial_capital = initial_capital

        # 외부 의존성
        self.get_current_price = get_current_price
        self.get_orderbook = get_orderbook
        self.get_volume_data = get_volume_data
        self.get_investor_trend = get_investor_trend
        self.execute_order = execute_order

        # 내부 컴포넌트 초기화
        self.news_analyzer = NewsAnalyzer(
            min_news_score=self.config.stock_selection.min_top_news_score
        )
        self.stock_selector = StockSelector(config=self.config.stock_selection)
        self.exit_manager = ExitManager(
            config=self.config.trading_session.exit_config
        )
        self.momentum_detector = MomentumDetector(
            config=self.config.trading_session.exit_config.momentum_exit
        )
        self.safety_guard = SafetyGuard(
            config=self.config.safety_guard,
            initial_capital=initial_capital,
        )

        # 현재 세션
        self.current_session: TradingSession | None = None

        # 실행 상태
        self._running = False
        self._task: asyncio.Task | None = None

    # ==================== 세션 관리 ====================

    def start_session(self, session_date: date | None = None) -> TradingSession:
        """새 거래 세션 시작"""
        session_date = session_date or date.today()
        self.current_session = TradingSession(date=session_date)
        self.safety_guard.reset_daily_stats()
        logger.info(f"거래 세션 시작: {session_date}")
        return self.current_session

    def end_session(self) -> TradingSession | None:
        """거래 세션 종료"""
        if self.current_session:
            self.current_session.status = "closed"
            logger.info(
                f"거래 세션 종료: {self.current_session.date}, "
                f"거래 {self.current_session.total_trades}건, "
                f"수익 {self.current_session.winning_trades}건, "
                f"손익 {self.current_session.total_pnl:+,.0f}원"
            )
        return self.current_session

    # ==================== 뉴스 분석 ====================

    def analyze_news(
        self,
        news_items: list[NewsItemDTO],
        analysis_date: datetime | None = None,
    ) -> NewsAnalysisResultDTO:
        """
        뉴스 분석 및 종목 리스트 생성

        Args:
            news_items: 뉴스 목록
            analysis_date: 분석 대상 날짜

        Returns:
            뉴스 분석 결과
        """
        analysis_date = analysis_date or datetime.now()

        request = NewsAnalysisRequestDTO(
            target_date=analysis_date,
            news_items=news_items,
            min_news_score=self.config.stock_selection.min_top_news_score,
        )

        result = self.news_analyzer.analyze_news(request)

        if self.current_session:
            self.current_session.news_analysis = result
            self.current_session.candidate_symbols = result.candidate_symbols
            self.current_session.status = "news_analyzed"

        logger.info(
            f"뉴스 분석 완료: {result.total_news_count}건 중 "
            f"{result.filtered_news_count}건 필터링, "
            f"{len(result.candidate_symbols)}개 종목 후보"
        )

        return result

    # ==================== 종목 선별 ====================

    async def select_stocks(
        self,
        candidate_symbols: list[str] | None = None,
    ) -> StockSelectionResultDTO:
        """
        복합 조건 필터링 및 종목 선별

        Args:
            candidate_symbols: 후보 종목 리스트 (None이면 뉴스 분석 결과 사용)

        Returns:
            종목 선별 결과
        """
        if candidate_symbols is None and self.current_session:
            candidate_symbols = self.current_session.candidate_symbols

        if not candidate_symbols:
            logger.warning("후보 종목이 없습니다")
            return StockSelectionResultDTO(
                selection_time=datetime.now(),
                total_candidates=0,
                filtered_candidates=0,
                ranked_stocks=[],
                selected_symbols=[],
                is_no_trade_day=True,
                no_trade_reason="후보 종목 없음",
            )

        # 종목별 실시간 데이터 수집
        candidates = await self._collect_stock_data(candidate_symbols)

        # 뉴스 스코어 적용
        symbol_scores = {}
        if self.current_session and self.current_session.news_analysis:
            symbol_scores = self.current_session.news_analysis.symbol_scores

        # 종목 선별 실행
        result = self.stock_selector.select_stocks(
            candidates=candidates,
            symbol_news_scores=symbol_scores,
        )

        if self.current_session:
            self.current_session.stock_selection = result
            self.current_session.selected_symbols = result.selected_symbols
            self.current_session.is_no_trade_day = result.is_no_trade_day
            self.current_session.no_trade_reason = result.no_trade_reason
            self.current_session.status = "selecting"

        logger.info(
            f"종목 선별 완료: {result.filtered_candidates}개 필터 통과, "
            f"{len(result.selected_symbols)}개 선정"
            + (f" (No-trade: {result.no_trade_reason})" if result.is_no_trade_day else "")
        )

        return result

    async def _collect_stock_data(
        self,
        symbols: list[str],
    ) -> list[StockCandidateDTO]:
        """종목별 실시간 데이터 수집"""
        candidates: list[StockCandidateDTO] = []

        for symbol in symbols:
            try:
                # 현재가 조회
                current_price = Decimal("0")
                if self.get_current_price:
                    current_price = await self.get_current_price(symbol)

                # 호가 조회
                orderbook = {}
                if self.get_orderbook:
                    orderbook = await self.get_orderbook(symbol)

                # 거래량 조회
                volume_data = {}
                if self.get_volume_data:
                    volume_data = await self.get_volume_data(symbol)

                # 투자자 동향 조회
                investor_trend = {}
                if self.get_investor_trend:
                    investor_trend = await self.get_investor_trend(symbol)

                candidate = StockCandidateDTO(
                    symbol=symbol,
                    name=volume_data.get("name", symbol),
                    current_price=current_price,
                    open_price=Decimal(str(volume_data.get("open", current_price))),
                    prev_close=Decimal(str(volume_data.get("prev_close", current_price))),
                    volume_ratio=volume_data.get("volume_ratio", 1.0),
                    price_change_rate=volume_data.get("price_change_rate", 0.0),
                    foreign_net_buy=investor_trend.get("foreign_net_buy", 0),
                    institution_net_buy=investor_trend.get("institution_net_buy", 0),
                    bid_ask_ratio=orderbook.get("bid_ask_ratio", 1.0),
                    market_cap=Decimal(str(volume_data.get("market_cap", 0))),
                    spread_rate=orderbook.get("spread_rate", 0.0),
                )

                candidates.append(candidate)

            except Exception as e:
                logger.error(f"종목 데이터 수집 실패: {symbol}, {e}")

        return candidates

    # ==================== 진입 관리 ====================

    async def execute_entries(self) -> list[TradingSignalDTO]:
        """
        선정된 종목에 대해 진입 실행

        Returns:
            진입 신호 목록
        """
        if not self.current_session or self.current_session.is_no_trade_day:
            return []

        signals: list[TradingSignalDTO] = []

        for symbol in self.current_session.selected_symbols:
            # 거래 가능 여부 확인
            can_trade, block_reason, message = self.safety_guard.can_trade()
            if not can_trade:
                logger.warning(f"거래 차단: {symbol}, {message}")
                continue

            try:
                # 현재가 조회
                current_price = Decimal("0")
                if self.get_current_price:
                    current_price = await self.get_current_price(symbol)

                # 포지션 사이즈 계산
                amount, quantity = self.safety_guard.calculate_position_size(
                    symbol, current_price
                )

                if quantity <= 0:
                    logger.warning(f"포지션 사이즈 부족: {symbol}")
                    continue

                # 주문 실행
                if self.execute_order:
                    success = await self.execute_order(symbol, "buy", quantity, current_price)
                    if not success:
                        logger.error(f"주문 실패: {symbol}")
                        continue

                # SafetyGuard에 포지션 등록
                self.safety_guard.open_position(symbol, amount)

                # ExitManager에 포지션 등록
                stock_selection = self.current_session.stock_selection
                candidate = None
                if stock_selection:
                    for ranked in stock_selection.ranked_stocks:
                        if ranked.symbol == symbol:
                            candidate = ranked.candidate
                            break

                self.exit_manager.open_position(
                    symbol=symbol,
                    name=candidate.name if candidate else symbol,
                    entry_time=datetime.now(),
                    entry_price=current_price,
                    quantity=quantity,
                    news_score=candidate.news_score if candidate else 0.0,
                    event_types=[e.value for e in (candidate.event_types if candidate else [])],
                )

                # 신호 생성
                signal = TradingSignalDTO(
                    signal_time=datetime.now(),
                    symbol=symbol,
                    signal_type="buy",
                    reason=f"복합 조건 충족: {candidate.name if candidate else symbol}",
                    price=current_price,
                    quantity=quantity,
                )
                signals.append(signal)

                logger.info(f"진입 완료: {symbol}, {quantity}주 @ {current_price:,.0f}")

            except Exception as e:
                logger.error(f"진입 실행 실패: {symbol}, {e}")

        return signals

    # ==================== 청산 관리 ====================

    async def check_exits(self) -> list[TradingSignalDTO]:
        """
        모든 포지션에 대해 청산 조건 체크

        Returns:
            청산 신호 목록
        """
        signals: list[TradingSignalDTO] = []
        current_time = datetime.now()

        for symbol, position in list(self.exit_manager.positions.items()):
            if position.status == TradingStatus.CLOSED:
                continue

            try:
                # 현재가 조회
                current_price = position.entry_price
                if self.get_current_price:
                    current_price = await self.get_current_price(symbol)

                # 모멘텀 데이터 업데이트 (옵션)
                # self.momentum_detector.update_price(...)

                # 청산 조건 체크
                signal = self.exit_manager.check_exit_conditions(
                    symbol=symbol,
                    current_price=current_price,
                    current_time=current_time,
                )

                if signal:
                    signals.append(signal)
                    await self._execute_exit(signal)

            except Exception as e:
                logger.error(f"청산 체크 실패: {symbol}, {e}")

        return signals

    async def _execute_exit(self, signal: TradingSignalDTO) -> None:
        """청산 실행"""
        symbol = signal.symbol
        position = self.exit_manager.get_position(symbol)

        if not position:
            return

        try:
            # 주문 실행
            if self.execute_order:
                success = await self.execute_order(
                    symbol, "sell", signal.quantity or 0, signal.price
                )
                if not success:
                    logger.error(f"청산 주문 실패: {symbol}")
                    return

            # 청산 처리
            is_full_exit = (
                signal.exit_reason
                in [
                    ExitReason.STOP_LOSS,
                    ExitReason.TIME_EXIT,
                    ExitReason.SECOND_PROFIT_TAKING,
                    ExitReason.MOMENTUM_EXIT,
                ]
            )

            if is_full_exit:
                realized_pnl = self.exit_manager.execute_full_exit(
                    symbol=symbol,
                    exit_price=signal.price,
                    exit_time=signal.signal_time,
                    exit_reason=signal.exit_reason or ExitReason.MANUAL,
                )
            else:
                realized_pnl = self.exit_manager.execute_partial_exit(
                    symbol=symbol,
                    exit_price=signal.price,
                    exit_quantity=signal.quantity or 0,
                    exit_time=signal.signal_time,
                    exit_reason=signal.exit_reason or ExitReason.FIRST_PROFIT_TAKING,
                )

            # SafetyGuard 업데이트
            if is_full_exit:
                is_win = realized_pnl > 0
                self.safety_guard.record_trade_result(
                    symbol=symbol,
                    is_win=is_win,
                    realized_pnl=realized_pnl,
                    exit_reason=signal.exit_reason.value if signal.exit_reason else None,
                )

                # 세션 통계 업데이트
                if self.current_session:
                    self.current_session.total_trades += 1
                    if is_win:
                        self.current_session.winning_trades += 1
                    self.current_session.total_pnl += realized_pnl

                    # 거래 결과 기록
                    trade_result = TradingResultDTO(
                        trade_id=f"{position.symbol}_{position.entry_time.strftime('%H%M%S')}",
                        symbol=position.symbol,
                        name=position.name,
                        entry_time=position.entry_time,
                        entry_price=position.entry_price,
                        entry_quantity=position.total_quantity,
                        first_exit_time=position.first_exit_time,
                        first_exit_price=position.first_exit_price,
                        first_exit_quantity=position.first_exit_quantity,
                        first_exit_reason=position.first_exit_reason,
                        final_exit_time=signal.signal_time,
                        final_exit_price=signal.price,
                        final_exit_quantity=signal.quantity,
                        final_exit_reason=signal.exit_reason,
                        realized_profit=position.realized_profit,
                        realized_profit_rate=float(position.realized_profit / (position.entry_price * position.total_quantity)) * 100,
                        status=TradingStatus.CLOSED,
                        holding_minutes=position.holding_duration_minutes,
                        news_score=position.news_score,
                        event_types=[NewsEventType(e) for e in position.event_types] if position.event_types else [],
                        momentum_signals_detected=signal.momentum_signals,
                    )
                    self.current_session.trades.append(trade_result)

            logger.info(
                f"청산 완료: {symbol}, {signal.exit_reason.value if signal.exit_reason else 'manual'}, "
                f"손익 {realized_pnl:+,.0f}원"
            )

        except Exception as e:
            logger.error(f"청산 실행 실패: {symbol}, {e}")

    # ==================== 메인 루프 ====================

    async def run(self) -> None:
        """
        전략 메인 루프

        타임라인:
        - 09:00~09:10: 복합 조건 확인
        - 09:10: 매수 진입
        - 09:10~10:40: 보유 (익절/손절 모니터링)
        - 10:40: 강제 청산
        """
        self._running = True
        monitoring_interval = self.config.trading_session.monitoring_interval_seconds

        while self._running:
            current_time = datetime.now().time()
            entry_time = self.config.trading_session.entry_config.entry_time
            exit_time = self.config.trading_session.exit_config.force_exit_time
            observation_start = self.config.trading_session.entry_config.observation_start_time

            try:
                # 09:00~09:10: 종목 선별 (진입 전)
                if observation_start <= current_time < entry_time:
                    if (
                        self.current_session
                        and self.current_session.status == "news_analyzed"
                    ):
                        await self.select_stocks()

                # 09:10: 진입 실행
                elif current_time >= entry_time and self.current_session:
                    if self.current_session.status == "selecting":
                        await self.execute_entries()
                        self.current_session.status = "trading"

                    # 09:10~10:40: 청산 모니터링
                    if self.current_session.status == "trading":
                        await self.check_exits()

                # 10:40 이후: 세션 종료
                if current_time >= exit_time:
                    self.end_session()
                    break

            except Exception as e:
                logger.error(f"전략 실행 오류: {e}")

            await asyncio.sleep(monitoring_interval)

    def stop(self) -> None:
        """전략 실행 중지"""
        self._running = False
        if self._task:
            self._task.cancel()

    # ==================== 상태 조회 ====================

    def get_status(self) -> dict[str, Any]:
        """현재 상태 요약"""
        session_info = None
        if self.current_session:
            session_info = {
                "date": self.current_session.date.isoformat(),
                "status": self.current_session.status,
                "candidate_symbols": self.current_session.candidate_symbols,
                "selected_symbols": self.current_session.selected_symbols,
                "is_no_trade_day": self.current_session.is_no_trade_day,
                "no_trade_reason": self.current_session.no_trade_reason,
                "total_trades": self.current_session.total_trades,
                "winning_trades": self.current_session.winning_trades,
                "total_pnl": float(self.current_session.total_pnl),
            }

        return {
            "running": self._running,
            "session": session_info,
            "safety_guard": self.safety_guard.get_status(),
            "positions": self.exit_manager.get_all_positions(),
        }
