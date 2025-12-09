# -*- coding: utf-8 -*-
"""
전략 분석 스크립트 - 현재 전략의 상세 성과 분석
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
    """전략 분석 메인"""
    print("=" * 80)
    print("📊 매매 전략 상세 분석")
    print("=" * 80)

    # 1. 의존성 초기화
    from src.adapters.database.connection import get_db

    kis_client = KISAPIClient()
    redis_client = await get_redis_client()
    db_gen = get_db()
    db_session = await db_gen.__anext__()

    try:
        market_data_service = MarketDataService(kis_client, redis_client)
        backtest_service = BacktestService(market_data_service, db_session)

        # 2. 기본 설정
        backtest_config = BacktestConfigDTO(
            initial_capital=Decimal("10_000_000"),
            commission_rate=0.00015,
            tax_rate=0.0023,
            slippage_rate=0.0005,
            use_commission=True,
            use_tax=True,
            use_slippage=True
        )

        # 3. 현재 전략 (엄격 모드)
        print("\n" + "=" * 80)
        print("📈 전략 1: 볼린저 밴드 + 엔벨로프 (엄격 모드)")
        print("=" * 80)
        print("  - 진입: 두 지표 모두 과매도/과매수 신호")
        print("  - 손절: -3%, 익절: +5%")
        print()

        strategy_strict = StrategyConfigDTO(
            bollinger_band=BollingerBandConfig(period=20, std_multiplier=2.0),
            envelope=EnvelopeConfig(period=20, percentage=2.0),
            position=PositionConfig(allocation_ratio=0.1, max_position_count=1),
            risk_management=RiskManagementConfig(
                use_stop_loss=True,
                stop_loss_ratio=-0.03,
                use_take_profit=True,
                take_profit_ratio=0.05,
                use_trailing_stop=False,
                use_reverse_signal_exit=True
            )
        )

        request = BacktestRequestDTO(
            symbol="005930",
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 12, 31),
            strategy_config=strategy_strict,
            backtest_config=backtest_config
        )

        result_strict = await backtest_service.run_backtest(request)

        print("\n📊 성과 요약:")
        print(f"  - 총 수익률: {result_strict.total_return:.2f}%")
        print(f"  - 연환산 수익률: {result_strict.annualized_return:.2f}%")
        print(f"  - MDD: {result_strict.mdd:.2f}%")
        print(f"  - Sharpe Ratio: {result_strict.sharpe_ratio:.2f}")
        print(f"  - 총 거래: {result_strict.total_trades}회")
        print(f"  - 승률: {result_strict.win_rate:.1f}%")
        print(f"  - Profit Factor: {result_strict.profit_factor:.2f}")
        print(f"  - 평균 수익: {result_strict.avg_win:.2f}%")
        print(f"  - 평균 손실: {result_strict.avg_loss:.2f}%")

        # 4. 거래 분석
        print("\n" + "=" * 80)
        print("📜 거래 내역 분석")
        print("=" * 80)

        wins = [t for t in result_strict.trades if t.exit_date and t.profit_rate > 0]
        losses = [t for t in result_strict.trades if t.exit_date and t.profit_rate < 0]

        print(f"\n✅ 수익 거래: {len(wins)}회")
        if wins:
            print("  상위 3건:")
            for trade in sorted(wins, key=lambda x: x.profit_rate, reverse=True)[:3]:
                print(f"    [{trade.entry_date.date()}] {trade.profit_rate:+.2f}% (보유: {trade.holding_days}일, 이유: {trade.exit_reason})")

        print(f"\n❌ 손실 거래: {len(losses)}회")
        if losses:
            print("  하위 3건:")
            for trade in sorted(losses, key=lambda x: x.profit_rate)[:3]:
                print(f"    [{trade.entry_date.date()}] {trade.profit_rate:+.2f}% (보유: {trade.holding_days}일, 이유: {trade.exit_reason})")

        # 5. 종료 사유 분석
        print("\n" + "=" * 80)
        print("📊 거래 종료 사유 분석")
        print("=" * 80)

        exit_reasons = {}
        for trade in result_strict.trades:
            if trade.exit_date:
                reason = trade.exit_reason
                if reason not in exit_reasons:
                    exit_reasons[reason] = {"count": 0, "profit": 0, "loss": 0}
                exit_reasons[reason]["count"] += 1
                if trade.profit_rate > 0:
                    exit_reasons[reason]["profit"] += 1
                else:
                    exit_reasons[reason]["loss"] += 1

        print()
        for reason, stats in exit_reasons.items():
            win_rate = (stats["profit"] / stats["count"] * 100) if stats["count"] > 0 else 0
            print(f"  {reason:20s}: {stats['count']:2d}회 (승: {stats['profit']:2d}, 패: {stats['loss']:2d}, 승률: {win_rate:5.1f}%)")

        await db_session.commit()
        await redis_client.disconnect()

        return result_strict

    finally:
        await db_session.close()


if __name__ == "__main__":
    asyncio.run(main())
