# -*- coding: utf-8 -*-
"""
다중 종목 백테스팅 예제

여러 종목에 대해 동일한 전략으로 백테스팅을 수행하고 결과를 비교합니다.
"""

import asyncio
from datetime import datetime
from decimal import Decimal

from src.adapters.cache.redis_client import get_redis_client
from src.adapters.external.kis_api.client import KISAPIClient
from src.application.domain.backtest.dto import (
    BacktestConfigDTO,
    MultiSymbolBacktestRequestDTO,
)
from src.application.domain.backtest.service import BacktestService
from src.application.domain.market_data.service import MarketDataService
from src.application.domain.strategy.dto import (
    BollingerBandConfig,
    EnvelopeConfig,
    PositionConfig,
    RiskManagementConfig,
    StrategyConfigDTO,
)
from src.settings.config import settings


async def main():
    """메인 실행 함수"""
    print("=" * 80)
    print("📊 다중 종목 백테스팅 예제")
    print("=" * 80)

    # 1. 의존성 초기화
    kis_client = KISAPIClient(
        app_key=settings.kis_app_key,
        app_secret=settings.kis_app_secret,
        base_url=settings.kis_base_url
    )
    redis_client = await get_redis_client()

    # 2. 서비스 초기화
    market_data_service = MarketDataService(kis_client, redis_client)
    backtest_service = BacktestService(market_data_service)

    # 3. 전략 설정
    strategy_config = StrategyConfigDTO(
        bollinger_band=BollingerBandConfig(
            period=20,
            std_multiplier=2.0
        ),
        envelope=EnvelopeConfig(
            period=20,
            percentage=2.0
        ),
        position=PositionConfig(
            allocation_ratio=0.1,
            max_position_count=1
        ),
        risk_management=RiskManagementConfig(
            use_stop_loss=True,
            stop_loss_ratio=-0.03,
            use_take_profit=True,
            take_profit_ratio=0.05,
            use_trailing_stop=False,
            use_reverse_signal_exit=True
        )
    )

    # 4. 백테스팅 설정
    backtest_config = BacktestConfigDTO(
        initial_capital=Decimal("10_000_000"),
        commission_rate=0.00015,
        tax_rate=0.0023,
        slippage_rate=0.0005,
        use_commission=True,
        use_tax=True,
        use_slippage=True
    )

    # 5. 다중 종목 백테스팅 요청
    symbols = [
        "005930",  # 삼성전자
        "000660",  # SK하이닉스
        "035420",  # NAVER
        "051910",  # LG화학
    ]

    request = MultiSymbolBacktestRequestDTO(
        symbols=symbols,
        start_date=datetime(2023, 1, 1),
        end_date=datetime(2024, 12, 31),
        strategy_config=strategy_config,
        backtest_config=backtest_config
    )

    # 6. 백테스팅 실행
    print(f"\n🚀 다중 종목 백테스팅 시작...")
    print(f"  - 종목 수: {len(symbols)}개")
    print(f"  - 기간: {request.start_date.date()} ~ {request.end_date.date()}")
    print(f"  - 초기 자본: {request.backtest_config.initial_capital:,.0f}원")
    print()

    multi_result = await backtest_service.run_multi_symbol_backtest(request)

    # 7. 결과 비교 출력
    print("\n" + "=" * 80)
    print("📊 종목별 성과 비교")
    print("=" * 80)

    # 테이블 헤더
    print(f"\n{'종목':^10} {'수익률':>10} {'MDD':>10} {'Sharpe':>10} {'승률':>10} {'거래수':>10} {'등급':>10}")
    print("-" * 80)

    # 종목별 결과 출력
    for symbol, result in multi_result.results.items():
        grade = backtest_service.get_strategy_performance_grade(result)
        print(
            f"{symbol:^10} "
            f"{result.total_return:>9.2f}% "
            f"{result.mdd:>9.2f}% "
            f"{result.sharpe_ratio:>10.2f} "
            f"{result.win_rate:>9.1f}% "
            f"{result.total_trades:>10} "
            f"{grade:>10}"
        )

    # 8. 최고/최저 성과 종목
    if multi_result.results:
        best_symbol = max(
            multi_result.results.items(),
            key=lambda x: x[1].total_return
        )
        worst_symbol = min(
            multi_result.results.items(),
            key=lambda x: x[1].total_return
        )

        print("\n" + "=" * 80)
        print(f"🏆 최고 성과: {best_symbol[0]} ({best_symbol[1].total_return:.2f}%)")
        print(f"📉 최저 성과: {worst_symbol[0]} ({worst_symbol[1].total_return:.2f}%)")

    # 9. 요약 통계
    print("\n" + "=" * 80)
    print("📈 전체 요약")
    print("=" * 80)
    print(f"  - 전체 종목: {multi_result.total_count}개")
    print(f"  - 성공: {multi_result.success_count}개")
    print(f"  - 실패: {multi_result.failed_count}개")

    if multi_result.results:
        avg_return = sum(r.total_return for r in multi_result.results.values()) / len(multi_result.results)
        avg_sharpe = sum(r.sharpe_ratio for r in multi_result.results.values()) / len(multi_result.results)
        print(f"  - 평균 수익률: {avg_return:.2f}%")
        print(f"  - 평균 Sharpe Ratio: {avg_sharpe:.2f}")

    # 10. 리소스 정리
    await redis_client.disconnect()

    print("\n✅ 다중 종목 백테스팅 예제 완료!")


if __name__ == "__main__":
    asyncio.run(main())
