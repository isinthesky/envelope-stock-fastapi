# -*- coding: utf-8 -*-
"""
Result Analyzer - 백테스트 결과 분석 및 포맷팅 모듈

결과 출력, 비교, 통계 분석 기능을 제공합니다.
"""

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.application.domain.backtest.dto import BacktestResultDTO


class ResultAnalyzer:
    """
    백테스트 결과 분석 및 포맷팅

    결과 출력, 비교 테이블, 통계 분석, 파일 저장 기능 제공
    """

    # ==================== 단일 결과 출력 ====================

    @staticmethod
    def print_single_result(result: BacktestResultDTO, title: str = "Backtest Result") -> None:
        """
        단일 백테스트 결과 출력

        Args:
            result: 백테스트 결과
            title: 출력 제목
        """
        print(f"\n{'=' * 60}")
        print(f"  {title}")
        print(f"{'=' * 60}")

        print(f"\n  📊 Performance Metrics")
        print(f"  {'─' * 40}")
        print(f"  Total Return:    {result.total_return:>10.2f}%")
        print(f"  Win Rate:        {result.win_rate:>10.2f}%")
        print(f"  Profit Factor:   {result.profit_factor:>10.2f}")
        print(f"  Sharpe Ratio:    {result.sharpe_ratio:>10.2f}")
        print(f"  MDD:             {result.mdd:>10.2f}%")

        print(f"\n  📈 Trading Statistics")
        print(f"  {'─' * 40}")
        print(f"  Total Trades:    {result.total_trades:>10}")
        print(f"  Winning Trades:  {result.winning_trades:>10}")
        print(f"  Losing Trades:   {result.losing_trades:>10}")

        if hasattr(result, 'final_capital'):
            print(f"\n  💰 Capital")
            print(f"  {'─' * 40}")
            print(f"  Final Capital:   {result.final_capital:>15,.0f}")

        print(f"\n{'=' * 60}\n")

    # ==================== 다중 결과 비교 ====================

    @staticmethod
    def print_comparison_table(
        results: dict[str, BacktestResultDTO],
        columns: list[str] | None = None,
    ) -> None:
        """
        다중 결과 비교 테이블 출력

        Args:
            results: {이름: 결과} 딕셔너리
            columns: 표시할 컬럼 목록 (기본값: 주요 지표)
        """
        if not results:
            print("No results to compare")
            return

        if columns is None:
            columns = ["total_return", "win_rate", "sharpe_ratio", "mdd", "total_trades"]

        # 헤더
        header = f"{'Name':<20}"
        for col in columns:
            header += f" {col:>12}"
        print(header)
        print("-" * len(header))

        # 데이터
        for name, result in results.items():
            row = f"{name:<20}"
            for col in columns:
                value = getattr(result, col, "N/A")
                if isinstance(value, float):
                    if col in ["total_return", "win_rate", "mdd"]:
                        row += f" {value:>11.2f}%"
                    else:
                        row += f" {value:>12.2f}"
                else:
                    row += f" {value:>12}"
            print(row)

    # ==================== 몬테카를로 분석 ====================

    @staticmethod
    def print_monte_carlo_summary(results: list[BacktestResultDTO]) -> None:
        """
        몬테카를로 시뮬레이션 결과 요약 출력

        Args:
            results: 시뮬레이션 결과 목록
        """
        if not results:
            print("No Monte Carlo results")
            return

        total_returns = [r.total_return for r in results]
        win_rates = [r.win_rate for r in results]
        sharpe_ratios = [r.sharpe_ratio for r in results]
        mdds = [r.mdd for r in results]

        print(f"\n{'=' * 60}")
        print("  📊 Monte Carlo Simulation Summary")
        print(f"  {'─' * 50}")
        print(f"  Simulations: {len(results)}")
        print(f"{'=' * 60}")

        print(f"\n  Return Distribution")
        print(f"  {'─' * 40}")
        print(f"  Mean:    {np.mean(total_returns):>10.2f}%")
        print(f"  Std:     {np.std(total_returns):>10.2f}%")
        print(f"  Min:     {np.min(total_returns):>10.2f}%")
        print(f"  Max:     {np.max(total_returns):>10.2f}%")
        print(f"  Median:  {np.median(total_returns):>10.2f}%")

        print(f"\n  Win Rate Distribution")
        print(f"  {'─' * 40}")
        print(f"  Mean:    {np.mean(win_rates):>10.2f}%")
        print(f"  Min:     {np.min(win_rates):>10.2f}%")
        print(f"  Max:     {np.max(win_rates):>10.2f}%")

        print(f"\n  Sharpe Ratio Distribution")
        print(f"  {'─' * 40}")
        print(f"  Mean:    {np.mean(sharpe_ratios):>10.2f}")
        print(f"  Min:     {np.min(sharpe_ratios):>10.2f}")
        print(f"  Max:     {np.max(sharpe_ratios):>10.2f}")

        print(f"\n  Risk Metrics")
        print(f"  {'─' * 40}")
        print(f"  Avg MDD:         {np.mean(mdds):>10.2f}%")
        print(f"  Worst MDD:       {np.min(mdds):>10.2f}%")
        positive_count = sum(1 for r in total_returns if r > 0)
        print(f"  Positive Rate:   {positive_count / len(results) * 100:>10.1f}%")

        # 백분위
        print(f"\n  Return Percentiles")
        print(f"  {'─' * 40}")
        for p in [5, 25, 50, 75, 95]:
            pct_value = np.percentile(total_returns, p)
            print(f"  {p}th:    {pct_value:>10.2f}%")

        print(f"\n{'=' * 60}\n")

    @staticmethod
    def get_monte_carlo_stats(results: list[BacktestResultDTO]) -> dict:
        """
        몬테카를로 결과 통계 계산

        Args:
            results: 시뮬레이션 결과 목록

        Returns:
            dict: 통계 정보
        """
        if not results:
            return {}

        total_returns = [r.total_return for r in results]
        win_rates = [r.win_rate for r in results]
        sharpe_ratios = [r.sharpe_ratio for r in results]
        mdds = [r.mdd for r in results]

        return {
            "simulations": len(results),
            "return_mean": float(np.mean(total_returns)),
            "return_std": float(np.std(total_returns)),
            "return_min": float(np.min(total_returns)),
            "return_max": float(np.max(total_returns)),
            "return_median": float(np.median(total_returns)),
            "win_rate_mean": float(np.mean(win_rates)),
            "sharpe_mean": float(np.mean(sharpe_ratios)),
            "mdd_mean": float(np.mean(mdds)),
            "mdd_worst": float(np.min(mdds)),
            "positive_rate": float(sum(1 for r in total_returns if r > 0) / len(results)),
            "percentile_5": float(np.percentile(total_returns, 5)),
            "percentile_25": float(np.percentile(total_returns, 25)),
            "percentile_50": float(np.percentile(total_returns, 50)),
            "percentile_75": float(np.percentile(total_returns, 75)),
            "percentile_95": float(np.percentile(total_returns, 95)),
        }

    # ==================== DataFrame 변환 ====================

    @staticmethod
    def to_dataframe(results: list[BacktestResultDTO]) -> pd.DataFrame:
        """
        결과를 DataFrame으로 변환

        Args:
            results: 결과 목록

        Returns:
            pd.DataFrame: 결과 테이블
        """
        if not results:
            return pd.DataFrame()

        data = []
        for i, result in enumerate(results):
            data.append({
                "simulation": i + 1,
                "total_return": result.total_return,
                "win_rate": result.win_rate,
                "profit_factor": result.profit_factor,
                "sharpe_ratio": result.sharpe_ratio,
                "mdd": result.mdd,
                "total_trades": result.total_trades,
                "winning_trades": result.winning_trades,
                "losing_trades": result.losing_trades,
            })

        return pd.DataFrame(data)

    # ==================== 파일 저장 ====================

    @staticmethod
    def save_to_json(
        results: list[BacktestResultDTO] | dict[str, BacktestResultDTO],
        filepath: str | Path,
        include_stats: bool = True,
    ) -> None:
        """
        결과를 JSON 파일로 저장

        Args:
            results: 결과 목록 또는 딕셔너리
            filepath: 저장 경로
            include_stats: 통계 포함 여부
        """
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        output = {
            "generated_at": datetime.now().isoformat(),
        }

        if isinstance(results, dict):
            output["results"] = {
                name: result.model_dump() for name, result in results.items()
            }
        else:
            output["results"] = [result.model_dump() for result in results]

            if include_stats and len(results) > 1:
                output["statistics"] = ResultAnalyzer.get_monte_carlo_stats(results)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2, default=str)

        print(f"Results saved to: {filepath}")

    @staticmethod
    def save_to_csv(
        results: list[BacktestResultDTO],
        filepath: str | Path,
    ) -> None:
        """
        결과를 CSV 파일로 저장

        Args:
            results: 결과 목록
            filepath: 저장 경로
        """
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        df = ResultAnalyzer.to_dataframe(results)
        df.to_csv(filepath, index=False, encoding="utf-8-sig")

        print(f"Results saved to: {filepath}")

    # ==================== 리포트 생성 ====================

    @staticmethod
    def generate_markdown_report(
        results: list[BacktestResultDTO],
        title: str = "Backtest Report",
    ) -> str:
        """
        마크다운 형식 리포트 생성

        Args:
            results: 결과 목록
            title: 리포트 제목

        Returns:
            str: 마크다운 텍스트
        """
        stats = ResultAnalyzer.get_monte_carlo_stats(results)

        report = f"# {title}\n\n"
        report += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        report += "## Summary\n\n"
        report += f"- **Simulations**: {stats['simulations']}\n"
        report += f"- **Positive Rate**: {stats['positive_rate']:.1%}\n\n"

        report += "## Return Distribution\n\n"
        report += "| Metric | Value |\n"
        report += "|--------|-------|\n"
        report += f"| Mean | {stats['return_mean']:.2f}% |\n"
        report += f"| Std | {stats['return_std']:.2f}% |\n"
        report += f"| Min | {stats['return_min']:.2f}% |\n"
        report += f"| Max | {stats['return_max']:.2f}% |\n"
        report += f"| Median | {stats['return_median']:.2f}% |\n\n"

        report += "## Risk Metrics\n\n"
        report += f"- **Average MDD**: {stats['mdd_mean']:.2f}%\n"
        report += f"- **Worst MDD**: {stats['mdd_worst']:.2f}%\n"
        report += f"- **Average Sharpe**: {stats['sharpe_mean']:.2f}\n\n"

        report += "## Percentiles\n\n"
        report += "| Percentile | Return |\n"
        report += "|------------|--------|\n"
        report += f"| 5th | {stats['percentile_5']:.2f}% |\n"
        report += f"| 25th | {stats['percentile_25']:.2f}% |\n"
        report += f"| 50th (Median) | {stats['percentile_50']:.2f}% |\n"
        report += f"| 75th | {stats['percentile_75']:.2f}% |\n"
        report += f"| 95th | {stats['percentile_95']:.2f}% |\n"

        return report
