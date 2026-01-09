# -*- coding: utf-8 -*-
"""
Evaluate Strategy - 오프라인 전략 평가 스크립트

합성 데이터를 사용하여 전략의 성능을 평가합니다.

Usage:
    python -m scripts.evaluate_strategy
    python -m scripts.evaluate_strategy --preset aggressive
    python -m scripts.evaluate_strategy --simulations 50
"""

import argparse
import asyncio
from datetime import datetime

from scripts.common.backtest_runner import BacktestRunner
from scripts.common.data_generator import MarketScenario, SyntheticDataGenerator
from scripts.common.result_analyzer import ResultAnalyzer
from scripts.common.strategy_presets import StrategyPresets


async def run_single_scenario(args):
    """단일 시나리오 테스트"""
    print("\n" + "=" * 60)
    print("  1. Single Scenario Analysis")
    print("=" * 60)

    # 전략 설정 로드
    strategy_config = StrategyPresets.get_strategy_preset(args.preset)
    backtest_config = StrategyPresets.default_backtest_config()

    # 시나리오 생성
    scenario = MarketScenario(
        name="SingleTest",
        trend=args.trend,
        volatility=args.volatility,
        periods=args.periods,
        seed=args.seed,
        scenario_type=args.scenario_type,
    )

    print(f"\n  Scenario: {args.scenario_type}")
    print(f"  Trend: {args.trend:.4f}, Volatility: {args.volatility:.4f}")
    print(f"  Periods: {args.periods}, Preset: {args.preset}")

    # 데이터 생성
    df = SyntheticDataGenerator.generate_ohlcv(scenario)
    print(f"  Generated {len(df)} candles")

    # 백테스트 실행
    result = await BacktestRunner.run_single(
        df=df,
        symbol="SYNTHETIC",
        strategy_config=strategy_config,
        backtest_config=backtest_config,
    )

    # 결과 출력
    ResultAnalyzer.print_single_result(result, "Single Scenario Result")

    return result


async def run_monte_carlo(args):
    """몬테카를로 시뮬레이션"""
    print("\n" + "=" * 60)
    print("  2. Monte Carlo Simulation")
    print("=" * 60)

    strategy_config = StrategyPresets.get_strategy_preset(args.preset)
    backtest_config = StrategyPresets.default_backtest_config()

    # 기본 시나리오
    base_scenario = MarketScenario(
        name="MonteCarloBase",
        trend=args.trend,
        volatility=args.volatility,
        periods=args.periods,
    )

    print(f"\n  Simulations: {args.simulations}")
    print(f"  Base Trend: {args.trend:.4f}, Base Vol: {args.volatility:.4f}")

    # 데이터 생성
    datasets = SyntheticDataGenerator.generate_monte_carlo(
        base_scenario=base_scenario,
        simulations=args.simulations,
        trend_std=0.0005,
        vol_range=(0.01, 0.03),
    )

    # 백테스트 실행 (진행 상황 표시)
    results = await BacktestRunner.run_with_progress(
        datasets=datasets,
        strategy_config=strategy_config,
        backtest_config=backtest_config,
    )

    # 결과 분석
    ResultAnalyzer.print_monte_carlo_summary(results)

    # 결과 저장 (옵션)
    if args.output:
        ResultAnalyzer.save_to_json(results, args.output)

    return results


async def main():
    parser = argparse.ArgumentParser(
        description="Offline Strategy Evaluation with Synthetic Data"
    )

    parser.add_argument(
        "--preset",
        type=str,
        default="default",
        choices=["default", "conservative", "aggressive", "trailing"],
        help="Strategy preset (default: default)",
    )
    parser.add_argument(
        "--scenario-type",
        type=str,
        default="random",
        choices=["random", "gc_scenario", "dc_scenario", "sideways"],
        help="Market scenario type (default: random)",
    )
    parser.add_argument(
        "--trend",
        type=float,
        default=0.0002,
        help="Daily trend (default: 0.0002 = 0.02%%)",
    )
    parser.add_argument(
        "--volatility",
        type=float,
        default=0.015,
        help="Daily volatility (default: 0.015 = 1.5%%)",
    )
    parser.add_argument(
        "--periods",
        type=int,
        default=250,
        help="Number of candles (default: 250)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--simulations",
        type=int,
        default=20,
        help="Number of Monte Carlo simulations (default: 20)",
    )
    parser.add_argument(
        "--skip-single",
        action="store_true",
        help="Skip single scenario test",
    )
    parser.add_argument(
        "--skip-monte-carlo",
        action="store_true",
        help="Skip Monte Carlo simulation",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON file path for results",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("  Offline Strategy Evaluation")
    print("=" * 60)
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. 단일 시나리오 테스트
    if not args.skip_single:
        await run_single_scenario(args)

    # 2. 몬테카를로 시뮬레이션
    if not args.skip_monte_carlo:
        await run_monte_carlo(args)

    print("\n" + "=" * 60)
    print("  Evaluation Complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
