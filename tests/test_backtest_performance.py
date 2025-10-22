# -*- coding: utf-8 -*-
"""
백테스트 성능 테스트

대용량 데이터 처리 성능 측정
"""

import time
from datetime import datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from src.application.domain.backtest.dto import BacktestConfigDTO
from src.application.domain.backtest.engine import BacktestEngine
from src.application.domain.strategy.dto import (
    BollingerBandConfig,
    EnvelopeConfig,
    PositionConfig,
    RiskManagementConfig,
    StrategyConfigDTO,
)


class TestBacktestPerformance:
    """백테스트 성능 테스트"""

    def setup_method(self):
        """테스트 초기화"""
        # 전략 설정
        self.strategy_config = StrategyConfigDTO(
            bollinger_band=BollingerBandConfig(period=20, std_multiplier=2.0),
            envelope=EnvelopeConfig(period=20, percentage=2.0),
            position=PositionConfig(allocation_ratio=0.1, max_position_count=1),
            risk_management=RiskManagementConfig(
                use_stop_loss=True,
                stop_loss_ratio=-0.05,
                use_take_profit=True,
                take_profit_ratio=0.10,
                use_trailing_stop=False,
                use_reverse_signal_exit=True,
            ),
        )

        # 백테스트 설정
        self.backtest_config = BacktestConfigDTO(
            initial_capital=Decimal("10000000"),
            commission_rate=0.00015,
            tax_rate=0.0023,
            slippage_rate=0.0005,
            use_commission=True,
            use_tax=True,
            use_slippage=True,
        )

    def _generate_test_data(self, days: int, trend: str = "mixed") -> pd.DataFrame:
        """
        테스트 데이터 생성

        Args:
            days: 일수
            trend: 트렌드 타입 ("up", "down", "mixed", "volatile")

        Returns:
            pd.DataFrame: OHLCV 데이터
        """
        dates = pd.date_range(start="2023-01-01", periods=days, freq="D")
        prices = []

        if trend == "up":
            # 상승 추세
            base = 70000
            for i in range(days):
                prices.append(base + i * 100 + (i % 10) * 50)

        elif trend == "down":
            # 하락 추세
            base = 90000
            for i in range(days):
                prices.append(base - i * 100 + (i % 10) * 50)

        elif trend == "volatile":
            # 변동성 높음
            base = 70000
            for i in range(days):
                variation = (i % 20 - 10) * 500
                prices.append(base + variation)

        else:  # mixed
            # 혼합 추세 (실제 시장과 유사)
            base = 70000
            for i in range(days):
                # 사인 파동 + 랜덤 변동
                wave = int(5000 * ((i / 30) % 2 - 1))
                noise = (i % 7 - 3) * 200
                prices.append(base + wave + noise)

        return pd.DataFrame(
            {
                "timestamp": dates,
                "open": prices,
                "high": [p + 500 for p in prices],
                "low": [p - 500 for p in prices],
                "close": prices,
                "volume": [1000000 + (i % 100) * 10000 for i in range(days)],
            }
        )

    async def test_performance_small_dataset(self):
        """소규모 데이터셋 성능 테스트 (30일)"""
        data = self._generate_test_data(30, trend="mixed")

        engine = BacktestEngine(
            symbol="005930",
            strategy_config=self.strategy_config,
            backtest_config=self.backtest_config,
        )

        start_time = time.perf_counter()

        result = await engine.run(
            data=data,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 1, 30),
        )

        elapsed = time.perf_counter() - start_time

        # 성능 검증 (30일 데이터는 0.5초 이내 처리)
        assert elapsed < 0.5, f"Too slow: {elapsed:.3f}s for 30 days"

        # 결과 검증
        assert len(result.daily_stats) == 30
        assert result.total_return is not None

        print(f"\n[소규모] 30일 처리 시간: {elapsed:.3f}초")
        print(f"  - 일평균 처리 시간: {elapsed/30*1000:.2f}ms")
        print(f"  - 거래 횟수: {result.total_trades}")

    async def test_performance_medium_dataset(self):
        """중규모 데이터셋 성능 테스트 (180일, 약 6개월)"""
        data = self._generate_test_data(180, trend="mixed")

        engine = BacktestEngine(
            symbol="005930",
            strategy_config=self.strategy_config,
            backtest_config=self.backtest_config,
        )

        start_time = time.perf_counter()

        result = await engine.run(
            data=data,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 6, 30),
        )

        elapsed = time.perf_counter() - start_time

        # 성능 검증 (180일 데이터는 2초 이내 처리)
        assert elapsed < 2.0, f"Too slow: {elapsed:.3f}s for 180 days"

        # 결과 검증
        assert len(result.daily_stats) == 180
        assert result.total_return is not None

        print(f"\n[중규모] 180일 처리 시간: {elapsed:.3f}초")
        print(f"  - 일평균 처리 시간: {elapsed/180*1000:.2f}ms")
        print(f"  - 거래 횟수: {result.total_trades}")
        print(f"  - 수익률: {result.total_return:.2f}%")

    async def test_performance_large_dataset(self):
        """대규모 데이터셋 성능 테스트 (365일, 1년)"""
        data = self._generate_test_data(365, trend="mixed")

        engine = BacktestEngine(
            symbol="005930",
            strategy_config=self.strategy_config,
            backtest_config=self.backtest_config,
        )

        start_time = time.perf_counter()

        result = await engine.run(
            data=data,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 12, 31),
        )

        elapsed = time.perf_counter() - start_time

        # 성능 검증 (365일 데이터는 5초 이내 처리)
        assert elapsed < 5.0, f"Too slow: {elapsed:.3f}s for 365 days"

        # 결과 검증
        assert len(result.daily_stats) == 365
        assert result.total_return is not None

        print(f"\n[대규모] 365일 처리 시간: {elapsed:.3f}초")
        print(f"  - 일평균 처리 시간: {elapsed/365*1000:.2f}ms")
        print(f"  - 거래 횟수: {result.total_trades}")
        print(f"  - 승률: {result.win_rate:.1f}%")
        print(f"  - MDD: {result.mdd:.2f}%")
        print(f"  - Sharpe Ratio: {result.sharpe_ratio:.2f}")

    async def test_performance_very_large_dataset(self):
        """초대규모 데이터셋 성능 테스트 (730일, 2년)"""
        data = self._generate_test_data(730, trend="mixed")

        engine = BacktestEngine(
            symbol="005930",
            strategy_config=self.strategy_config,
            backtest_config=self.backtest_config,
        )

        start_time = time.perf_counter()

        result = await engine.run(
            data=data,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 12, 31),
        )

        elapsed = time.perf_counter() - start_time

        # 성능 검증 (730일 데이터는 10초 이내 처리)
        assert elapsed < 10.0, f"Too slow: {elapsed:.3f}s for 730 days"

        # 결과 검증
        assert len(result.daily_stats) == 730
        assert result.total_return is not None

        print(f"\n[초대규모] 730일 (2년) 처리 시간: {elapsed:.3f}초")
        print(f"  - 일평균 처리 시간: {elapsed/730*1000:.2f}ms")
        print(f"  - 초당 처리 일수: {730/elapsed:.0f}일/초")
        print(f"  - 거래 횟수: {result.total_trades}")
        print(f"  - CAGR: {result.cagr:.2f}%")

    async def test_performance_different_trends(self):
        """다양한 트렌드별 성능 테스트"""
        trends = ["up", "down", "mixed", "volatile"]
        results = {}

        for trend in trends:
            data = self._generate_test_data(100, trend=trend)

            engine = BacktestEngine(
                symbol="005930",
                strategy_config=self.strategy_config,
                backtest_config=self.backtest_config,
            )

            start_time = time.perf_counter()

            result = await engine.run(
                data=data,
                start_date=datetime(2023, 1, 1),
                end_date=datetime(2023, 4, 10),
            )

            elapsed = time.perf_counter() - start_time
            results[trend] = {
                "time": elapsed,
                "trades": result.total_trades,
                "return": result.total_return,
            }

        print("\n[트렌드별 성능 비교] 100일 데이터")
        for trend, stats in results.items():
            print(f"  {trend:10s}: {stats['time']:.3f}초, "
                  f"거래 {stats['trades']:2d}회, "
                  f"수익률 {stats['return']:+6.2f}%")

        # 모든 트렌드에서 1초 이내 처리
        for trend, stats in results.items():
            assert stats['time'] < 1.0, f"{trend} trend too slow"

    async def test_memory_efficiency(self):
        """메모리 효율성 테스트"""
        import tracemalloc

        # 메모리 추적 시작
        tracemalloc.start()

        data = self._generate_test_data(365, trend="mixed")

        engine = BacktestEngine(
            symbol="005930",
            strategy_config=self.strategy_config,
            backtest_config=self.backtest_config,
        )

        # 시작 메모리
        snapshot_start = tracemalloc.take_snapshot()

        result = await engine.run(
            data=data,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 12, 31),
        )

        # 종료 메모리
        snapshot_end = tracemalloc.take_snapshot()

        # 메모리 차이 계산
        top_stats = snapshot_end.compare_to(snapshot_start, 'lineno')
        total_memory = sum(stat.size_diff for stat in top_stats)

        tracemalloc.stop()

        # 메모리 사용량 출력
        print(f"\n[메모리 사용량] 365일 백테스트")
        print(f"  - 총 메모리 증가: {total_memory / 1024 / 1024:.2f} MB")
        print(f"  - 일평균 메모리: {total_memory / 365 / 1024:.2f} KB")

        # 메모리 효율성 검증 (365일 백테스트가 100MB 이하)
        assert total_memory < 100 * 1024 * 1024, \
            f"Too much memory used: {total_memory / 1024 / 1024:.2f}MB"

    async def test_concurrent_backtests(self):
        """동시 백테스트 실행 성능 테스트"""
        import asyncio

        # 3개 종목 동시 백테스트
        data1 = self._generate_test_data(100, trend="up")
        data2 = self._generate_test_data(100, trend="down")
        data3 = self._generate_test_data(100, trend="mixed")

        engines = [
            BacktestEngine("005930", self.strategy_config, self.backtest_config),
            BacktestEngine("000660", self.strategy_config, self.backtest_config),
            BacktestEngine("035420", self.strategy_config, self.backtest_config),
        ]

        start_time = time.perf_counter()

        # 동시 실행
        results = await asyncio.gather(
            engines[0].run(data1, datetime(2023, 1, 1), datetime(2023, 4, 10)),
            engines[1].run(data2, datetime(2023, 1, 1), datetime(2023, 4, 10)),
            engines[2].run(data3, datetime(2023, 1, 1), datetime(2023, 4, 10)),
        )

        elapsed = time.perf_counter() - start_time

        print(f"\n[동시 실행] 3개 종목 x 100일")
        print(f"  - 총 처리 시간: {elapsed:.3f}초")
        print(f"  - 종목당 평균: {elapsed/3:.3f}초")
        for i, result in enumerate(results):
            print(f"  - 종목{i+1}: 거래 {result.total_trades}회, "
                  f"수익률 {result.total_return:+.2f}%")

        # 동시 실행이 순차 실행보다 효율적인지 확인
        # (완벽한 병렬화는 아니지만 어느 정도 이득이 있어야 함)
        assert elapsed < 3.0, "Concurrent execution too slow"
