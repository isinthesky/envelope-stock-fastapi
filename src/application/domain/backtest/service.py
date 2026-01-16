# -*- coding: utf-8 -*-
"""
Backtest Service - 백테스팅 서비스

백테스팅 실행 및 관리를 담당하는 서비스 레이어
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.exceptions import BacktestDataError, BacktestError
from src.application.domain.backtest.data_loader import BacktestDataLoader
from src.application.domain.backtest.dto import (
    BacktestRequestDTO,
    BacktestResultDTO,
    MultiSymbolBacktestRequestDTO,
    MultiSymbolBacktestResultDTO,
)
from src.application.domain.backtest.engine import BacktestEngine
from src.application.domain.market_data.service import MarketDataService


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
