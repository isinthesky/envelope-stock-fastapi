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

from bisect import bisect_left
from dataclasses import dataclass, field
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
    PortfolioExecutionOptions,
    PortfolioParityEngine,
)
from src.application.domain.backtest.regime import (
    classify_regimes,
    decompose_by_regime,
    regime_summary_dict,
)
from src.application.domain.backtest.regime_filter import (
    RegimeEntryFilter,
    compute_allowed_entry_dates,
)
from src.application.domain.backtest.statistics import (
    bootstrap_sharpe_ci,
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
)
from src.application.domain.backtest.walk_forward_windows import WalkForwardWindow
from src.application.domain.strategy.dto import GoldenCrossConfigDTO


@dataclass(frozen=True, slots=True)
class WalkForwardCandidate:
    label: str
    config: GoldenCrossConfigDTO
    # 진입 국면 필터(하락/횡보장 회피). None이면 게이트 미적용(기존 동작).
    regime_filter: RegimeEntryFilter | None = None


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
    test_eligible_symbols: int | None = None  # pit 모드: test 시작 시점 편입 수


@dataclass(frozen=True, slots=True)
class WalkForwardReport:
    folds: list[FoldOutcome]
    oos: dict
    markdown: str
    candidates: int
    trials: int  # 총 시도(후보×fold) — 데이터 스누핑 보정(P4 DSR) 입력
    oos_daily_returns: list[float] = field(default_factory=list)
    stats: dict = field(default_factory=dict)  # DSR/PBO/bootstrap(P4)
    # 연구 진단(추가 필드): 날짜가 붙은 연속 OOS 수익 / 일별 투자비중(포지션가치/자산)
    oos_dated_returns: list[tuple[datetime, float]] = field(default_factory=list)
    oos_exposure: list[tuple[datetime, float]] = field(default_factory=list)


def _metrics(result: BacktestResultDTO) -> dict:
    return {
        "total_return": result.total_return,
        "cagr": result.cagr,
        "sharpe": result.sharpe_ratio,
        "sharpe_rf0": result.sharpe_ratio_rf0,
        "mdd": result.mdd,
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
        "win_rate": result.win_rate,
    }


def stitch_oos_segments(
    segments: list[list[DailyStatsDTO]], initial_capital: Decimal
) -> tuple[dict, list[tuple[datetime, float]]]:
    """fold별 OOS 일별 통계를 이어붙여 (집계지표 dict, 날짜가 붙은 연속 OOS 일별수익)을 반환.

    `WalkForwardRunner._stitch_oos`의 본체(동작 동일). 다른 연구 엔진(모멘텀 등)이
    같은 정의로 OOS를 집계하도록 모듈 함수로 노출한다.
    """
    segments = [s for s in segments if s]
    empty = {
        "total_return": 0.0,
        "cagr": 0.0,
        "sharpe": 0.0,
        "sharpe_rf0": 0.0,
        "mdd": 0.0,
        "trading_days": 0,
        "folds": 0,
    }
    if not segments:
        return empty, []
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
    oos_dated: list[tuple[datetime, float]] = []
    for dt, r in sorted(per_day, key=lambda x: x[0]):
        d = dt.date() if hasattr(dt, "date") else dt
        if d in seen:
            continue
        seen.add(d)
        equities.append(equities[-1] * (1.0 + r))
        dates.append(dt)
        oos_dated.append((dt, r))

    if len(equities) < 2:
        return {**empty, "folds": len(segments)}, []
    # equities[0]=c0 에 첫 날짜를 붙여 길이를 맞춘다.
    dates = [dates[0]] + dates
    final = equities[-1]
    total_return = (final / c0 - 1.0) * 100.0
    start_dt, end_dt = dates[0], dates[-1]
    years = max((end_dt - start_dt).days / 365.0, 1e-9)
    cagr = PerformanceMetrics.calculate_cagr(Decimal(str(c0)), Decimal(str(final)), years)
    mdd = PerformanceMetrics.calculate_mdd([Decimal(str(e)) for e in equities])["mdd"]
    equity_df = pd.DataFrame({"timestamp": dates, "equity": equities})
    # Sharpe: 일별 초과수익(rf 연3%→일별) 기준 연환산. sharpe_rf0는 DSR과 같은 기준.
    sharpe = PerformanceMetrics.calculate_daily_sharpe_ratio(equity_df, risk_free_rate=3.0)
    sharpe_rf0 = PerformanceMetrics.calculate_daily_sharpe_ratio(equity_df, risk_free_rate=0.0)
    return (
        {
            "total_return": round(total_return, 2),
            "cagr": round(cagr, 2),
            "sharpe": round(sharpe, 3),
            "sharpe_rf0": round(sharpe_rf0, 3),
            "mdd": round(mdd, 2),
            "trading_days": len(seen),
            "folds": len(segments),
        },
        oos_dated,
    )


