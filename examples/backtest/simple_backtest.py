# -*- coding: utf-8 -*-
"""
간단한 백테스팅 예제

삼성전자(005930)에 대해 볼린저 밴드 + 엔벨로프 전략을 백테스팅합니다.
"""

import asyncio
from datetime import datetime
from decimal import Decimal

from src.adapters.cache.redis_client import get_redis_client
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
from src.settings.config import settings


async def main():
    """메인 실행 함수"""
    print("=" * 80)
    print("📊 백테스팅 예제 - 삼성전자 (DB 캐싱 활성화)")
    print("=" * 80)

    # 1. 의존성 초기화
    from src.adapters.database.connection import get_db

    kis_client = KISAPIClient()
    redis_client = await get_redis_client()

    # 2. DB 세션 생성 (캐싱 사용)
    db_gen = get_db()
    db_session = await db_gen.__anext__()

    try:
        # 3. 서비스 초기화 (DB 세션 전달)
        market_data_service = MarketDataService(kis_client, redis_client)
        backtest_service = BacktestService(market_data_service, db_session)

        # 4. 전략 설정
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
                allocation_ratio=0.1,  # 10% 배분
                max_position_count=1
            ),
            risk_management=RiskManagementConfig(
                use_stop_loss=True,
                stop_loss_ratio=-0.03,  # -3% 손절
                use_take_profit=True,
                take_profit_ratio=0.05,  # +5% 익절
                use_trailing_stop=False,
                use_reverse_signal_exit=True
            )
        )

        # 5. 백테스팅 설정
        backtest_config = BacktestConfigDTO(
            initial_capital=Decimal("10_000_000"),  # 1,000만원
            commission_rate=0.00015,  # 0.015%
            tax_rate=0.0023,  # 0.23%
            slippage_rate=0.0005,  # 0.05%
            use_commission=True,
            use_tax=True,
            use_slippage=True
        )

        # 6. 백테스팅 요청 생성
        request = BacktestRequestDTO(
            symbol="005930",  # 삼성전자
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 12, 31),
            strategy_config=strategy_config,
            backtest_config=backtest_config
        )

        # 7. 백테스팅 실행
        print("\n🚀 백테스팅 시작...")
        print(f"  - 종목: {request.symbol} (삼성전자)")
        print(f"  - 기간: {request.start_date.date()} ~ {request.end_date.date()}")
        print(f"  - 초기 자본: {request.backtest_config.initial_capital:,.0f}원")
        print(f"  - 캐싱: DB 활성화")
        print()

        result = await backtest_service.run_backtest(request)

        # 8. 결과 출력
        backtest_service.print_result_summary(result)

        # 9. 성과 등급
        grade = backtest_service.get_strategy_performance_grade(result)
        print(f"\n🎯 전략 성과 등급: {grade}")

        # 10. 거래 내역 샘플 출력
        print(f"\n📜 거래 내역 (최근 5건):")
        print("=" * 80)
        for trade in result.trades[-5:]:
            if trade.exit_date:
                print(f"  [{trade.entry_date.date()}] 매수 {trade.entry_price:,.0f}원 x {trade.quantity}주")
                print(f"  [{trade.exit_date.date()}] 매도 {trade.exit_price:,.0f}원 (손익: {trade.profit_rate:+.2f}%, 이유: {trade.exit_reason})")
                print()

        # 11. 리소스 정리
        await db_session.commit()
        await redis_client.disconnect()

        print("\n✅ 백테스팅 예제 완료!")

    finally:
        # DB 세션 정리
        await db_session.close()


if __name__ == "__main__":
    asyncio.run(main())
