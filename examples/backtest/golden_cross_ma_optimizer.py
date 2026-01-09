# -*- coding: utf-8 -*-
"""
골든크로스 MA 파라미터 최적화

MA55를 고정하고 장기 MA(150~170, 5단위)를 변경하면서
가장 높은 승률을 달성하는 파라미터를 탐색합니다.

현재 설정: MA55/MA165
"""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from dataclasses import dataclass

from examples.backtest.golden_cross_backtest import (
    GoldenCrossConfig,
    BacktestConfig,
    BacktestResult,
    GoldenCrossBacktester,
    get_analysis_history_symbols,
)

from src.adapters.cache.redis_client import get_redis_client
from src.adapters.database.connection import get_db
from src.adapters.external.kis_api.client import KISAPIClient
from src.application.domain.backtest.data_loader import BacktestDataLoader
from src.application.domain.market_data.service import MarketDataService


# 테스트할 장기 MA 범위 (150~170, 5단위)
SHORT_MA_FIXED = 55
LONG_MA_CANDIDATES = [150, 155, 160, 165, 170]

# 테스트 종목 수 (stock_universe에서 조회)
TEST_STOCK_COUNT = 50


async def get_stock_universe_symbols(db_session, limit: int = 50) -> list[dict]:
    """stock_universe 테이블에서 활성 종목 조회 (시가총액 상위)"""
    from sqlalchemy import text

    query = text("""
        SELECT symbol, name, market
        FROM stock_universe
        WHERE is_active = true
          AND is_tradable = true
          AND is_excluded = false
        ORDER BY market_cap DESC NULLS LAST
        LIMIT :limit
    """)

    result = await db_session.execute(query, {"limit": limit})
    rows = result.fetchall()

    return [{"symbol": row[0], "name": row[1], "market": row[2]} for row in rows]


@dataclass
class MAOptimizationResult:
    """MA 최적화 결과"""
    short_ma: int
    long_ma: int
    avg_return: float
    avg_win_rate: float
    avg_mdd: float
    total_trades: int
    avg_sharpe: float
    avg_profit_factor: float
    stock_results: list[BacktestResult]
    valid_stock_count: int = 0


