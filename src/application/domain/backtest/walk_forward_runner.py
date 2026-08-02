# -*- coding: utf-8 -*-
"""
Walk-Forward Runner (P3) — 진짜 out-of-sample 검증

기존 `walk_forward.py`(손입력 메트릭 재출력 스텁)를 대체하는, **실제로 엔진을
돌려 train/test 성과를 계산하는** 러너.

파이프라인:
    1. fold별 롤링 (train,test) 창 (`walk_forward_windows`)
    2. fold별 **as-of 유니버스**: 해당 창을 커버하는(워밍업 포함) 종목만 편입
    3. train 구간에서 후보 config 중 선택(selection_metric argmax) → **freeze(hash)**
    4. 동결 config로 **test 구간 OOS** 평가 (fold마다 플랫 시작)
    5. 각 fold의 OOS 일별수익을 **이어붙여 연속 OOS equity** → 집계 지표

지표는 검증된 `PortfolioParityEngine`(라이브 parity 시그널 + 비용 + 집중도 캡)과
`PerformanceMetrics`로 계산한다. 손입력 숫자는 없다.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any, cast

import pandas as pd

from src.application.common.performance_metrics import PerformanceMetrics
from src.application.domain.backtest.dto import (
    BacktestConfigDTO,
    BacktestResultDTO,
    DailyStatsDTO,
)
from src.application.domain.backtest.portfolio_parity_engine import (
    PortfolioConstraints,
    PortfolioParityEngine,
)
from src.application.domain.backtest.walk_forward_windows import WalkForwardWindow
from src.application.domain.strategy.dto import GoldenCrossConfigDTO


@dataclass(frozen=True, slots=True)
class WalkForwardCandidate:
    label: str
    config: GoldenCrossConfigDTO


@dataclass(frozen=True, slots=True)
class FoldOutcome:
    window: WalkForwardWindow
    eligible_symbols: int
    selected_label: str
    selected_hash: str
    train: dict
    test: dict  # OOS
    excluded_symbols: int = 0
    excluded_sample: tuple[str, ...] = ()  # 제외 종목 일부(무음 누락 방지)


@dataclass(frozen=True, slots=True)
class WalkForwardReport:
    folds: list[FoldOutcome]
    oos: dict
    markdown: str
    candidates: int
    trials: int  # 총 시도(후보×fold) — 데이터 스누핑 보정(P4 DSR) 입력


def _metrics(result: BacktestResultDTO) -> dict:
    return {
        "total_return": result.total_return,
        "cagr": result.cagr,
        "sharpe": result.sharpe_ratio,
        "mdd": result.mdd,
        "total_trades": result.total_trades,
    }


class WalkForwardRunner:
    def __init__(
        self,
        candidates: list[WalkForwardCandidate],
        constraints: PortfolioConstraints | None = None,
        backtest_config: BacktestConfigDTO | None = None,
        *,
        selection_metric: str = "sharpe_ratio",
        lookback_trading_days: int | None = None,
        min_fold_coverage: float = 0.9,
    ) -> None:
        if not candidates:
            raise ValueError("at least one candidate config required")
        self.candidates = candidates
        self.constraints = constraints or PortfolioConstraints()
        self.backtest_config = backtest_config or BacktestConfigDTO()
        self.selection_metric = selection_metric
        self.min_fold_coverage = min_fold_coverage
        if lookback_trading_days is None:
            long = max(c.config.ma_config.long_period for c in candidates)
            lookback_trading_days = long + 30
        self.lookback_trading_days = lookback_trading_days

    # ==================== public ====================

    def run(
        self,
        panels: dict[str, pd.DataFrame],
        trading_days: list[date],
        windows: list[WalkForwardWindow],
    ) -> WalkForwardReport:
        if not panels or not windows:
            raise ValueError("panels and windows required")

        days = sorted(set(trading_days))
        day_index = {d: i for i, d in enumerate(days)}
        symbol_dates = {
            sym: sorted({self._row_date(ts) for ts in df["timestamp"]})
            for sym, df in panels.items()
        }

        folds: list[FoldOutcome] = []
        oos_segments: list[list[DailyStatsDTO]] = []
        trials = 0

        for w in windows:
            lb_start = self._lookback_start(days, day_index, w.train_start)
            eligible = [
                sym
                for sym in panels
                if self._eligible(symbol_dates[sym], days, day_index, w, lb_start)
            ]
            excluded = sorted(set(panels) - set(eligible))
            excluded_sample = tuple(excluded[:10])
            if not eligible:
                folds.append(FoldOutcome(w, 0, "-", "", {}, {}, len(excluded), excluded_sample))
                continue

            # 1) train에서 후보 선택
            train_slice = {sym: self._slice(panels[sym], lb_start, w.train_end) for sym in eligible}
            best_value: float | None = None
            best_candidate: WalkForwardCandidate | None = None
            best_result: BacktestResultDTO | None = None
            for cand in self.candidates:
                trials += 1
                engine = PortfolioParityEngine(cand.config, self.constraints)
                res = engine.run(train_slice, self.backtest_config, active_from=w.train_start)
                value = self._metric_value(res.result)
                if best_value is None or value > best_value:
                    best_value = value
                    best_candidate = cand
                    best_result = res.result

            assert best_candidate is not None and best_result is not None
            selected_hash = self._freeze(best_candidate)

            # 2) 동결 config로 OOS test (fold마다 플랫 시작)
            test_lb_start = self._lookback_start(days, day_index, w.test_start)
            test_slice = {
                sym: self._slice(panels[sym], test_lb_start, w.test_end) for sym in eligible
            }
            test_engine = PortfolioParityEngine(best_candidate.config, self.constraints)
            test_res = test_engine.run(test_slice, self.backtest_config, active_from=w.test_start)

            folds.append(
                FoldOutcome(
                    window=w,
                    eligible_symbols=len(eligible),
                    selected_label=best_candidate.label,
                    selected_hash=selected_hash,
                    train=_metrics(best_result),
                    test=_metrics(test_res.result),
                    excluded_symbols=len(excluded),
                    excluded_sample=excluded_sample,
                )
            )
            oos_segments.append(test_res.result.daily_stats)

        oos = self._stitch_oos(oos_segments, self.backtest_config.initial_capital)
        markdown = self._report_md(folds, oos, trials)
        return WalkForwardReport(
            folds=folds,
            oos=oos,
            markdown=markdown,
            candidates=len(self.candidates),
            trials=trials,
        )

    # ==================== helpers ====================

    @staticmethod
    def _row_date(ts: Any) -> date:
        return cast(date, ts.date() if hasattr(ts, "date") else ts)

    def _lookback_start(self, days: list[date], day_index: dict[date, int], anchor: date) -> date:
        idx = day_index.get(anchor)
        if idx is None:
            # anchor가 거래일 리스트에 없으면 가장 가까운 이전 거래일 사용
            prior = [d for d in days if d <= anchor]
            idx = day_index[prior[-1]] if prior else 0
        return days[max(0, idx - self.lookback_trading_days)]

    def _eligible(
        self,
        sdates: list[date],
        days: list[date],
        day_index: dict[date, int],
        w: WalkForwardWindow,
        lb_start: date,
    ) -> bool:
        if not sdates:
            return False
        # 워밍업 이력 + test_end까지 데이터 보유
        if sdates[0] > lb_start or sdates[-1] < w.test_end:
            return False
        # [train_start, test_end] 커버리지
        window_days = [d for d in days if w.train_start <= d <= w.test_end]
        if not window_days:
            return False
        sset = set(sdates)
        covered = sum(1 for d in window_days if d in sset)
        return covered / len(window_days) >= self.min_fold_coverage

    @staticmethod
    def _slice(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
        d = df["timestamp"].map(lambda ts: ts.date() if hasattr(ts, "date") else ts)
        return df[(d >= start) & (d <= end)].reset_index(drop=True)

    def _metric_value(self, result: BacktestResultDTO) -> float:
        # 무거래 config는 선택 대상에서 제외(no-op이 우연히 1등 되는 것 방지)
        if result.total_trades == 0:
            return float("-inf")
        value = getattr(result, self.selection_metric, None)
        if value is None:
            return float("-inf")
        try:
            fvalue = float(value)
        except (TypeError, ValueError):
            return float("-inf")
        if fvalue != fvalue:  # NaN
            return float("-inf")
        return fvalue

    @staticmethod
    def _freeze(candidate: WalkForwardCandidate) -> str:
        payload = f"{candidate.label}:{candidate.config.model_dump_json()}"
        return sha256(payload.encode("utf-8")).hexdigest()[:16]

    def _stitch_oos(self, segments: list[list[DailyStatsDTO]], initial_capital: Decimal) -> dict:
        segments = [s for s in segments if s]
        if not segments:
            return {
                "total_return": 0.0,
                "cagr": 0.0,
                "sharpe": 0.0,
                "mdd": 0.0,
                "trading_days": 0,
                "folds": 0,
            }
        c0 = float(initial_capital)

        # fold별 일별수익을 (날짜, 수익) 쌍으로 모은다. 각 fold는 플랫 시작이므로
        # day-0 수익은 c0 대비(진입일 비용/손익 포함)로 계산한다.
        per_day: list[tuple[datetime, float]] = []
        for seg in segments:
            eqs = [float(s.equity) for s in seg]
            dts = [s.date for s in seg]
            if not eqs:
                continue
            if c0 > 0:
                per_day.append((dts[0], eqs[0] / c0 - 1.0))  # 진입일 비용 반영
            for i in range(1, len(eqs)):
                prev = eqs[i - 1]
                if prev > 0:
                    per_day.append((dts[i], eqs[i] / prev - 1.0))

        # 날짜 기준 dedup: test 창이 겹쳐도(step < test_size) 같은 거래일 수익을
        # 이중계산하지 않는다. 시간순 정렬 후 최초 관측만 채택.
        seen: set[date] = set()
        equities = [c0]
        dates = []
        for dt, r in sorted(per_day, key=lambda x: x[0]):
            d = dt.date() if hasattr(dt, "date") else dt
            if d in seen:
                continue
            seen.add(d)
            equities.append(equities[-1] * (1.0 + r))
            dates.append(dt)

        if len(equities) < 2:
            return {
                "total_return": 0.0,
                "cagr": 0.0,
                "sharpe": 0.0,
                "mdd": 0.0,
                "trading_days": 0,
                "folds": len(segments),
            }
        # equities[0]=c0 에 첫 날짜를 붙여 길이를 맞춘다.
        dates = [dates[0]] + dates
        final = equities[-1]
        total_return = (final / c0 - 1.0) * 100.0
        start_dt, end_dt = dates[0], dates[-1]
        years = max((end_dt - start_dt).days / 365.0, 1e-9)
        cagr = PerformanceMetrics.calculate_cagr(Decimal(str(c0)), Decimal(str(final)), years)
        mdd = PerformanceMetrics.calculate_mdd([Decimal(str(e)) for e in equities])["mdd"]
        equity_df = pd.DataFrame({"timestamp": dates, "equity": equities})
        volatility = PerformanceMetrics.calculate_volatility(equity_df)
        annualized = PerformanceMetrics.calculate_annualized_return(
            Decimal(str(c0)), Decimal(str(final)), start_dt, end_dt
        )
        sharpe = PerformanceMetrics.calculate_sharpe_ratio(annualized, volatility)
        return {
            "total_return": round(total_return, 2),
            "cagr": round(cagr, 2),
            "sharpe": round(sharpe, 3),
            "mdd": round(mdd, 2),
            "trading_days": len(seen),
            "folds": len(segments),
        }

    def _report_md(self, folds: list[FoldOutcome], oos: dict, trials: int) -> str:
        lines = [
            "# Walk-Forward Validation Report (real OOS)",
            "",
            f"- Candidates: {len(self.candidates)} | Folds: {len(folds)} | "
            f"Trials(candidate×fold): {trials}",
            f"- Selection metric: `{self.selection_metric}`",
            f"- Constraints: max_positions={self.constraints.max_positions}, "
            f"max_sector_weight={self.constraints.max_sector_weight}",
            "",
            "## Stitched OOS (headline — 이 숫자만이 정직한 성과)",
            "",
            f"- CAGR: **{oos['cagr']}%** | Sharpe: **{oos['sharpe']}** | "
            f"MDD: **{oos['mdd']}%** | total_return: {oos['total_return']}%",
            f"- OOS trading days: {oos['trading_days']} across {oos['folds']} folds",
            "",
            "## Per-fold (train 선택 → test OOS)",
            "",
            "| Fold | Train | Test(OOS) | Eligible | Excluded | Selected | Hash | "
            "Train Sharpe | Test Sharpe | Test Ret% | Test MDD% | Test Trades |",
            "| --- | --- | --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for i, f in enumerate(folds, 1):
            w = f.window
            if not f.test:
                lines.append(
                    f"| {i} | {w.train_start}~{w.train_end} | {w.test_start}~{w.test_end} "
                    f"| 0 | {f.excluded_symbols} | _(no eligible symbols)_ | | | | | | |"
                )
                continue
            lines.append(
                f"| {i} | {w.train_start}~{w.train_end} | {w.test_start}~{w.test_end} "
                f"| {f.eligible_symbols} | {f.excluded_symbols} | `{f.selected_label}` "
                f"| `{f.selected_hash}` "
                f"| {f.train.get('sharpe', 0):.2f} | {f.test.get('sharpe', 0):.2f} "
                f"| {f.test.get('total_return', 0):.2f} | {f.test.get('mdd', 0):.2f} "
                f"| {f.test.get('total_trades', 0)} |"
            )
        # 제외 종목 표본(무음 누락 방지)
        excluded_lines = [
            f"  - Fold {i}: {f.excluded_symbols} excluded"
            + (f" (예: {', '.join(f.excluded_sample)})" if f.excluded_sample else "")
            for i, f in enumerate(folds, 1)
            if f.excluded_symbols
        ]
        if excluded_lines:
            lines.append("")
            lines.append("### 제외 종목 (fold별 as-of 미달)")
            lines.extend(excluded_lines)
        lines.append("")
        lines.append(
            "> IS→OOS 성과 감쇠와 fold별 편차를 함께 보라. train Sharpe 대비 "
            "test Sharpe가 크게 낮으면 과적합 신호다. DSR/PBO는 P4에서 산출."
        )
        lines.extend(
            [
                "",
                "## 알려진 한계 (해석 시 반드시 감안)",
                "",
                "- **생존편향**: fold 편입은 test_end까지 데이터가 있는 종목만 대상이라, "
                "구간 중 상장폐지된 종목이 빠진다. 데이터 소스에 폐지 ETF가 없어 코드로 "
                "완전 제거 불가 → OOS 성과는 낙관 방향으로 편향될 수 있다.",
                "- **fold 독립 플랫 시작**: 각 fold는 무포지션에서 시작하며 이전 fold의 "
                "보유는 이월되지 않는다(표준 walk-forward). 워밍업 구간 진입 신호는 집계 제외.",
                "- **same_close 체결**: 시그널 발생 바의 종가로 판단·체결(라이브 15:35 종가주문과 "
                "정합)하나 본질적으로 낙관적이다. paper-trade에서 실측 보정 필요.",
                "- **OOS 이어붙이기**: 겹치는 test 창(step<test_size)은 거래일 dedup으로 "
                "이중계산을 방지한다.",
                self._cost_assumption_line(),
            ]
        )
        return "\n".join(lines) + "\n"

    def _cost_assumption_line(self) -> str:
        cfg = self.backtest_config
        tax = "적용" if cfg.use_tax else "미적용"
        comm = "적용" if cfg.use_commission else "미적용"
        slip = "적용" if cfg.use_slippage else "미적용"
        return (
            f"- **비용 가정**: 수수료 {comm} · 슬리피지 {slip} · 매도세 {tax}. "
            "⚠️ 국내 주식형 ETF는 실제 매도세 면제이므로 use_tax=True면 비용 과대계상"
            "(보수적). 종목군에 맞게 use_tax로 조정하라."
        )
