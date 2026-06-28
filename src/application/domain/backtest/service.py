# -*- coding: utf-8 -*-
"""
Backtest Service - 백테스팅 서비스

백테스팅 실행 및 관리를 담당하는 서비스 레이어
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.exceptions import BacktestDataError, BacktestError
from src.application.domain.backtest.data_loader import BacktestDataLoader
from src.application.domain.backtest.dto import (
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
from src.application.domain.market_data.service import MarketDataService


@dataclass(frozen=True, slots=True)
class _PortfolioCandidate:
    symbol: str
    rank_return: float
    trade: TradeDTO


@dataclass(frozen=True, slots=True)
class _PortfolioPosition:
    symbol: str
    entry_date: datetime
    exit_date: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: int
    invested_cash: Decimal

    @property
    def exit_value(self) -> Decimal:
        return self.exit_price * self.quantity


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

    async def run_backtest(
        self,
        request: BacktestRequestDTO
    ) -> BacktestResultDTO:
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
            print(f"📥 데이터 수집 중: {request.symbol} ({request.start_date.date()} ~ {request.end_date.date()})")

            data, actual_start, actual_end = await self.data_loader.load_ohlcv_data(
                symbol=request.symbol,
                start_date=request.start_date,
                end_date=request.end_date
            )

            print(f"✅ 데이터 수집 완료: {len(data)}건")
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
            print(f"\n🔄 백테스팅 실행 중...")

            result = await engine.run(
                data=data,
                start_date=actual_start,
                end_date=actual_end
            )

            print(f"✅ 백테스팅 완료")
            print(f"\n📊 결과 요약:")
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
        self,
        request: MultiSymbolBacktestRequestDTO
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
                    backtest_config=request.backtest_config
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
            failed_count=failed_count
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

        sorted_by_return = sorted(symbol_summaries, key=lambda item: item.total_return, reverse=True)

        return UniverseBacktestSummaryDTO(
            requested_count=multi_result.total_count,
            success_count=multi_result.success_count,
            failed_count=multi_result.failed_count,
            average_return=round(sum(result.total_return for result in result_list) / len(result_list), 2),
            average_win_rate=round(sum(result.win_rate for result in result_list) / len(result_list), 2),
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
    ) -> UniverseBacktestPortfolioSummaryDTO:
        if max_positions < 1:
            raise BacktestError("max_positions must be at least 1")

        candidates = self._build_portfolio_candidates(multi_result)
        cash = initial_capital
        active_positions: list[_PortfolioPosition] = []
        completed_trades: list[UniverseBacktestPortfolioTradeDTO] = []
        equity_points = [initial_capital]
        entered_positions = 0
        rejected_candidates = 0
        slot_cash = initial_capital / Decimal(max_positions)

        for candidate in candidates:
            current_date = candidate.trade.entry_date
            retained_positions: list[_PortfolioPosition] = []
            released_position = False
            for position in active_positions:
                if position.exit_date <= current_date:
                    cash += position.exit_value
                    completed_trades.append(self._complete_portfolio_trade(position))
                    released_position = True
                else:
                    retained_positions.append(position)
            active_positions = retained_positions
            if released_position:
                active_equity = sum(item.invested_cash for item in active_positions)
                equity_points.append(cash + active_equity)

            if any(position.symbol == candidate.symbol for position in active_positions):
                continue
            if len(active_positions) >= max_positions or cash <= 0:
                rejected_candidates += 1
                continue

            entry_price = candidate.trade.entry_price
            exit_date = candidate.trade.exit_date
            exit_price = candidate.trade.exit_price
            if exit_date is None or exit_price is None or entry_price <= 0:
                rejected_candidates += 1
                continue

            investable_cash = min(cash, slot_cash)
            quantity = int(investable_cash / entry_price)
            if quantity < 1:
                rejected_candidates += 1
                continue

            invested_cash = entry_price * quantity
            cash -= invested_cash
            active_positions.append(
                _PortfolioPosition(
                    symbol=candidate.symbol,
                    entry_date=candidate.trade.entry_date,
                    exit_date=exit_date,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    quantity=quantity,
                    invested_cash=invested_cash,
                )
            )
            entered_positions += 1

        remaining_positions = sorted(active_positions, key=lambda item: item.exit_date)
        while remaining_positions:
            position = remaining_positions.pop(0)
            cash += position.exit_value
            completed_trades.append(self._complete_portfolio_trade(position))
            active_equity = sum(item.invested_cash for item in remaining_positions)
            equity_points.append(cash + active_equity)

        final_capital = cash
        total_return = self._percentage_change(initial_capital, final_capital)
        benchmark_return = self._average_benchmark_return(multi_result)
        winning_trades = sum(1 for trade in completed_trades if trade.profit > 0)
        losing_trades = sum(1 for trade in completed_trades if trade.profit < 0)
        total_trades = len(completed_trades)
        win_rate = round((winning_trades / total_trades) * 100, 2) if total_trades else 0.0

        return UniverseBacktestPortfolioSummaryDTO(
            ranking_method="entry_date_then_symbol_total_return_desc",
            position_sizing="equal_cash_slot_by_max_positions",
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

    def _build_portfolio_candidates(
        self,
        multi_result: MultiSymbolBacktestResultDTO,
    ) -> list[_PortfolioCandidate]:
        candidates: list[_PortfolioCandidate] = []
        for result in multi_result.results.values():
            for trade in result.trades:
                if trade.exit_date is None or trade.exit_price is None:
                    continue
                candidates.append(
                    _PortfolioCandidate(
                        symbol=result.symbol,
                        rank_return=result.total_return,
                        trade=trade,
                    )
                )
        return sorted(
            candidates,
            key=lambda item: (
                item.trade.entry_date,
                -item.rank_return,
                item.symbol,
                item.trade.trade_id,
            ),
        )

    def _complete_portfolio_trade(
        self,
        position: _PortfolioPosition,
    ) -> UniverseBacktestPortfolioTradeDTO:
        exit_value = position.exit_value
        profit = exit_value - position.invested_cash
        return UniverseBacktestPortfolioTradeDTO(
            symbol=position.symbol,
            entry_date=position.entry_date,
            exit_date=position.exit_date,
            entry_price=position.entry_price,
            exit_price=position.exit_price,
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
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
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
                symbol=symbol,
                start_date=start_date,
                end_date=end_date
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
                    "avg_volume": summary["avg_volume"]
                }
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

        print(f"\n📈 수익 지표:")
        print(f"  - 총 수익률: {result.total_return:.2f}%")
        print(f"  - 연환산 수익률: {result.annualized_return:.2f}%")
        print(f"  - CAGR: {result.cagr:.2f}%")

        print(f"\n📉 리스크 지표:")
        print(f"  - MDD: {result.mdd:.2f}%")
        print(f"  - 변동성: {result.volatility:.2f}%")
        print(f"  - Sharpe Ratio: {result.sharpe_ratio:.2f}")
        print(f"  - Sortino Ratio: {result.sortino_ratio:.2f}")
        print(f"  - Calmar Ratio: {result.calmar_ratio:.2f}")
        print(f"  - VaR (95%): {result.var_95:.2f}%")

        print(f"\n🎯 거래 통계:")
        print(f"  - 총 거래: {result.total_trades}회")
        print(f"  - 승률: {result.win_rate:.2f}%")
        print(f"  - Profit Factor: {result.profit_factor:.2f}")
        print(f"  - 평균 수익: {result.avg_win:.2f}%")
        print(f"  - 평균 손실: {result.avg_loss:.2f}%")
        print(f"  - 평균 보유: {result.avg_holding_days:.1f}일")
        print(f"  - 최대 연승: {result.max_consecutive_wins}회")
        print(f"  - 최대 연패: {result.max_consecutive_losses}회")

        if result.benchmark_return is not None:
            print(f"\n📊 벤치마크 비교:")
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