def generate_optimization_report(
    optimization_results: list[MAOptimizationResult],
    report_path: str,
) -> str:
    """최적화 리포트 생성"""
    from datetime import datetime as dt

    lines = []
    lines.append("# 골든크로스 MA 파라미터 최적화 리포트")
    lines.append("")
    lines.append(f"> 생성일시: {dt.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # 설정 요약
    lines.append("## 1. 최적화 설정")
    lines.append("")
    lines.append(f"- **단기 MA (고정)**: MA{SHORT_MA_FIXED}")
    lines.append(f"- **장기 MA 후보**: {', '.join(f'MA{ma}' for ma in LONG_MA_CANDIDATES)}")
    lines.append("- **매수 조건**: 골든크로스 활성 + Stochastic K < 30")
    lines.append("- **매도 조건**: 데드크로스 또는 손절(-7%)/익절(+15%)")
    lines.append("")

    # 결과 비교표
    lines.append("## 2. 파라미터별 성과 비교")
    lines.append("")
    lines.append("| 장기MA | 평균 수익률 | 평균 승률 | 평균 MDD | 총 거래 | 평균 Sharpe | 평균 PF |")
    lines.append("|:------:|----------:|----------:|--------:|-------:|-----------:|--------:|")

    # 현재 설정(MA165) 표시
    for res in sorted(optimization_results, key=lambda x: x.long_ma):
        marker = " (현재)" if res.long_ma == 165 else ""
        lines.append(
            f"| MA{res.long_ma}{marker} | {res.avg_return:+.2f}% | {res.avg_win_rate:.1f}% | "
            f"{res.avg_mdd:.2f}% | {res.total_trades} | {res.avg_sharpe:.2f} | {res.avg_profit_factor:.2f} |"
        )

    lines.append("")

    # 최적 파라미터 추천
    lines.append("## 3. 최적 파라미터 추천")
    lines.append("")

    # 승률 기준
    best_by_win_rate = max(optimization_results, key=lambda x: x.avg_win_rate)
    lines.append(f"### 승률 기준 최적")
    lines.append(f"- **MA{SHORT_MA_FIXED}/MA{best_by_win_rate.long_ma}**: 승률 {best_by_win_rate.avg_win_rate:.1f}%")
    lines.append("")

    # 수익률 기준
    best_by_return = max(optimization_results, key=lambda x: x.avg_return)
    lines.append(f"### 수익률 기준 최적")
    lines.append(f"- **MA{SHORT_MA_FIXED}/MA{best_by_return.long_ma}**: 수익률 {best_by_return.avg_return:+.2f}%")
    lines.append("")

    # Sharpe 기준
    best_by_sharpe = max(optimization_results, key=lambda x: x.avg_sharpe)
    lines.append(f"### 리스크 조정 수익률 (Sharpe) 기준 최적")
    lines.append(f"- **MA{SHORT_MA_FIXED}/MA{best_by_sharpe.long_ma}**: Sharpe {best_by_sharpe.avg_sharpe:.2f}")
    lines.append("")

    # MDD 기준
    best_by_mdd = min(optimization_results, key=lambda x: x.avg_mdd)
    lines.append(f"### 리스크 (MDD) 기준 최적")
    lines.append(f"- **MA{SHORT_MA_FIXED}/MA{best_by_mdd.long_ma}**: MDD {best_by_mdd.avg_mdd:.2f}%")
    lines.append("")

    # 종목별 민감도 분석
    lines.append("## 4. 종목별 파라미터 민감도 분석")
    lines.append("")
    lines.append("각 종목이 어떤 MA 설정에서 최고 성과를 보이는지 분석합니다.")
    lines.append("")

    # 종목별 최적 MA 찾기
    stock_best_ma: dict[str, dict] = {}
    for res in optimization_results:
        for stock in res.stock_results:
            if stock.error:
                continue
            key = f"{stock.name} ({stock.symbol})"
            if key not in stock_best_ma:
                stock_best_ma[key] = {
                    "best_return": (res.long_ma, stock.total_return),
                    "best_win_rate": (res.long_ma, stock.win_rate),
                }
            else:
                if stock.total_return > stock_best_ma[key]["best_return"][1]:
                    stock_best_ma[key]["best_return"] = (res.long_ma, stock.total_return)
                if stock.win_rate > stock_best_ma[key]["best_win_rate"][1]:
                    stock_best_ma[key]["best_win_rate"] = (res.long_ma, stock.win_rate)

    lines.append("| 종목 | 최적 장기MA (수익률) | 최고 수익률 | 최적 장기MA (승률) | 최고 승률 |")
    lines.append("|:-----|:--------------------:|------------:|:------------------:|----------:|")

    for stock_name, data in sorted(stock_best_ma.items()):
        ret_ma, ret_val = data["best_return"]
        wr_ma, wr_val = data["best_win_rate"]
        lines.append(f"| {stock_name} | MA{ret_ma} | {ret_val:+.2f}% | MA{wr_ma} | {wr_val:.1f}% |")

    lines.append("")

    # 종목별 상세 결과 (각 MA별)
    lines.append("## 5. 종목별 상세 결과")
    lines.append("")

    # 종목 이름 수집
    stock_names = {}
    for res in optimization_results:
        for stock in res.stock_results:
            if not stock.error:
                stock_names[stock.symbol] = stock.name

    for symbol, name in stock_names.items():
        lines.append(f"### {name} ({symbol})")
        lines.append("")
        lines.append("| 장기MA | 수익률 | 승률 | MDD | 거래수 | Sharpe |")
        lines.append("|:------:|-------:|-----:|----:|-------:|-------:|")

        for res in sorted(optimization_results, key=lambda x: x.long_ma):
            stock = next((s for s in res.stock_results if s.symbol == symbol), None)
            if stock and not stock.error:
                lines.append(
                    f"| MA{res.long_ma} | {stock.total_return:+.2f}% | "
                    f"{stock.win_rate:.1f}% | {stock.mdd:.2f}% | "
                    f"{stock.total_trades} | {stock.sharpe_ratio:.2f} |"
                )

        lines.append("")

    # 결론
    lines.append("## 6. 결론")
    lines.append("")

    # 현재 설정 vs 최적 설정 비교
    current = next((r for r in optimization_results if r.long_ma == 165), None)

    if current and best_by_win_rate.long_ma != 165:
        win_rate_improvement = best_by_win_rate.avg_win_rate - current.avg_win_rate
        lines.append(f"### 승률 개선 가능성")
        if win_rate_improvement > 0:
            lines.append(f"- 현재 MA165 승률: {current.avg_win_rate:.1f}%")
            lines.append(f"- 최적 MA{best_by_win_rate.long_ma} 승률: {best_by_win_rate.avg_win_rate:.1f}%")
            lines.append(f"- **개선 폭: +{win_rate_improvement:.1f}%p**")
        else:
            lines.append("- 현재 MA165 설정이 승률 기준으로 최적이거나 유사합니다.")
        lines.append("")

    if current and best_by_return.long_ma != 165:
        return_improvement = best_by_return.avg_return - current.avg_return
        lines.append(f"### 수익률 개선 가능성")
        if return_improvement > 0:
            lines.append(f"- 현재 MA165 수익률: {current.avg_return:+.2f}%")
            lines.append(f"- 최적 MA{best_by_return.long_ma} 수익률: {best_by_return.avg_return:+.2f}%")
            lines.append(f"- **개선 폭: +{return_improvement:.2f}%p**")
        else:
            lines.append("- 현재 MA165 설정이 수익률 기준으로 최적이거나 유사합니다.")
        lines.append("")

    lines.append("### 권장 사항")
    lines.append("")

    # 종합 추천
    if best_by_win_rate.long_ma == best_by_return.long_ma:
        lines.append(f"- 승률과 수익률 모두 **MA{SHORT_MA_FIXED}/MA{best_by_win_rate.long_ma}**에서 최적입니다.")
    else:
        lines.append(f"- 승률 중시: **MA{SHORT_MA_FIXED}/MA{best_by_win_rate.long_ma}** 권장")
        lines.append(f"- 수익률 중시: **MA{SHORT_MA_FIXED}/MA{best_by_return.long_ma}** 권장")

    if best_by_sharpe.long_ma != best_by_win_rate.long_ma and best_by_sharpe.long_ma != best_by_return.long_ma:
        lines.append(f"- 리스크 조정 수익률 중시: **MA{SHORT_MA_FIXED}/MA{best_by_sharpe.long_ma}** 권장")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*이 리포트는 자동 생성되었습니다. 투자 결정은 본인의 판단하에 이루어져야 합니다.*")

    report_content = "\n".join(lines)

    # 파일 저장
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    return report_content


async def run_backtest_for_long_ma(
    long_ma: int,
    stocks: list[dict],
    data_loader: BacktestDataLoader,
    start_date: datetime,
    end_date: datetime,
) -> MAOptimizationResult:
    """특정 장기 MA 설정으로 백테스트 실행"""

    strategy_config = GoldenCrossConfig(
        short_ma_period=SHORT_MA_FIXED,
        long_ma_period=long_ma,
    )
    backtest_config = BacktestConfig()
    backtester = GoldenCrossBacktester(strategy_config, backtest_config)

    results: list[BacktestResult] = []

    for stock in stocks:
        symbol = stock["symbol"]
        name = stock["name"] or symbol

        try:
            # 데이터 로드
            df, actual_start, actual_end = await data_loader.load_ohlcv_data(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                chunk_days=90,
                use_cache=True,
            )

            # 백테스트 실행
            result = await backtester.run(
                symbol=symbol,
                name=name,
                df=df,
                start_date=actual_start,
                end_date=actual_end,
            )
            results.append(result)

        except Exception as e:
            results.append(BacktestResult(
                symbol=symbol,
                name=name,
                start_date=start_date,
                end_date=end_date,
                initial_capital=backtest_config.initial_capital,
                final_capital=backtest_config.initial_capital,
                total_return=0.0,
                annualized_return=0.0,
                mdd=0.0,
                mdd_start_date=None,
                mdd_end_date=None,
                sharpe_ratio=0.0,
                win_rate=0.0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                avg_profit=0.0,
                avg_loss=0.0,
                profit_factor=0.0,
                avg_holding_days=0.0,
                max_consecutive_wins=0,
                max_consecutive_losses=0,
                error=str(e),
            ))

    # 결과 집계
    valid_results = [r for r in results if r.error is None]

    if valid_results:
        avg_return = sum(r.total_return for r in valid_results) / len(valid_results)
        avg_win_rate = sum(r.win_rate for r in valid_results) / len(valid_results)
        avg_mdd = sum(r.mdd for r in valid_results) / len(valid_results)
        total_trades = sum(r.total_trades for r in valid_results)
        avg_sharpe = sum(r.sharpe_ratio for r in valid_results) / len(valid_results)
        avg_pf = sum(r.profit_factor for r in valid_results if r.profit_factor != float("inf")) / len(valid_results) if valid_results else 0.0
    else:
        avg_return = 0.0
        avg_win_rate = 0.0
        avg_mdd = 0.0
        total_trades = 0
        avg_sharpe = 0.0
        avg_pf = 0.0

    return MAOptimizationResult(
        short_ma=SHORT_MA_FIXED,
        long_ma=long_ma,
        avg_return=avg_return,
        avg_win_rate=avg_win_rate,
        avg_mdd=avg_mdd,
        total_trades=total_trades,
        avg_sharpe=avg_sharpe,
        avg_profit_factor=avg_pf,
        stock_results=results,
        valid_stock_count=len(valid_results),
    )


async def main():
    """메인 실행 함수"""
    print("=" * 80)
    print("📊 골든크로스 MA 파라미터 최적화 (장기 MA)")
    print("=" * 80)
    print(f"\n테스트 파라미터: MA{SHORT_MA_FIXED} (고정) / MA{LONG_MA_CANDIDATES[0]}~MA{LONG_MA_CANDIDATES[-1]} (5단위)")
    print(f"테스트 종목 수: {TEST_STOCK_COUNT}개 (시가총액 상위)")

    # 1. 의존성 초기화
    kis_client = KISAPIClient()
    redis_client = await get_redis_client()

    # 2. DB 세션 생성
    db_gen = get_db()
    db_session = await db_gen.__anext__()

    try:
        # 3. stock_universe에서 시가총액 상위 종목 조회
        print(f"\n📋 stock_universe 종목 조회 (상위 {TEST_STOCK_COUNT}개)...")
        stocks = await get_stock_universe_symbols(db_session, limit=TEST_STOCK_COUNT)

        if not stocks:
            print("❌ 활성 종목이 없습니다.")
            return

        print(f"✅ {len(stocks)}개 종목 조회됨:")
        for i, s in enumerate(stocks[:10], 1):
            print(f"   {i}. {s['name']} ({s['symbol']}) [{s['market']}]")
        if len(stocks) > 10:
            print(f"   ... 외 {len(stocks) - 10}개")

        # 4. 서비스 초기화
        market_data_service = MarketDataService(kis_client, redis_client)
        data_loader = BacktestDataLoader(market_data_service, db_session)

        # 5. 기간 설정 (2년)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=730)

        print(f"\n📅 백테스트 기간: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")
        print("=" * 80)

        # 6. 각 장기 MA 설정별 백테스트 실행
        optimization_results: list[MAOptimizationResult] = []

        for idx, long_ma in enumerate(LONG_MA_CANDIDATES, 1):
            print(f"\n[{idx}/{len(LONG_MA_CANDIDATES)}] MA{SHORT_MA_FIXED}/MA{long_ma} 테스트 중...")

            result = await run_backtest_for_long_ma(
                long_ma=long_ma,
                stocks=stocks,
                data_loader=data_loader,
                start_date=start_date,
                end_date=end_date,
            )

            optimization_results.append(result)

            marker = " (현재 설정)" if long_ma == 165 else ""
            print(f"   ✅ MA{SHORT_MA_FIXED}/MA{long_ma}{marker}")
            print(f"      - 평균 수익률: {result.avg_return:+.2f}%")
            print(f"      - 평균 승률: {result.avg_win_rate:.1f}%")
            print(f"      - 평균 MDD: {result.avg_mdd:.2f}%")
            print(f"      - 총 거래: {result.total_trades}회")

        # 7. 결과 요약 출력
        print("\n" + "=" * 80)
        print("📊 파라미터 비교 결과")
        print("=" * 80)

        print(f"\n{'장기MA':<10} {'수익률':>10} {'승률':>8} {'MDD':>8} {'거래수':>8} {'Sharpe':>8}")
        print("-" * 60)

        for res in sorted(optimization_results, key=lambda x: x.long_ma):
            marker = " *" if res.long_ma == 165 else ""
            print(
                f"MA{res.long_ma:<7}{marker} {res.avg_return:>+9.2f}% "
                f"{res.avg_win_rate:>7.1f}% {res.avg_mdd:>7.2f}% "
                f"{res.total_trades:>8} {res.avg_sharpe:>7.2f}"
            )

        print("-" * 60)
        print("* = 현재 설정 (MA55/MA165)")

        # 8. 최적 파라미터 출력
        print("\n" + "=" * 80)
        print("🎯 최적 파라미터")
        print("=" * 80)

        best_win_rate = max(optimization_results, key=lambda x: x.avg_win_rate)
        best_return = max(optimization_results, key=lambda x: x.avg_return)
        best_sharpe = max(optimization_results, key=lambda x: x.avg_sharpe)

        print(f"\n✅ 승률 최고: MA{SHORT_MA_FIXED}/MA{best_win_rate.long_ma} ({best_win_rate.avg_win_rate:.1f}%)")
        print(f"✅ 수익률 최고: MA{SHORT_MA_FIXED}/MA{best_return.long_ma} ({best_return.avg_return:+.2f}%)")
        print(f"✅ Sharpe 최고: MA{SHORT_MA_FIXED}/MA{best_sharpe.long_ma} ({best_sharpe.avg_sharpe:.2f})")

        # 9. 리포트 생성
        import os
        os.makedirs("reports", exist_ok=True)
        report_path = "reports/golden_cross_ma_optimization_report.md"

        print(f"\n📝 리포트 생성 중...")
        generate_optimization_report(optimization_results, report_path)
        print(f"✅ 리포트 저장됨: {report_path}")

        # 10. DB 커밋 및 정리
        await db_session.commit()
        await redis_client.disconnect()

        print("\n" + "=" * 80)
        print("🎉 최적화 완료!")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db_session.close()


if __name__ == "__main__":
    asyncio.run(main())
