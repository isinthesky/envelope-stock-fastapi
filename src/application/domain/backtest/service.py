# -*- coding: utf-8 -*-
"""
Backtest Service - 백테스팅 서비스

백테스팅 실행 및 관리를 담당하는 서비스 레이어
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.exceptions import BacktestDataError, BacktestError
from src.application.domain.backtest.data_loader import BacktestDataLoader
from src.application.domain.backtest.dto import (
    BacktestConfigDTO,
    BacktestRequestDTO,
    BacktestResultDTO,
    MultiSymbolBacktestRequestDTO,
    MultiSymbolBacktestResultDTO,
    TradeDTO,
    UniverseBacktestPortfolioSummaryDTO,
    UniverseBacktestPortfolioTradeDTO,
    UniverseBacktestResultDTO,
    UniverseBacktestSummaryDTO,
    UniverseBacktestSymbolSummaryDTO,
)
from src.application.domain.backtest.engine import BacktestEngine
from src.application.domain.backtest.order_manager import BacktestOrderManager
from src.application.domain.market_data.service import MarketDataService


@dataclass(frozen=True, slots=True)
class _CandidateLot:
    """엔진 포지션을 구성하는 lot(분할 청산 tranche) 하나."""

    quantity: int
    exit_date: datetime
    exit_price: Decimal
    forced_liquidation: bool = False  # 기간 종료 시 미청산 → 최종 바 청산 평가


@dataclass(frozen=True, slots=True)
class _PortfolioCandidate:
    symbol: str
    entry_date: datetime
    entry_price: Decimal
    lots: tuple[_CandidateLot, ...]


@dataclass(slots=True)
class _PortfolioTranche:
    quantity: int
    exit_date: datetime
    exit_price: Decimal


@dataclass(slots=True)
class _PortfolioPosition:
    symbol: str
    entry_date: datetime
    entry_price: Decimal
    quantity: int
    invested_cash: Decimal  # 매수 체결금액 + 매수 수수료
    tranches: list[_PortfolioTranche]
    exit_value: Decimal = Decimal("0")  # 누적 매도 순수령액(수수료·세금 차감)
    last_exit_date: datetime | None = None
    exited_quantity_value: Decimal = Decimal("0")  # Σ 체결가×수량(가중평균 청산가용)


def _day(value: datetime) -> date:
    return value.date() if hasattr(value, "date") else value


class BacktestService:
    """백테스팅 서비스"""

    def __init__(
        self,
        market_data_service: MarketDataService,
        db_session: AsyncSession | None = None,
    ):
        """
        Args:
            market_data_service: 시세 데이터 서비스
            db_session: DB 세션 (캐싱 사용 시 필수)
        """
        self.market_data_service = market_data_service
        self.db_session = db_session
        self.data_loader = BacktestDataLoader(market_data_service, db_session)
        # 포트폴리오 시뮬레이션의 일별 시가평가(MTM)용 종가 캐시: symbol -> {date: close}
        self.close_cache: dict[str, dict[date, Decimal]] = {}

    async def run_backtest(self, request: BacktestRequestDTO) -> BacktestResultDTO:
        """
        백테스팅 실행

        Args:
            request: 백테스팅 요청

        Returns:
            BacktestResultDTO: 백테스팅 결과

        Raises:
            BacktestDataError: 데이터 로드 실패
            BacktestError: 백테스팅 실행 실패
        """
        try:
            # 1. 데이터 로드
            print(
                f"📥 데이터 수집 중: {request.symbol} ({request.start_date.date()} ~ {request.end_date.date()})"
            )

            data, actual_start, actual_end = await self.data_loader.load_ohlcv_data(
                symbol=request.symbol, start_date=request.start_date, end_date=request.end_date
            )

            print(f"✅ 데이터 수집 완료: {len(data)}건")
            self.close_cache[request.symbol] = {
                _day(ts): Decimal(str(close)) for ts, close in zip(data["timestamp"], data["close"])
            }
            summary = self.data_loader.get_data_summary(data)

            if actual_start > request.start_date or actual_end < request.end_date:
                print(
                    "⚠️ 요청한 기간 전체가 제공되지 않았습니다. "
                    f"KIS API 제한으로 {actual_start.date()} ~ {actual_end.date()} 범위만 사용합니다."
                )

            print(f"  - 기간: {actual_start.date()} ~ {actual_end.date()}")
            print(f"  - 가격 범위: {summary['price_min']:,.0f} ~ {summary['price_max']:,.0f}")
            print(f"  - 평균 거래량: {summary['avg_volume']:,}")

            # 2. 엔진 초기화
            engine = BacktestEngine(
                symbol=request.symbol,
                strategy_config=request.strategy_config,
                backtest_config=request.backtest_config,
                strategy_type=request.strategy_type,
                strategy_params=request.strategy_params,
            )

            # 3. 백테스팅 실행
            print("\n🔄 백테스팅 실행 중...")

            result = await engine.run(data=data, start_date=actual_start, end_date=actual_end)

            print("✅ 백테스팅 완료")
            print("\n📊 결과 요약:")
            print(f"  - 총 수익률: {result.total_return:.2f}%")
            print(f"  - MDD: {result.mdd:.2f}%")
            print(f"  - Sharpe Ratio: {result.sharpe_ratio:.2f}")
            print(f"  - 체결 시점: {result.execution_timing}")
            print(f"  - 총 거래: {result.total_trades}회 (승률: {result.win_rate:.1f}%)")

            return result

        except BacktestDataError:
            raise
        except Exception as e:
            raise BacktestError(f"Backtest execution failed: {e}")

    async def run_multi_symbol_backtest(
        self, request: MultiSymbolBacktestRequestDTO
    ) -> MultiSymbolBacktestResultDTO:
        """
        다중 종목 백테스팅

        Args:
            request: 다중 종목 백테스팅 요청

        Returns:
            MultiSymbolBacktestResultDTO: 다중 종목 백테스팅 결과
        """
        results = {}
        success_count = 0
        failed_count = 0

        print(f"\n🚀 다중 종목 백테스팅 시작: {len(request.symbols)}개 종목")
        print("=" * 80)

        for idx, symbol in enumerate(request.symbols, 1):
            print(f"\n[{idx}/{len(request.symbols)}] {symbol} 백테스팅 중...")

            try:
                # 단일 종목 백테스팅 요청 생성
                single_request = BacktestRequestDTO(
                    symbol=symbol,
                    start_date=request.start_date,
                    end_date=request.end_date,
                    strategy_type=request.strategy_type,
                    strategy_params=request.strategy_params,
                    strategy_config=request.strategy_config,
                    backtest_config=request.backtest_config,
                )

                # 백테스팅 실행
                result = await self.run_backtest(single_request)

                results[symbol] = result
                success_count += 1

            except Exception as e:
                print(f"❌ {symbol} 백테스팅 실패: {e}")
                failed_count += 1

        print("\n" + "=" * 80)
        print(f"🎉 다중 종목 백테스팅 완료: 성공 {success_count}개, 실패 {failed_count}개")

        return MultiSymbolBacktestResultDTO(
            results=results,
            total_count=len(request.symbols),
            success_count=success_count,
            failed_count=failed_count,
        )

    def summarize_multi_symbol_results(
        self,
        multi_result: MultiSymbolBacktestResultDTO,
    ) -> UniverseBacktestSummaryDTO:
        """다중 종목 백테스트 결과를 sell 전략 페이지용 요약으로 집계"""
        result_list = list(multi_result.results.values())
        if not result_list:
            return UniverseBacktestSummaryDTO(
                requested_count=multi_result.total_count,
                success_count=multi_result.success_count,
                failed_count=multi_result.failed_count,
                average_return=0.0,
                average_win_rate=0.0,
                average_mdd=0.0,
                average_holding_days=0.0,
                profitable_symbols=0,
                profitable_ratio=0.0,
                total_trades=0,
                best_symbols=[],
                worst_symbols=[],
            )

        symbol_summaries = [
            UniverseBacktestSymbolSummaryDTO(
                symbol=result.symbol,
                total_return=result.total_return,
                win_rate=result.win_rate,
                total_trades=result.total_trades,
                mdd=result.mdd,
                avg_holding_days=result.avg_holding_days,
            )
            for result in result_list
        ]

        profitable_symbols = sum(1 for result in result_list if result.total_return > 0)
        profitable_ratio = (profitable_symbols / len(result_list)) * 100 if result_list else 0.0

        sorted_by_return = sorted(
            symbol_summaries, key=lambda item: item.total_return, reverse=True
        )

        return UniverseBacktestSummaryDTO(
            requested_count=multi_result.total_count,
            success_count=multi_result.success_count,
            failed_count=multi_result.failed_count,
            average_return=round(
                sum(result.total_return for result in result_list) / len(result_list), 2
            ),
            average_win_rate=round(
                sum(result.win_rate for result in result_list) / len(result_list), 2
            ),
            average_mdd=round(sum(result.mdd for result in result_list) / len(result_list), 2),
            average_holding_days=round(
                sum(result.avg_holding_days for result in result_list) / len(result_list), 2
            ),
            profitable_symbols=profitable_symbols,
            profitable_ratio=round(profitable_ratio, 2),
            total_trades=sum(result.total_trades for result in result_list),
            best_symbols=sorted_by_return[:5],
            worst_symbols=list(reversed(sorted_by_return[-5:])),
        )

    def simulate_universe_portfolio(
        self,
        multi_result: MultiSymbolBacktestResultDTO,
        initial_capital: Decimal,
        max_positions: int,
        *,
        backtest_config: BacktestConfigDTO | None = None,
        price_series: dict[str, dict[date, Decimal]] | None = None,
    ) -> UniverseBacktestPortfolioSummaryDTO:
        """종목별 엔진 거래를 공유 현금북에 재배치하는 포트폴리오 시뮬레이션.

        - 후보 우선순위: 진입일 → 종목코드(사전순). **전체기간 수익률 랭킹은 사용하지
          않는다**(미래 정보 누수 제거).
        - 엔진의 분할 lot은 한 포지션의 tranche로 묶어 lot 비율대로 부분 청산한다.
        - ``backtest_config``가 주어지면 매수 수수료, 매도 수수료·세금(ETF 면제)을 반영.
        - 종가 시계열(``price_series`` 또는 실행 중 캐시)이 있으면 **일별 시가평가**로
          MDD를 계산하고, 기간 종료 시 미청산 lot은 최종 바에서 청산비용 차감 평가.
          없으면 레거시(이벤트 시점·원가 평가)로 폴백하며 ``equity_valuation``에 표기.
        """
        if max_positions < 1:
            raise BacktestError("max_positions must be at least 1")

        prices = price_series if price_series is not None else self.close_cache
        order_manager = BacktestOrderManager(backtest_config) if backtest_config else None
        candidates = self._build_portfolio_candidates(multi_result, prices, order_manager)
        cash = initial_capital
        active_positions: list[_PortfolioPosition] = []
        completed_trades: list[UniverseBacktestPortfolioTradeDTO] = []
        ledger: list[tuple[datetime, int, str, int, Decimal]] = (
            []
        )  # (일시, 순서, 종목, Δ수량, Δ현금)
        entered_positions = 0
        rejected_candidates = 0
        slot_cash = initial_capital / Decimal(max_positions)

        def release(until: datetime | None) -> None:
            nonlocal cash, active_positions
            retained: list[_PortfolioPosition] = []
            for position in active_positions:
                remaining: list[_PortfolioTranche] = []
                for tranche in position.tranches:
                    if until is None or tranche.exit_date <= until:
                        net = self._tranche_net_proceeds(position.symbol, tranche, order_manager)
                        cash += net
                        position.exit_value += net
                        position.exited_quantity_value += tranche.exit_price * tranche.quantity
                        position.last_exit_date = max(
                            position.last_exit_date or tranche.exit_date, tranche.exit_date
                        )
                        ledger.append(
                            (tranche.exit_date, 0, position.symbol, -tranche.quantity, net)
                        )
                    else:
                        remaining.append(tranche)
                position.tranches = remaining
                if remaining:
                    retained.append(position)
                else:
                    completed_trades.append(self._complete_portfolio_trade(position))
            active_positions = retained

        for candidate in candidates:
            release(candidate.entry_date)

            if any(position.symbol == candidate.symbol for position in active_positions):
                continue
            if len(active_positions) >= max_positions or cash <= 0:
                rejected_candidates += 1
                continue

            entry_price = candidate.entry_price
            if entry_price <= 0:
                rejected_candidates += 1
                continue
            commission_rate = (
                order_manager.buy_commission(Decimal("1"), candidate.entry_date)
                if order_manager
                else Decimal("0")
            )
            investable_cash = min(cash, slot_cash)
            quantity = int(investable_cash / (entry_price * (Decimal("1") + commission_rate)))
            if quantity < 1:
                rejected_candidates += 1
                continue

            purchase = entry_price * quantity
            commission = (
                order_manager.buy_commission(purchase, candidate.entry_date)
                if order_manager
                else Decimal("0")
            )
            invested_cash = purchase + commission
            cash -= invested_cash
            ledger.append((candidate.entry_date, 1, candidate.symbol, quantity, -invested_cash))
            active_positions.append(
                _PortfolioPosition(
                    symbol=candidate.symbol,
                    entry_date=candidate.entry_date,
                    entry_price=entry_price,
                    quantity=quantity,
                    invested_cash=invested_cash,
                    tranches=self._allocate_tranches(quantity, candidate.lots),
                )
            )
            entered_positions += 1

        release(None)

        final_capital = cash
        total_return = self._percentage_change(initial_capital, final_capital)
        benchmark_return = self._average_benchmark_return(multi_result)
        winning_trades = sum(1 for trade in completed_trades if trade.profit > 0)
        losing_trades = sum(1 for trade in completed_trades if trade.profit < 0)
        total_trades = len(completed_trades)
        win_rate = round((winning_trades / total_trades) * 100, 2) if total_trades else 0.0
        equity_points, valuation = self._portfolio_equity_curve(initial_capital, ledger, prices)

        return UniverseBacktestPortfolioSummaryDTO(
            ranking_method="entry_date_then_symbol_asc(no_lookahead)",
            position_sizing="equal_cash_slot_by_max_positions",
            equity_valuation=valuation,
            cost_model=(
                "commission+sell_tax(etf_exempt)+engine_slippage"
                if order_manager
                else "engine_slippage_only(no_commission_tax)"
            ),
            initial_capital=initial_capital,
            final_capital=final_capital,
            ending_cash=cash,
            total_return=total_return,
            benchmark_return=benchmark_return,
            excess_return=round(total_return - benchmark_return, 2),
            max_positions=max_positions,
            entered_positions=entered_positions,
            rejected_candidates=rejected_candidates,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            mdd=self._calculate_portfolio_mdd(equity_points),
            trades=completed_trades,
        )

    @staticmethod
    def _allocate_tranches(
        quantity: int, lots: tuple[_CandidateLot, ...]
    ) -> list[_PortfolioTranche]:
        """포트폴리오 수량을 엔진 lot 비율대로 tranche에 배분(나머지는 마지막 lot)."""
        total = sum(lot.quantity for lot in lots)
        tranches: list[_PortfolioTranche] = []
        allocated = 0
        for idx, lot in enumerate(lots):
            if idx == len(lots) - 1:
                qty = quantity - allocated
            else:
                qty = quantity * lot.quantity // total if total > 0 else 0
                allocated += qty
            if qty > 0:
                tranches.append(_PortfolioTranche(qty, lot.exit_date, lot.exit_price))
        return tranches

    @staticmethod
    def _tranche_net_proceeds(
        symbol: str,
        tranche: _PortfolioTranche,
        order_manager: BacktestOrderManager | None,
    ) -> Decimal:
        amount = tranche.exit_price * tranche.quantity
        if order_manager is None:
            return amount
        return amount - order_manager.sell_costs(amount, tranche.exit_date, symbol)

    def _portfolio_equity_curve(
        self,
        initial_capital: Decimal,
        ledger: list[tuple[datetime, int, str, int, Decimal]],
        prices: dict[str, dict[date, Decimal]],
    ) -> tuple[list[Decimal], str]:
        """현금 원장 + 종가로 일별 시가평가 자산곡선을 만든다(불가 시 레거시 폴백)."""
        if not ledger:
            return [initial_capital], "daily_mark_to_market"
        symbols = {row[2] for row in ledger}
        if not all(prices.get(sym) for sym in symbols):
            return self._legacy_equity_points(initial_capital, ledger), "event_cost_basis(legacy)"

        ordered = sorted(ledger, key=lambda row: (_day(row[0]), row[1]))
        first_day, last_day = _day(ordered[0][0]), _day(ordered[-1][0])
        calendar = sorted(
            {d for sym in symbols for d in prices[sym] if first_day <= d <= last_day}
            | {_day(row[0]) for row in ordered}
        )
        cash = initial_capital
        holdings: dict[str, int] = {}
        last_close: dict[str, Decimal] = {}
        equity_points = [initial_capital]
        idx = 0
        for day in calendar:
            while idx < len(ordered) and _day(ordered[idx][0]) <= day:
                _, _, sym, dq, dcash = ordered[idx]
                cash += dcash
                holdings[sym] = holdings.get(sym, 0) + dq
                idx += 1
            value = Decimal("0")
            for sym, qty in holdings.items():
                if qty <= 0:
                    continue
                close = prices[sym].get(day)
                if close is not None:
                    last_close[sym] = close
                value += last_close.get(sym, Decimal("0")) * qty
            equity_points.append(cash + value)
        return equity_points, "daily_mark_to_market"

    @staticmethod
    def _legacy_equity_points(
        initial_capital: Decimal, ledger: list[tuple[datetime, int, str, int, Decimal]]
    ) -> list[Decimal]:
        """종가가 없을 때: 이벤트 시점에 보유분을 원가로 평가(MDD 과소추정 가능)."""
        cash = initial_capital
        cost_basis: dict[str, Decimal] = {}
        qty_left: dict[str, int] = {}
        points = [initial_capital]
        for _, _, sym, dq, dcash in sorted(ledger, key=lambda row: (row[0], row[1])):
            cash += dcash
            if dq > 0:
                cost_basis[sym] = -dcash
                qty_left[sym] = dq
            else:
                total_qty = qty_left.get(sym, 0)
                if total_qty > 0:
                    cost_basis[sym] = cost_basis[sym] * Decimal(total_qty + dq) / Decimal(total_qty)
                qty_left[sym] = total_qty + dq
                points.append(cash + sum(cost_basis.values()))
        return points

    def _build_portfolio_candidates(
        self,
        multi_result: MultiSymbolBacktestResultDTO,
        prices: dict[str, dict[date, Decimal]] | None = None,
        order_manager: BacktestOrderManager | None = None,
    ) -> list[_PortfolioCandidate]:
        """엔진 거래를 (종목, 진입일) 포지션 단위로 묶는다.

        미청산 lot은 종가가 있으면 최종 바 종가(매도 슬리피지 반영)로 강제 청산 평가하고,
        없으면 제외한다(레거시).
        """
        prices = prices or {}
        candidates: list[_PortfolioCandidate] = []
        for result in multi_result.results.values():
            grouped: dict[datetime, list[TradeDTO]] = {}
            for trade in result.trades:
                grouped.setdefault(trade.entry_date, []).append(trade)
            series = prices.get(result.symbol) or {}
            last_day = max(series) if series else None
            for entry_date, trades in grouped.items():
                lots: list[_CandidateLot] = []
                for trade in sorted(trades, key=lambda item: item.trade_id):
                    if trade.exit_date is not None and trade.exit_price is not None:
                        lots.append(
                            _CandidateLot(trade.quantity, trade.exit_date, trade.exit_price)
                        )
                    elif last_day is not None:
                        exit_dt = datetime.combine(last_day, datetime.min.time())
                        close = series[last_day]
                        exit_price = (
                            order_manager.sell_execution_price(close, exit_dt)
                            if order_manager
                            else close
                        )
                        lots.append(_CandidateLot(trade.quantity, exit_dt, exit_price, True))
                if not lots:
                    continue
                candidates.append(
                    _PortfolioCandidate(
                        symbol=result.symbol,
                        entry_date=entry_date,
                        entry_price=trades[0].entry_price,
                        lots=tuple(lots),
                    )
                )
        return sorted(candidates, key=lambda item: (item.entry_date, item.symbol))

    def _complete_portfolio_trade(
        self,
        position: _PortfolioPosition,
    ) -> UniverseBacktestPortfolioTradeDTO:
        exit_value = position.exit_value
        profit = exit_value - position.invested_cash
        avg_exit_price = (
            position.exited_quantity_value / position.quantity
            if position.quantity > 0
            else Decimal("0")
        )
        return UniverseBacktestPortfolioTradeDTO(
            symbol=position.symbol,
            entry_date=position.entry_date,
            exit_date=position.last_exit_date or position.entry_date,
            entry_price=position.entry_price,
            exit_price=avg_exit_price,
            quantity=position.quantity,
            invested_cash=position.invested_cash,
            exit_value=exit_value,
            profit=profit,
            profit_rate=self._percentage_change(position.invested_cash, exit_value),
        )

    def _percentage_change(self, initial_value: Decimal, final_value: Decimal) -> float:
        if initial_value <= 0:
            return 0.0
        return round(float((final_value - initial_value) / initial_value * Decimal("100")), 2)

    def _average_benchmark_return(self, multi_result: MultiSymbolBacktestResultDTO) -> float:
        benchmark_returns = [
            result.benchmark_return
            for result in multi_result.results.values()
            if result.benchmark_return is not None
        ]
        if not benchmark_returns:
            return 0.0
        return round(sum(benchmark_returns) / len(benchmark_returns), 2)

    def _calculate_portfolio_mdd(self, equity_points: list[Decimal]) -> float:
        peak = equity_points[0] if equity_points else Decimal("0")
        max_drawdown = Decimal("0")
        for equity in equity_points:
            if equity > peak:
                peak = equity
            if peak > 0:
                drawdown = (equity - peak) / peak * Decimal("100")
                if drawdown < max_drawdown:
                    max_drawdown = drawdown
        return round(float(max_drawdown), 2)

    def build_universe_backtest_result(
        self,
        *,
        market: str | None,
        eligible_only: bool,
        symbols: list[str],
        request: MultiSymbolBacktestRequestDTO,
        multi_result: MultiSymbolBacktestResultDTO,
        config_summary: dict,
        portfolio_enabled: bool = False,
        max_positions: int | None = None,
    ) -> UniverseBacktestResultDTO:
        """유니버스 백테스트 결과 래핑"""
        summary = self.summarize_multi_symbol_results(multi_result)
        portfolio_summary = None
        if portfolio_enabled:
            portfolio_summary = self.simulate_universe_portfolio(
                multi_result,
                request.backtest_config.initial_capital,
                1 if max_positions is None else max_positions,
                backtest_config=request.backtest_config,
            )
        return UniverseBacktestResultDTO(
            market=market,
            eligible_only=eligible_only,
            symbols=symbols,
            start_date=request.start_date,
            end_date=request.end_date,
            strategy_type=request.strategy_type,
            config_summary=config_summary,
            portfolio_summary=portfolio_summary,
            summary=summary,
            diagnostic_summary=summary,
            results=multi_result.results,
        )

    async def validate_data_quality(
        self, symbol: str, start_date: datetime, end_date: datetime
    ) -> dict:
        """
        데이터 품질 검증

        Args:
            symbol: 종목코드
            start_date: 시작일
            end_date: 종료일

        Returns:
            dict: 검증 결과
        """
        try:
            # 데이터 로드
            data, actual_start, actual_end = await self.data_loader.load_ohlcv_data(
                symbol=symbol, start_date=start_date, end_date=end_date
            )

            # 결측일 검증
            coverage_start = max(start_date, actual_start)
            missing_result = self.data_loader.validate_missing_dates(
                data, coverage_start, actual_end
            )

            # 데이터 요약
            summary = self.data_loader.get_data_summary(data)

            return {
                "symbol": symbol,
                "data_quality": {
                    "total_rows": summary["total_rows"],
                    "requested_start": start_date,
                    "requested_end": end_date,
                    "start_date": actual_start,
                    "end_date": actual_end,
                    "coverage_rate": missing_result["coverage_rate"],
                    "missing_count": missing_result["missing_count"],
                    "is_truncated": actual_start > start_date or actual_end < end_date,
                },
                "price_stats": {
                    "min": float(summary["price_min"]),
                    "max": float(summary["price_max"]),
                    "avg_volume": summary["avg_volume"],
                },
            }

        except Exception as e:
            raise BacktestError(f"Data quality validation failed: {e}")

    def print_result_summary(self, result: BacktestResultDTO) -> None:
        """
        백테스팅 결과 요약 출력

        Args:
            result: 백테스팅 결과
        """
        print("\n" + "=" * 80)
        print("📊 백테스팅 성과 요약")
        print("=" * 80)

        print(f"\n📅 기간: {result.start_date.date()} ~ {result.end_date.date()}")
        print(f"⏱️ 체결 시점: {result.execution_timing}")
        print(f"💰 초기 자본: {result.initial_capital:,.0f}원")
        print(f"💰 최종 자본: {result.final_capital:,.0f}원")

        print("\n📈 수익 지표:")
        print(f"  - 총 수익률: {result.total_return:.2f}%")
        print(f"  - 연환산 수익률: {result.annualized_return:.2f}%")
        print(f"  - CAGR: {result.cagr:.2f}%")

        print("\n📉 리스크 지표:")
        print(f"  - MDD: {result.mdd:.2f}%")
        print(f"  - 변동성: {result.volatility:.2f}%")
        print(f"  - Sharpe Ratio: {result.sharpe_ratio:.2f}")
        print(f"  - Sortino Ratio: {result.sortino_ratio:.2f}")
        print(f"  - Calmar Ratio: {result.calmar_ratio:.2f}")
        print(f"  - VaR (95%): {result.var_95:.2f}%")

        print("\n🎯 거래 통계:")
        print(f"  - 총 거래: {result.total_trades}회")
        print(f"  - 승률: {result.win_rate:.2f}%")
        print(f"  - Profit Factor: {result.profit_factor:.2f}")
        print(f"  - 평균 수익: {result.avg_win:.2f}%")
        print(f"  - 평균 손실: {result.avg_loss:.2f}%")
        print(f"  - 평균 보유: {result.avg_holding_days:.1f}일")
        print(f"  - 최대 연승: {result.max_consecutive_wins}회")
        print(f"  - 최대 연패: {result.max_consecutive_losses}회")

        if result.benchmark_return is not None:
            print("\n📊 벤치마크 비교:")
            print(f"  - 벤치마크 수익률: {result.benchmark_return:.2f}%")
            print(f"  - Alpha: {result.alpha:.2f}%")
            print(f"  - Beta: {result.beta:.2f}")
            print(f"  - Tracking Error: {result.tracking_error:.2f}%")
            print(f"  - Information Ratio: {result.information_ratio:.2f}")

        print("\n" + "=" * 80)

    def get_strategy_performance_grade(self, result: BacktestResultDTO) -> str:
        """
        전략 성과 등급 평가

        Args:
            result: 백테스팅 결과

        Returns:
            str: 등급 (A+, A, B+, B, C+, C, D)
        """
        score = 0

        # 연환산 수익률 점수 (30점)
        if result.annualized_return > 20:
            score += 30
        elif result.annualized_return > 10:
            score += 20
        elif result.annualized_return > 0:
            score += 10

        # MDD 점수 (25점)
        if result.mdd > -15:
            score += 25
        elif result.mdd > -25:
            score += 15
        elif result.mdd > -35:
            score += 5

        # Sharpe Ratio 점수 (20점)
        if result.sharpe_ratio > 2.0:
            score += 20
        elif result.sharpe_ratio > 1.0:
            score += 15
        elif result.sharpe_ratio > 0.5:
            score += 10

        # 승률 점수 (15점)
        if result.win_rate > 60:
            score += 15
        elif result.win_rate > 50:
            score += 10
        elif result.win_rate > 40:
            score += 5

        # Profit Factor 점수 (10점)
        if result.profit_factor > 2.0:
            score += 10
        elif result.profit_factor > 1.5:
            score += 7
        elif result.profit_factor > 1.0:
            score += 4

        # 등급 산출
        if score >= 90:
            return "A+"
        elif score >= 80:
            return "A"
        elif score >= 70:
            return "B+"
        elif score >= 60:
            return "B"
        elif score >= 50:
            return "C+"
        elif score >= 40:
            return "C"
        else:
            return "D"