def stitch_oos_exposure(segments: list[list[DailyStatsDTO]]) -> list[tuple[datetime, float]]:
    """OOS 일별 투자비중(position_value/equity). 날짜 dedup 규칙은 수익 스티칭과 동일(최초 관측)."""
    per_day: list[tuple[datetime, float]] = []
    for seg in segments:
        for st in seg:
            eq = float(st.equity)
            per_day.append((st.date, float(st.position_value) / eq if eq > 0 else 0.0))
    seen: set[date] = set()
    out: list[tuple[datetime, float]] = []
    for dt, x in sorted(per_day, key=lambda p: p[0]):
        d = dt.date() if hasattr(dt, "date") else dt
        if d in seen:
            continue
        seen.add(d)
        out.append((dt, x))
    return out


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
        benchmark: pd.DataFrame | None = None,
        regime_long_ma: int = 200,
        n_trials: int | None = None,
        execution: PortfolioExecutionOptions | None = None,
        eligibility: str = "legacy",
    ) -> None:
        """
        Args:
            n_trials: DSR 선택편향 보정에 쓸 **누적 연구 시도 수**(이번 실행 외의 과거
                그리드/ablation/A-B 포함). 연구자가 반드시 설정해야 한다. 미지정 시
                이번 실행의 시도 수(후보×fold, 최소 후보 수)로 대체하고 리포트에
                경고를 남긴다(숫자를 지어내지 않는다).
            execution: 체결/사이징/현금 연구 옵션(None=기존 엔진 동작).
            eligibility: "legacy"(기본: train 시작 전 워밍업 + test_end까지 데이터 +
                창 커버리지 ≥ min_fold_coverage — test_end 생존 조건은 미래 정보) |
                "pit"(point-in-time: 각 구간 시작일 **이전** 자체 바가
                lookback_trading_days 이상인 종목만 편입. train/test 각각 판정,
                미래 데이터 조건 없음).
        """
        if not candidates:
            raise ValueError("at least one candidate config required")
        self.candidates = candidates
        self.constraints = constraints or PortfolioConstraints()
        self.backtest_config = backtest_config or BacktestConfigDTO()
        self.selection_metric = selection_metric
        self.min_fold_coverage = min_fold_coverage
        # 국면 분해용 벤치마크(예: KODEX 200). 없으면 regime 섹션 생략.
        self.benchmark = benchmark
        self.regime_long_ma = regime_long_ma
        if n_trials is not None and n_trials < 1:
            raise ValueError("n_trials must be >= 1")
        self.n_trials = n_trials
        self.execution = execution
        if eligibility not in ("legacy", "pit"):
            raise ValueError(f"unsupported eligibility rule: {eligibility}")
        self.eligibility = eligibility
        if lookback_trading_days is None:
            long = max(c.config.ma_config.long_period for c in candidates)
            lookback_trading_days = long + 30
        self.lookback_trading_days = lookback_trading_days
        # 진입 국면 필터별 허용일 캐시(동일 필터 재계산 방지)
        self._allowed_cache: dict[RegimeEntryFilter, set[date] | None] = {}

    def _allowed_dates_for(self, filt: RegimeEntryFilter | None) -> set[date] | None:
        """후보 필터에 대한 진입 허용일 집합(벤치마크 기준). 필터/벤치 없으면 None."""
        if filt is None or self.benchmark is None:
            return None
        if filt not in self._allowed_cache:
            self._allowed_cache[filt] = compute_allowed_entry_dates(self.benchmark, filt)
        return self._allowed_cache[filt]

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
        trial_sharpes: list[float] = []  # 모든 시도의 per-period Sharpe(DSR SR0용)
        cand_fold_matrix: list[list[float]] = []  # (fold, candidate) train Sharpe(PBO용)

        for w in windows:
            lb_start = self._lookback_start(days, day_index, w.train_start)
            if self.eligibility == "pit":
                eligible = [
                    sym for sym in panels if self._eligible_pit(symbol_dates[sym], w.train_start)
                ]
            else:
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
            fold_row: list[float] = []
            for cand in self.candidates:
                trials += 1
                engine = PortfolioParityEngine(cand.config, self.constraints, self.execution)
                res = engine.run(
                    train_slice,
                    self.backtest_config,
                    active_from=w.train_start,
                    entry_allowed_dates=self._allowed_dates_for(cand.regime_filter),
                )
                value = self._metric_value(res.result)
                sp = self._daily_sharpe(res.result.daily_stats)
                fold_row.append(sp)
                trial_sharpes.append(sp)
                if best_value is None or value > best_value:
                    best_value = value
                    best_candidate = cand
                    best_result = res.result
            cand_fold_matrix.append(fold_row)

            assert best_candidate is not None and best_result is not None
            selected_hash = self._freeze(best_candidate)

            # 2) 동결 config로 OOS test (fold마다 플랫 시작)
            test_lb_start = self._lookback_start(days, day_index, w.test_start)
            test_symbols = (
                [sym for sym in panels if self._eligible_pit(symbol_dates[sym], w.test_start)]
                if self.eligibility == "pit"
                else eligible
            )
            test_slice = {
                sym: self._slice(panels[sym], test_lb_start, w.test_end) for sym in test_symbols
            }
            test_engine = PortfolioParityEngine(
                best_candidate.config, self.constraints, self.execution
            )
            test_res = test_engine.run(
                test_slice,
                self.backtest_config,
                active_from=w.test_start,
                entry_allowed_dates=self._allowed_dates_for(best_candidate.regime_filter),
            )

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
                    test_eligible_symbols=(
                        len(test_symbols) if self.eligibility == "pit" else None
                    ),
                )
            )
            oos_segments.append(test_res.result.daily_stats)

        oos, oos_dated = self._stitch_oos(oos_segments, self.backtest_config.initial_capital)
        oos_returns = [r for _, r in oos_dated]
        stats = self._overfitting_stats(oos_returns, trial_sharpes, cand_fold_matrix, trials)
        # 국면 분해(벤치마크 제공 시): 2022 약세장 OOS 성과 격리
        if self.benchmark is not None and oos_dated:
            regimes = classify_regimes(self.benchmark, long_ma=self.regime_long_ma)
            decomp = decompose_by_regime(oos_dated, regimes)
            stats["regime"] = regime_summary_dict(decomp)
        markdown = self._report_md(folds, oos, trials, stats)
        return WalkForwardReport(
            folds=folds,
            oos=oos,
            markdown=markdown,
            candidates=len(self.candidates),
            trials=trials,
            oos_daily_returns=oos_returns,
            stats=stats,
            oos_dated_returns=oos_dated,
            oos_exposure=stitch_oos_exposure(oos_segments),
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

    def _eligible_pit(self, sdates: list[date], anchor: date) -> bool:
        """point-in-time: anchor **이전** 자체 바 수 ≥ lookback_trading_days."""
        return bisect_left(sdates, anchor) >= self.lookback_trading_days

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

    @staticmethod
    def _daily_sharpe(daily_stats: list[DailyStatsDTO]) -> float:
        """일별 통계에서 per-period(일별) Sharpe를 계산한다(무거래=0)."""
        rets = [float(s.daily_return) / 100.0 for s in daily_stats[1:]]
        if len(rets) < 2:
            return 0.0
        import statistics as _st

        sd = _st.pstdev(rets)
        return (_st.fmean(rets) / sd) if sd > 0 else 0.0

    def _overfitting_stats(
        self,
        oos_returns: list[float],
        trial_sharpes: list[float],
        cand_fold_matrix: list[list[float]],
        trials_in_run: int | None = None,
    ) -> dict:
        """DSR / PBO / bootstrap CI를 산출한다(과적합 정량화).

        DSR 기준: per-period(일별) Sharpe, **rf=0**(Bailey & López de Prado 원식 입력).
        OOS 헤드라인 `sharpe`는 rf 3% 초과수익 기준이므로, 동일 기준 비교용으로
        `sharpe_rf0`(=observed_daily_sharpe×√252)를 함께 보고한다.
        """
        in_run = trials_in_run if trials_in_run is not None else len(trial_sharpes)
        # 기본값은 이번 실행 시도 수(후보×fold)와 후보 수 중 큰 값 — 기존 기본(N=후보×fold)
        # 보다 느슨해지지 않게 한다. 연구자 제공값이 있으면 그보다 작아지지 않는다.
        default_n = max(in_run, len(self.candidates))
        n_trials = max(self.n_trials, default_n) if self.n_trials is not None else default_n
        dsr = deflated_sharpe_ratio(oos_returns, trial_sharpes, n_trials=n_trials)
        ci = bootstrap_sharpe_ci(oos_returns)
        # PBO: 행렬을 (fold × candidate)로. 후보 1개면 PBO 정의 불가(nan).
        pbo = (
            probability_of_backtest_overfitting(cand_fold_matrix)
            if cand_fold_matrix and len(cand_fold_matrix[0]) >= 2
            else float("nan")
        )
        return {
            "deflated_sharpe": dsr.deflated_sharpe,
            "observed_daily_sharpe": dsr.observed_sharpe,
            "expected_max_sharpe": dsr.expected_max_sharpe,
            "n_trials": dsr.n_trials,
            "n_trials_in_run": in_run,
            "n_trials_supplied": self.n_trials,
            "n_trials_source": (
                "researcher_supplied" if self.n_trials is not None else "default_in_run_only"
            ),
            "n_obs": dsr.n_obs,
            "pbo": round(pbo, 4) if pbo == pbo else None,
            "oos_sharpe_ci_low": round(ci.low, 4),
            "oos_sharpe_ci_high": round(ci.high, 4),
        }

    def _stitch_oos(
        self, segments: list[list[DailyStatsDTO]], initial_capital: Decimal
    ) -> tuple[dict, list[tuple[datetime, float]]]:
        """(집계지표 dict, 날짜가 붙은 연속 OOS 일별수익)을 반환한다."""
        return stitch_oos_segments(segments, initial_capital)

    @staticmethod
    def _regime_lines(regime: dict | None) -> list[str]:
        if not regime:
            return []
        lines = [
            "### 국면별 OOS 분해 (강세장 수익은 무의미 — 약세장 성과가 핵심)",
            "",
            "| Regime | Days | Return% | Daily Sharpe | MDD% |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for name in ("bull", "bear", "chop"):
            m = regime.get(name)
            if not m:
                continue
            lines.append(
                f"| {name} | {m['n_days']} | {m['total_return']} "
                f"| {m['daily_sharpe']} | {m['mdd']} |"
            )
        lines.append("")
        lines.append(
            "> ⚠️ **bear 구간의 Return/MDD가 실질 합격 판정의 중심.** "
            "bull 구간 고수익만으로 판단 금지."
        )
        lines.append("")
        return lines

    def _report_md(self, folds: list[FoldOutcome], oos: dict, trials: int, stats: dict) -> str:
        pbo = stats.get("pbo")
        pbo_str = f"{pbo}" if pbo is not None else "n/a(후보 1개)"
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
            f"- CAGR: **{oos['cagr']}%** | Sharpe(rf 3%): **{oos['sharpe']}** | "
            f"Sharpe(rf 0, DSR 기준): {oos.get('sharpe_rf0')} | "
            f"MDD: **{oos['mdd']}%** | total_return: {oos['total_return']}%",
            "- Sharpe 정의: mean(일별수익 − rf_daily)/std(일별수익)×√252 "
            "(rf_daily=(1+rf)^(1/252)−1).",
            f"- OOS trading days: {oos['trading_days']} across {oos['folds']} folds",
            "",
            "## 과적합 정량화 (P4 — 이걸로 우연/과적합을 판별)",
            "",
            f"- **Deflated Sharpe**: {stats.get('deflated_sharpe')} "
            f"(관측 일별SR {stats.get('observed_daily_sharpe')} vs 기대최대 "
            f"{stats.get('expected_max_sharpe')}, N={stats.get('n_trials')}, "
            f"T={stats.get('n_obs')}) — **≥0.95 미만이면 우연과 구분 불가**",
            f"- DSR 시도 수 N={stats.get('n_trials')} "
            f"(출처: `{stats.get('n_trials_source')}`, 이번 실행 후보×fold="
            f"{stats.get('n_trials_in_run')}, 연구자 제공={stats.get('n_trials_supplied')})",
            *self._n_trials_warning(stats),
            f"- **PBO**: {pbo_str} — **≤0.2 초과면 과적합 신호**",
            f"- OOS 일별 Sharpe 95% CI: "
            f"[{stats.get('oos_sharpe_ci_low')}, {stats.get('oos_sharpe_ci_high')}]",
            "",
            *self._regime_lines(stats.get("regime")),
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

    @staticmethod
    def _n_trials_warning(stats: dict) -> list[str]:
        if stats.get("n_trials_source") == "researcher_supplied":
            return []
        return [
            "- ⚠️ **누적 연구 시도 수 미제공**: N은 이번 실행의 시도 수뿐이다. 과거 그리드/"
            "ablation/A-B 등 누적 시도(수백 회 가능)를 `n_trials`(CLI `--n-trials`)로 "
            "제공하지 않으면 DSR은 **과대평가**된다.",
        ]

    def _cost_assumption_line(self) -> str:
        cfg = self.backtest_config
        tax = "적용" if cfg.use_tax else "미적용"
        comm = "적용" if cfg.use_commission else "미적용"
        slip = "적용" if cfg.use_slippage else "미적용"
        etf = "면제(0%)" if cfg.etf_tax_exempt else "과세(보수적)"
        return (
            f"- **비용 가정**: 수수료 {comm} · 슬리피지 {slip} · 매도세 {tax} "
            f"(ETF 심볼 매도세 {etf}, 연도별 세율표는 cost_schedule). "
            "국내주식형 외 ETF의 매매차익 배당소득세 15.4%는 미반영."
        )
