# -*- coding: utf-8 -*-
"""
Strategy Execution Engine - 전략 실행 엔진

볼린저 밴드 기반 자동매매 전략 실행
"""

import asyncio
import json
from datetime import datetime, timedelta
from decimal import Decimal

from src.adapters.database.connection import get_async_session
from src.adapters.database.models.strategy import StrategyStatus
from src.adapters.database.repositories.strategy_repository import StrategyRepository
from src.adapters.external.kis_api.client import KISAPIClient
from src.application.common.indicators import TechnicalIndicators
from src.application.domain.account.service import AccountService
from src.application.domain.market_data.service import MarketDataService
from src.application.domain.order.dto import OrderCreateRequestDTO
from src.application.domain.order.service import OrderService
from src.application.domain.strategy.dto import StrategyConfigDTO
from src.settings.config import settings


class StrategyEngine:
    """
    전략 실행 엔진

    활성 전략을 주기적으로 체크하여 시그널 생성 및 자동 주문 실행
    """

    def __init__(self) -> None:
        self.is_running = False
        self.task: asyncio.Task | None = None
        self.indicators = TechnicalIndicators()

        # 각 전략별 가격 데이터 캐시
        self.price_cache: dict[str, dict[str, list[float]]] = {}  # strategy_id -> {symbol -> prices}

        # 각 전략별 포지션 상태
        self.positions: dict[str, dict[str, dict]] = {}  # strategy_id -> {symbol -> position_info}

    async def start(self) -> None:
        """백그라운드 태스크 시작"""
        if self.is_running:
            print("⚠️  Strategy engine is already running")
            return

        self.is_running = True
        self.task = asyncio.create_task(self._run())
        print("✅ Strategy execution engine started")

    async def stop(self) -> None:
        """백그라운드 태스크 중지"""
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        print("✅ Strategy execution engine stopped")

    async def _run(self) -> None:
        """메인 루프: 활성 전략 체크 및 실행"""
        while self.is_running:
            try:
                # 활성 전략 조회 및 실행
                await self._execute_active_strategies()

            except Exception as e:
                print(f"❌ Strategy engine error: {e}")

            # 60초 대기 (기본)
            await asyncio.sleep(60)

    async def _execute_active_strategies(self) -> None:
        """모든 활성 전략 실행"""
        async for session in get_async_session():
            try:
                strategy_repo = StrategyRepository(session)
                active_strategies = await strategy_repo.get_active_strategies()

                for strategy in active_strategies:
                    try:
                        await self._execute_strategy(strategy, session)
                    except Exception as e:
                        print(f"❌ Strategy {strategy.name} execution failed: {e}")
                        # 실행 통계 업데이트 (실패)
                        await strategy_repo.update_execution_stats(strategy.id, success=False)

            except Exception as e:
                print(f"❌ Failed to retrieve active strategies: {e}")

    async def _execute_strategy(self, strategy, session) -> None:
        """개별 전략 실행"""
        strategy_id = str(strategy.id)
        config = StrategyConfigDTO(**json.loads(strategy.config_json))

        # 종목별 실행
        for symbol in strategy.symbol_list:
            try:
                await self._execute_for_symbol(strategy, symbol, config, session)
            except Exception as e:
                print(f"❌ Strategy {strategy.name} for {symbol} failed: {e}")

    async def _execute_for_symbol(
        self, strategy, symbol: str, config: StrategyConfigDTO, session
    ) -> None:
        """종목별 전략 실행"""
        strategy_id = str(strategy.id)

        # 1. 차트 데이터 수집 (최근 100일)
        prices = await self._fetch_price_data(symbol)
        if not prices or len(prices) < config.bollinger_band.period:
            print(f"⚠️  Insufficient price data for {symbol}")
            return

        # 가격 캐시 업데이트
        if strategy_id not in self.price_cache:
            self.price_cache[strategy_id] = {}
        self.price_cache[strategy_id][symbol] = prices

        # 2. 기술적 지표 계산
        bb = self.indicators.calculate_bollinger_bands(
            prices, config.bollinger_band.period, config.bollinger_band.std_multiplier
        )
        envelope = self.indicators.calculate_envelope(
            prices, config.envelope.period, config.envelope.percentage
        )

        if bb["upper"] is None or envelope["upper"] is None:
            print(f"⚠️  Failed to calculate indicators for {symbol}")
            return

        current_price = prices[-1]

        # 3. 시그널 생성 (볼린저 밴드 + 엔벨로프 결합)
        signal = self.indicators.generate_combined_signal(
            current_price, bb, envelope, threshold=0.001, use_strict_mode=True
        )

        # 시그널 강도 계산 (디버깅/로깅용)
        signal_strength = self.indicators.get_signal_strength(current_price, bb, envelope)

        if signal != "hold":
            print(
                f"📊 {symbol} Signal: {signal.upper()} | "
                f"Price: {current_price:.0f} | "
                f"BB: [{bb['lower']:.0f}, {bb['middle']:.0f}, {bb['upper']:.0f}] | "
                f"ENV: [{envelope['lower']:.0f}, {envelope['middle']:.0f}, {envelope['upper']:.0f}] | "
                f"Strength: BB={signal_strength['bb_position']:.2f}, ENV={signal_strength['env_position']:.2f}"
            )

        # 4. 포지션 확인 및 주문 실행
        await self._handle_signal(strategy, symbol, signal, current_price, config, session)

    async def _fetch_price_data(self, symbol: str) -> list[float]:
        """차트 데이터 수집"""
        try:
            kis_client = KISAPIClient()
            market_data_service = MarketDataService(kis_client)

            # 일봉 데이터 조회 (최근 100일)
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=150)).strftime("%Y%m%d")

            chart_data = await market_data_service.get_chart_data(
                symbol=symbol,
                period="D",  # 일봉
                start_date=start_date,
                end_date=end_date,
            )

            # 종가 리스트 추출
            prices = [float(candle.close) for candle in chart_data.candles]
            return prices

        except Exception as e:
            print(f"❌ Failed to fetch price data for {symbol}: {e}")
            return []

    async def _handle_signal(
        self, strategy, symbol: str, signal: str, current_price: float, config: StrategyConfigDTO, session
    ) -> None:
        """시그널 처리 및 주문 실행"""
        strategy_id = str(strategy.id)

        # 포지션 초기화
        if strategy_id not in self.positions:
            self.positions[strategy_id] = {}
        if symbol not in self.positions[strategy_id]:
            self.positions[strategy_id][symbol] = {"position": None, "entry_price": None}

        position_info = self.positions[strategy_id][symbol]
        current_position = position_info.get("position")

        # 매수 시그널
        if signal == "buy" and current_position != "long":
            await self._execute_buy(strategy, symbol, current_price, config, session)
            self.positions[strategy_id][symbol] = {"position": "long", "entry_price": current_price}

        # 매도 시그널 (청산 또는 반대 시그널)
        elif signal == "sell" and current_position == "long":
            if config.risk_management.use_reverse_signal_exit:
                await self._execute_sell(strategy, symbol, current_price, config, session)
                self.positions[strategy_id][symbol] = {"position": None, "entry_price": None}

        # 손절/익절 체크
        if current_position == "long":
            entry_price = position_info.get("entry_price")
            if entry_price:
                await self._check_risk_management(
                    strategy, symbol, current_price, entry_price, config, session
                )

    async def _execute_buy(
        self, strategy, symbol: str, current_price: float, config: StrategyConfigDTO, session
    ) -> None:
        """매수 주문 실행"""
        try:
            # 계좌 잔고 조회
            kis_client = KISAPIClient()
            account_service = AccountService(kis_client)
            balance = await account_service.get_balance(strategy.account_no)

            # 포지션 크기 계산
            quantity = self.indicators.calculate_position_size(
                balance.total_cash, config.position.allocation_ratio, current_price
            )

            if quantity <= 0:
                print(f"⚠️  Insufficient cash for buying {symbol}")
                return

            # 매수 주문 생성
            order_service = OrderService(kis_client, session)
            order_request = OrderCreateRequestDTO(
                symbol=symbol,
                order_type="buy",
                price_type="limit",
                price=Decimal(str(current_price)),
                quantity=quantity,
                account_no=strategy.account_no,
            )

            order_result = await order_service.create_order(session, order_request)
            print(f"✅ Buy order created: {symbol} x {quantity} @ {current_price}")

            # 전략 실행 통계 업데이트 (성공)
            strategy_repo = StrategyRepository(session)
            await strategy_repo.update_execution_stats(strategy.id, success=True)

        except Exception as e:
            print(f"❌ Buy order failed for {symbol}: {e}")
            # 전략 실행 통계 업데이트 (실패)
            strategy_repo = StrategyRepository(session)
            await strategy_repo.update_execution_stats(strategy.id, success=False)

    async def _execute_sell(
        self, strategy, symbol: str, current_price: float, config: StrategyConfigDTO, session
    ) -> None:
        """매도 주문 실행 (청산)"""
        try:
            # 보유 수량 조회
            kis_client = KISAPIClient()
            account_service = AccountService(kis_client)
            positions = await account_service.get_positions(strategy.account_no)

            # 해당 종목 포지션 찾기
            target_position = None
            for pos in positions.positions:
                if pos.symbol == symbol:
                    target_position = pos
                    break

            if not target_position or target_position.quantity <= 0:
                print(f"⚠️  No position to sell for {symbol}")
                return

            # 매도 주문 생성
            order_service = OrderService(kis_client, session)
            order_request = OrderCreateRequestDTO(
                symbol=symbol,
                order_type="sell",
                price_type="limit",
                price=Decimal(str(current_price)),
                quantity=target_position.quantity,
                account_no=strategy.account_no,
            )

            order_result = await order_service.create_order(session, order_request)
            print(f"✅ Sell order created: {symbol} x {target_position.quantity} @ {current_price}")

            # 전략 실행 통계 업데이트 (성공)
            strategy_repo = StrategyRepository(session)
            await strategy_repo.update_execution_stats(strategy.id, success=True)

        except Exception as e:
            print(f"❌ Sell order failed for {symbol}: {e}")
            # 전략 실행 통계 업데이트 (실패)
            strategy_repo = StrategyRepository(session)
            await strategy_repo.update_execution_stats(strategy.id, success=False)

    async def _check_risk_management(
        self, strategy, symbol: str, current_price: float, entry_price: float, config: StrategyConfigDTO, session
    ) -> None:
        """리스크 관리 체크 (손절/익절)"""
        if not entry_price:
            return

        profit_ratio = (current_price - entry_price) / entry_price

        # 손절
        if config.risk_management.use_stop_loss and config.risk_management.stop_loss_ratio:
            if profit_ratio <= config.risk_management.stop_loss_ratio:
                print(f"⚠️  Stop loss triggered for {symbol}: {profit_ratio * 100:.2f}%")
                await self._execute_sell(strategy, symbol, current_price, config, session)
                strategy_id = str(strategy.id)
                self.positions[strategy_id][symbol] = {"position": None, "entry_price": None}
                return

        # 익절
        if config.risk_management.use_take_profit and config.risk_management.take_profit_ratio:
            if profit_ratio >= config.risk_management.take_profit_ratio:
                print(f"✅ Take profit triggered for {symbol}: {profit_ratio * 100:.2f}%")
                await self._execute_sell(strategy, symbol, current_price, config, session)
                strategy_id = str(strategy.id)
                self.positions[strategy_id][symbol] = {"position": None, "entry_price": None}
                return


# ==================== 싱글톤 인스턴스 ====================

_strategy_engine_instance: StrategyEngine | None = None


def get_strategy_engine() -> StrategyEngine:
    """
    StrategyEngine 싱글톤 인스턴스 반환

    Returns:
        StrategyEngine: 전략 실행 엔진 인스턴스
    """
    global _strategy_engine_instance
    if _strategy_engine_instance is None:
        _strategy_engine_instance = StrategyEngine()
    return _strategy_engine_instance
