# -*- coding: utf-8 -*-
"""
전략 최적화 - 승률 개선을 위한 근본적 전략 변경
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
    strategy_desc: str,
    strategy_config: StrategyConfigDTO,
    backtest_config: BacktestConfigDTO,
):
    """전략 테스트"""
    print(f"\n{'=' * 80}")
    print(f"📈 {strategy_name}")
    print(f"{'=' * 80}")
    print(f"  {strategy_desc}")

    request = BacktestRequestDTO(
        symbol="005930",
        start_date=datetime(2023, 1, 1),
        end_date=datetime(2024, 12, 31),
        strategy_config=strategy_config,
        backtest_config=backtest_config
    )

    result = await backtest_service.run_backtest(request)

    # 종료 사유
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
    print(f"  수익률: {result.total_return:+.2f}% | MDD: {result.mdd:.2f}% | Sharpe: {result.sharpe_ratio:.2f}")
    print(f"  거래: {result.total_trades}회 | 승률: {result.win_rate:.1f}% | PF: {result.profit_factor:.2f}")
    print(f"  평균 수익: {result.avg_win:+.2f}% | 평균 손실: {result.avg_loss:.2f}%")

    if exit_reasons:
        print(f"  종료 사유:")
        for reason, stats in sorted(exit_reasons.items(), key=lambda x: -x[1]['count']):
            wr = (stats["wins"] / stats["count"] * 100) if stats["count"] > 0 else 0
            print(f"    {reason:20s}: {stats['count']:2d}회 (승률: {wr:5.1f}%)")

    return {
        "name": strategy_name,
        "desc": strategy_desc,
        "result": result,
    }


async def main():
    """전략 최적화 메인"""
    print("=" * 80)
    print("🎯 매매 전략 최적화 - 승률 개선")
    print("=" * 80)

    kis_client = KISAPIClient()
    redis_client = await get_redis_client()
    db_gen = get_db()
    db_session = await db_gen.__anext__()

    try:
        market_data_service = MarketDataService(kis_client, redis_client)
        backtest_service = BacktestService(market_data_service, db_session)

        backtest_config = BacktestConfigDTO(
            initial_capital=Decimal("10_000_000"),
            commission_rate=0.00015,
            tax_rate=0.0023,
            slippage_rate=0.0005,
            use_commission=True,
            use_tax=True,
            use_slippage=True
        )

        results = []

        # ==================== 전략 A: 기존 엄격 모드 (기준선) ====================
        strategy_a = StrategyConfigDTO(
            bollinger_band=BollingerBandConfig(period=20, std_multiplier=2.0),
            envelope=EnvelopeConfig(period=20, percentage=2.0),
            position=PositionConfig(allocation_ratio=0.1, max_position_count=1),
            risk_management=RiskManagementConfig(
                use_stop_loss=True, stop_loss_ratio=-0.03,
                use_take_profit=True, take_profit_ratio=0.05,
                use_trailing_stop=False,
                use_reverse_signal_exit=True
            )
        )
        results.append(await test_strategy(
            backtest_service,
            "전략 A: 기존 (엄격 모드)",
            "BB(20,2.0) + ENV(20,2.0%), 손절 -3%, 익절 +5%",
            strategy_a, backtest_config
        ))

        # ==================== 전략 B: 완화 모드 ====================
        # 주의: 완화 모드는 코드 수정이 필요 (현재 미지원)
        # 대신 더 공격적인 파라미터 사용

        # ==================== 전략 C: 볼린저 밴드 확장 (2.5 std) ====================
        strategy_c = StrategyConfigDTO(
            bollinger_band=BollingerBandConfig(period=20, std_multiplier=2.5),  # 확장
            envelope=EnvelopeConfig(period=20, percentage=2.5),  # 확장
            position=PositionConfig(allocation_ratio=0.1, max_position_count=1),
            risk_management=RiskManagementConfig(
                use_stop_loss=True, stop_loss_ratio=-0.04,  # 완화
                use_take_profit=True, take_profit_ratio=0.04,  # 완화
                use_trailing_stop=False,
                use_reverse_signal_exit=True
            )
        )
        results.append(await test_strategy(
            backtest_service,
            "전략 C: 지표 확장",
            "BB(20,2.5) + ENV(20,2.5%), 손절 -4%, 익절 +4%",
            strategy_c, backtest_config
        ))

        # ==================== 전략 D: 짧은 기간 (10일) ====================
        strategy_d = StrategyConfigDTO(
            bollinger_band=BollingerBandConfig(period=10, std_multiplier=2.0),
            envelope=EnvelopeConfig(period=10, percentage=2.0),
            position=PositionConfig(allocation_ratio=0.1, max_position_count=1),
            risk_management=RiskManagementConfig(
                use_stop_loss=True, stop_loss_ratio=-0.04,
                use_take_profit=True, take_profit_ratio=0.04,
                use_trailing_stop=False,
                use_reverse_signal_exit=True
            )
        )
        results.append(await test_strategy(
            backtest_service,
            "전략 D: 짧은 기간",
            "BB(10,2.0) + ENV(10,2.0%), 손절 -4%, 익절 +4%",
            strategy_d, backtest_config
        ))

        # ==================== 전략 E: 긴 기간 (30일) ====================
        strategy_e = StrategyConfigDTO(
            bollinger_band=BollingerBandConfig(period=30, std_multiplier=2.0),
            envelope=EnvelopeConfig(period=30, percentage=2.0),
            position=PositionConfig(allocation_ratio=0.1, max_position_count=1),
            risk_management=RiskManagementConfig(
                use_stop_loss=True, stop_loss_ratio=-0.04,
                use_take_profit=True, take_profit_ratio=0.04,
                use_trailing_stop=False,
                use_reverse_signal_exit=True
            )
        )
        results.append(await test_strategy(
            backtest_service,
            "전략 E: 긴 기간",
            "BB(30,2.0) + ENV(30,2.0%), 손절 -4%, 익절 +4%",
            strategy_e, backtest_config
        ))

        # ==================== 전략 F: 트레일링 스탑 최적화 ====================
        strategy_f = StrategyConfigDTO(
            bollinger_band=BollingerBandConfig(period=20, std_multiplier=2.0),
            envelope=EnvelopeConfig(period=20, percentage=2.0),
            position=PositionConfig(allocation_ratio=0.15, max_position_count=1),  # 포지션 확대
            risk_management=RiskManagementConfig(
                use_stop_loss=True, stop_loss_ratio=-0.06,  # 여유 있게
                use_take_profit=False,  # 익절 제거
                use_trailing_stop=True,  # 트레일링 활용
                trailing_stop_ratio=0.03,  # 3% 하락 시
                use_reverse_signal_exit=True
            )
        )
        results.append(await test_strategy(
            backtest_service,
            "전략 F: 트레일링 중심",
            "BB(20,2.0) + ENV(20,2.0%), 손절 -6%, 트레일링 -3%, 포지션 15%",
            strategy_f, backtest_config
        ))

        # ==================== 비교 결과 ====================
        print(f"\n\n{'=' * 80}")
        print(f"📊 전략 최적화 결과")
        print(f"{'=' * 80}\n")

        print(f"{'전략':^22} {'수익률':>10} {'승률':>8} {'거래':>6} {'PF':>6} {'Sharpe':>8} {'등급':>6}")
        print("-" * 80)

        for r in results:
            result = r["result"]
            grade = backtest_service.get_strategy_performance_grade(result)
            print(
                f"{r['name'][:20]:22} "
                f"{result.total_return:>9.2f}% "
                f"{result.win_rate:>7.1f}% "
                f"{result.total_trades:>5d}회 "
                f"{result.profit_factor:>6.2f} "
                f"{result.sharpe_ratio:>8.2f} "
                f"{grade:>6}"
            )

        # 최고 성과
        best_by_return = max(results, key=lambda x: x["result"].total_return)
        best_by_winrate = max(results, key=lambda x: x["result"].win_rate)

        print(f"\n{'=' * 80}")
        print(f"🏆 권장 전략")
        print(f"{'=' * 80}")
        print(f"\n✅ 최고 수익률: {best_by_return['name']}")
        print(f"   {best_by_return['desc']}")
        print(f"   수익률: {best_by_return['result'].total_return:+.2f}% | "
              f"승률: {best_by_return['result'].win_rate:.1f}% | "
              f"거래: {best_by_return['result'].total_trades}회")

        print(f"\n✅ 최고 승률: {best_by_winrate['name']}")
        print(f"   {best_by_winrate['desc']}")
        print(f"   수익률: {best_by_winrate['result'].total_return:+.2f}% | "
              f"승률: {best_by_winrate['result'].win_rate:.1f}% | "
              f"거래: {best_by_winrate['result'].total_trades}회")

        await db_session.commit()
        await redis_client.disconnect()

    finally:
        await db_session.close()


if __name__ == "__main__":
    asyncio.run(main())
