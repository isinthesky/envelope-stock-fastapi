# -*- coding: utf-8 -*-
"""
전략 비교 테스트 - 승률 개선을 위한 여러 전략 비교
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


async def test_strategy(
    backtest_service,
    strategy_name: str,
    strategy_config: StrategyConfigDTO,
    backtest_config: BacktestConfigDTO,
):
    """전략 테스트 및 결과 반환"""
    print(f"\n{'=' * 80}")
    print(f"📈 {strategy_name}")
    print(f"{'=' * 80}")

    request = BacktestRequestDTO(
        symbol="005930",
        start_date=datetime(2023, 1, 1),
        end_date=datetime(2024, 12, 31),
        strategy_config=strategy_config,
        backtest_config=backtest_config
    )

    result = await backtest_service.run_backtest(request)

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

    print(f"\n📊 성과:")
    print(f"  총 수익률: {result.total_return:+.2f}% | MDD: {result.mdd:.2f}%")
    print(f"  거래: {result.total_trades}회 | 승률: {result.win_rate:.1f}%")
    print(f"  평균 수익: {result.avg_win:+.2f}% | 평균 손실: {result.avg_loss:.2f}%")
    print(f"  Profit Factor: {result.profit_factor:.2f} | Sharpe: {result.sharpe_ratio:.2f}")

    print(f"\n  종료 사유:")
    for reason, stats in exit_reasons.items():
        wr = (stats["wins"] / stats["count"] * 100) if stats["count"] > 0 else 0
        print(f"    {reason:20s}: {stats['count']:2d}회 (승률: {wr:5.1f}%)")

    return {
        "name": strategy_name,
        "result": result,
        "exit_reasons": exit_reasons,
    }


async def main():
    """전략 비교 메인"""
    print("=" * 80)
    print("🔬 매매 전략 비교 테스트")
    print("=" * 80)

    # 의존성 초기화
    kis_client = KISAPIClient()
    redis_client = await get_redis_client()
    db_gen = get_db()
    db_session = await db_gen.__anext__()

    try:
        market_data_service = MarketDataService(kis_client, redis_client)
        backtest_service = BacktestService(market_data_service, db_session)

        backtest_config = BacktestConfigDTO(
            initial_capital=Decimal("10_000_000"),
            use_commission=True,
            use_tax=True,
            use_slippage=True
        )

        results = []

        # ==================== 전략 1: 기존 (엄격 모드, 손절 -3%) ====================
        strategy1 = StrategyConfigDTO(
            bollinger_band=BollingerBandConfig(period=20, std_multiplier=2.0),
            envelope=EnvelopeConfig(period=20, percentage=2.0),
            position=PositionConfig(allocation_ratio=0.1, max_position_count=1),
            risk_management=RiskManagementConfig(
                use_stop_loss=True,
                stop_loss_ratio=-0.03,  # -3%
                use_take_profit=True,
                take_profit_ratio=0.05,  # +5%
                use_trailing_stop=False,
                use_reverse_signal_exit=True
            )
        )
        results.append(await test_strategy(
            backtest_service,
            "전략 1: 기존 (엄격, 손절 -3%)",
            strategy1,
            backtest_config
        ))

        # ==================== 전략 2: 손절 완화 (-5%) ====================
        strategy2 = StrategyConfigDTO(
            bollinger_band=BollingerBandConfig(period=20, std_multiplier=2.0),
            envelope=EnvelopeConfig(period=20, percentage=2.0),
            position=PositionConfig(allocation_ratio=0.1, max_position_count=1),
            risk_management=RiskManagementConfig(
                use_stop_loss=True,
                stop_loss_ratio=-0.05,  # -5% (완화)
                use_take_profit=True,
                take_profit_ratio=0.05,
                use_trailing_stop=False,
                use_reverse_signal_exit=True
            )
        )
        results.append(await test_strategy(
            backtest_service,
            "전략 2: 손절 완화 (엄격, 손절 -5%)",
            strategy2,
            backtest_config
        ))

        # ==================== 전략 3: 익절 강화 (+3%) ====================
        strategy3 = StrategyConfigDTO(
            bollinger_band=BollingerBandConfig(period=20, std_multiplier=2.0),
            envelope=EnvelopeConfig(period=20, percentage=2.0),
            position=PositionConfig(allocation_ratio=0.1, max_position_count=1),
            risk_management=RiskManagementConfig(
                use_stop_loss=True,
                stop_loss_ratio=-0.05,  # -5%
                use_take_profit=True,
                take_profit_ratio=0.03,  # +3% (빠른 수익 실현)
                use_trailing_stop=False,
                use_reverse_signal_exit=True
            )
        )
        results.append(await test_strategy(
            backtest_service,
            "전략 3: 익절 강화 (손절 -5%, 익절 +3%)",
            strategy3,
            backtest_config
        ))

        # ==================== 전략 4: 트레일링 스탑 활성화 ====================
        strategy4 = StrategyConfigDTO(
            bollinger_band=BollingerBandConfig(period=20, std_multiplier=2.0),
            envelope=EnvelopeConfig(period=20, percentage=2.0),
            position=PositionConfig(allocation_ratio=0.1, max_position_count=1),
            risk_management=RiskManagementConfig(
                use_stop_loss=True,
                stop_loss_ratio=-0.05,
                use_take_profit=True,
                take_profit_ratio=0.05,
                use_trailing_stop=True,  # 트레일링 활성화
                trailing_stop_ratio=0.02,  # 2% 하락 시
                use_reverse_signal_exit=True
            )
        )
        results.append(await test_strategy(
            backtest_service,
            "전략 4: 트레일링 스탑 (손절 -5%, 트레일링 -2%)",
            strategy4,
            backtest_config
        ))

        # ==================== 비교 결과 ====================
        print(f"\n\n{'=' * 80}")
        print(f"📊 전략 비교 결과")
        print(f"{'=' * 80}\n")

        print(f"{'전략':^30} {'수익률':>10} {'승률':>8} {'거래':>6} {'PF':>6} {'Sharpe':>8} {'MDD':>8}")
        print("-" * 80)

        for r in results:
            result = r["result"]
            print(
                f"{r['name'][:28]:30} "
                f"{result.total_return:>9.2f}% "
                f"{result.win_rate:>7.1f}% "
                f"{result.total_trades:>5d}회 "
                f"{result.profit_factor:>6.2f} "
                f"{result.sharpe_ratio:>8.2f} "
                f"{result.mdd:>7.2f}%"
            )

        # 최고 성과 전략
        best_by_return = max(results, key=lambda x: x["result"].total_return)
        best_by_winrate = max(results, key=lambda x: x["result"].win_rate)
        best_by_sharpe = max(results, key=lambda x: x["result"].sharpe_ratio)

        print(f"\n{'=' * 80}")
        print(f"🏆 최고 성과")
        print(f"{'=' * 80}")
        print(f"  최고 수익률: {best_by_return['name']} ({best_by_return['result'].total_return:+.2f}%)")
        print(f"  최고 승률:   {best_by_winrate['name']} ({best_by_winrate['result'].win_rate:.1f}%)")
        print(f"  최고 Sharpe: {best_by_sharpe['name']} ({best_by_sharpe['result'].sharpe_ratio:.2f})")

        await db_session.commit()
        await redis_client.disconnect()

    finally:
        await db_session.close()


if __name__ == "__main__":
    asyncio.run(main())
