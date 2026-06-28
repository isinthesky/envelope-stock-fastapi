# -*- coding: utf-8 -*-
"""
최적화된 백테스팅 예제 - 전략 F (트레일링 중심)

승률: 33.3% → 수익률: +2.04%로 개선된 전략
"""

import asyncio
from datetime import datetime
from decimal import Decimal

from src.adapters.cache.redis_client import get_redis_client
from src.adapters.database.connection import get_db
from src.adapters.external.kis_api.client import KISAPIClient
from src.application.domain.backtest.dto import (
    BacktestConfigDTO,
    BacktestRequestDTO,
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


async def main():
    """메인 실행 함수"""
    print("=" * 80)
    print("📊 최적화된 백테스팅 - 삼성전자 (트레일링 중심 전략)")
    print("=" * 80)

    # 의존성 초기화
    kis_client = KISAPIClient()
    redis_client = await get_redis_client()
    db_gen = get_db()
    db_session = await db_gen.__anext__()

    try:
        market_data_service = MarketDataService(kis_client, redis_client)
        backtest_service = BacktestService(market_data_service, db_session)

        # ==================== 최적화된 전략 설정 ====================
        print("\n🎯 전략 설정:")
        print("  - 볼린저 밴드: 20일, 표준편차 2.0")
        print("  - 엔벨로프: 20일, 2.0%")
        print("  - 손절: -6% (여유 있게)")
        print("  - 익절: 사용 안 함 (트레일링으로 대체)")
        print("  - 트레일링 스탑: -3% (고점 대비)")
        print("  - 포지션 크기: 15%")
        print("  - 역신호 청산: 활성화")

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
                allocation_ratio=0.15,  # 15% 포지션 (기존 10% → 15%)
                max_position_count=1
            ),
            risk_management=RiskManagementConfig(
                use_stop_loss=True,
                stop_loss_ratio=-0.06,  # -6% 손절 (기존 -3% → -6%)
                use_take_profit=False,   # 익절 사용 안 함 (트레일링으로 대체)
                use_trailing_stop=True,  # 트레일링 활성화
                trailing_stop_ratio=0.03,  # 고점 대비 -3% 하락 시
                use_reverse_signal_exit=True
            )
        )

        backtest_config = BacktestConfigDTO(
            initial_capital=Decimal("10_000_000"),
            use_commission=True,
            use_tax=True,
            use_slippage=True
        )

        request = BacktestRequestDTO(
            symbol="005930",
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 12, 31),
            strategy_config=strategy_config,
            backtest_config=backtest_config
        )

        # 백테스팅 실행
        print("\n🚀 백테스팅 시작...")
        print(f"  - 종목: {request.symbol} (삼성전자)")
        print(f"  - 기간: {request.start_date.date()} ~ {request.end_date.date()}")
        print(f"  - 초기 자본: {request.backtest_config.initial_capital:,.0f}원")
        print()

        result = await backtest_service.run_backtest(request)

        # 결과 출력
        backtest_service.print_result_summary(result)

        # 성과 등급
        grade = backtest_service.get_strategy_performance_grade(result)
        print(f"\n🎯 전략 성과 등급: {grade}")

        # 기존 전략과 비교
        print(f"\n📊 기존 전략 대비 개선 효과:")
        print(f"{'':20} {'기존 전략':>15} {'최적화 전략':>15} {'개선':>10}")
        print("-" * 65)
        print(f"{'총 수익률':20} {'-0.54%':>15} {f'{result.total_return:+.2f}%':>15} {f'{result.total_return + 0.54:+.2f}%p':>10}")
        print(f"{'Profit Factor':20} {'0.78':>15} {f'{result.profit_factor:.2f}':>15} {f'{(result.profit_factor - 0.78) / 0.78 * 100:+.0f}%':>10}")
        print(f"{'평균 수익':20} {'+2.82%':>15} {f'{result.avg_win:+.2f}%':>15} {f'{result.avg_win - 2.82:+.2f}%p':>10}")
        print(f"{'등급':20} {'D':>15} {grade:>15} {'개선':>10}")

        # 종료 사유 분석
        exit_reasons = {}
        for trade in result.trades:
            if trade.exit_date:
                reason = trade.exit_reason
                if reason not in exit_reasons:
                    exit_reasons[reason] = {"count": 0, "wins": 0}
                exit_reasons[reason]["count"] += 1
                if trade.profit_rate > 0:
                    exit_reasons[reason]["wins"] += 1

        print(f"\n📋 거래 종료 사유:")
        for reason, stats in sorted(exit_reasons.items(), key=lambda x: -x[1]['count']):
            win_rate = (stats["wins"] / stats["count"] * 100) if stats["count"] > 0 else 0
            status = "✅" if win_rate >= 50 else "⚠️" if win_rate > 0 else "❌"
            print(f"  {status} {reason:20s}: {stats['count']:2d}회 (승률: {win_rate:5.1f}%)")

        # 리소스 정리
        await db_session.commit()
        await redis_client.disconnect()

        print("\n✅ 최적화된 백테스팅 완료!")

    finally:
        await db_session.close()


if __name__ == "__main__":
    asyncio.run(main())
