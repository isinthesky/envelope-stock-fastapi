# -*- coding: utf-8 -*-
"""
Go/No-Go Gates (P5) — 실자산 투입 정당화 게이트 (순수 로직)

설계 §9: walk-forward OOS 집계가 아래를 **동시에** 충족해야만 실자산 투입을
정당화한다. 하나라도 미달이면 **NO-GO → paper-trade로 회부**.

    G1 DSR ≥ 0.95              (우연과 구분)
    G2 OOS Sharpe(비용후) ≥ 1.0
    G3 벤치 대비 초과수익 > 0   (약세장 포함 전 구간)
    G4 약세장 MDD 벤치 대비 개선/동등
    G5 PBO ≤ 0.2               (과적합 신호 없음)
    G6 IS→OOS Sharpe 감쇠 ≤ 30%
    G7 슬리피지 2배에도 초과수익 유지 (비용 민감도)

핵심 원칙:
    - **NA(근거 부족)도 GO를 막는다.** 벤치/민감도 미제공 게이트는 통과가 아니라
      "판정 불가"로 남고, 그러면 최종 verdict는 GO가 될 수 없다(보수적).
    - 이 판정은 자동 실전 전환이 아니다. 사람의 최종 결정을 위한 **하드 근거**다.

DB/외부 의존 없음 → 완전 단위 테스트 가능. WalkForwardReport에서 primitive를
뽑는 헬퍼(`gate_inputs_from_report`)와 순수 판정(`evaluate_gates`)을 분리한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Status = Literal["PASS", "FAIL", "NA"]
Verdict = Literal["GO", "NO_GO", "INCOMPLETE"]


@dataclass(frozen=True, slots=True)
class GateThresholds:
    min_dsr: float = 0.95
    min_oos_sharpe: float = 1.0
    min_excess_return: float = 0.0  # OOS 전략 - 벤치 (percentage point)
    max_pbo: float = 0.2
    max_is_oos_decay: float = 0.30  # IS 대비 OOS Sharpe 감쇠 허용 비율
    min_oos_trading_days: int = 250  # 표본 충분성(약 1년)


@dataclass(frozen=True, slots=True)
class GateInputs:
    """게이트 판정에 필요한 primitive. report/벤치/민감도에서 추출."""

    dsr: float
    oos_sharpe: float
    oos_total_return_pct: float
    oos_trading_days: int
    pbo: float | None = None
    mean_train_sharpe: float | None = None
    mean_test_sharpe: float | None = None
    strat_bear_mdd: float | None = None  # 전략 약세장 MDD(%, 음수)
    benchmark_oos_return_pct: float | None = None
    benchmark_bear_mdd: float | None = None  # 벤치 약세장 MDD(%, 음수)
    slippage_2x_positive: bool | None = None  # 슬리피지 2배에도 초과수익 양(+)?


@dataclass(frozen=True, slots=True)
class GateCheck:
    key: str
    name: str
    status: Status
    detail: str


@dataclass(frozen=True, slots=True)
class GateResult:
    verdict: Verdict
    checks: list[GateCheck] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    na: int = 0
    reason: str = ""

    def markdown(self) -> str:
        icon = {"GO": "🟢 GO", "NO_GO": "🔴 NO-GO", "INCOMPLETE": "🟡 INCOMPLETE"}[self.verdict]
        lines = [
            "## Go/No-Go 게이트 (P5 — 실자산 투입 판정)",
            "",
            f"### 최종 판정: **{icon}**",
            "",
            f"> {self.reason}",
            "",
            f"- PASS {self.passed} / FAIL {self.failed} / NA {self.na} (총 {len(self.checks)})",
            "",
            "| Gate | 항목 | 상태 | 근거 |",
            "| --- | --- | :---: | --- |",
        ]
        smap = {"PASS": "✅", "FAIL": "❌", "NA": "➖"}
        for c in self.checks:
            lines.append(f"| {c.key} | {c.name} | {smap[c.status]} | {c.detail} |")
        lines.append("")
        lines.append(
            "> ⚠️ **NA(근거 부족)도 GO를 막는다.** 벤치/민감도 미제공 게이트는 "
            "통과가 아니라 판정 불가다. 하나라도 FAIL이면 실자산 금지 → paper-trade 회부."
        )
        lines.append("")
        return "\n".join(lines)


def _is_nan(x: float | None) -> bool:
    return x is None or x != x  # None 또는 NaN


def _num(x: float | None) -> float | None:
    """유효한 실수면 그대로, None/NaN이면 None(mypy narrowing용)."""
    if x is None or x != x:
        return None
    return x


def evaluate_gates(inp: GateInputs, thresholds: GateThresholds | None = None) -> GateResult:
    """primitive 입력으로 7개 게이트를 판정한다."""
    t = thresholds or GateThresholds()
    checks: list[GateCheck] = []

    # G1 DSR ≥ 0.95
    if _is_nan(inp.dsr):
        checks.append(GateCheck("G1", "DSR ≥ 0.95", "NA", "DSR 산출 불가"))
    else:
        ok = inp.dsr >= t.min_dsr
        checks.append(
            GateCheck(
                "G1",
                "DSR ≥ 0.95",
                "PASS" if ok else "FAIL",
                f"DSR={inp.dsr:.3f} (기준 {t.min_dsr})",
            )
        )

    # G2 OOS Sharpe(비용후) ≥ 1.0
    if _is_nan(inp.oos_sharpe):
        checks.append(GateCheck("G2", "OOS Sharpe ≥ 1.0", "NA", "Sharpe 산출 불가"))
    else:
        ok = inp.oos_sharpe >= t.min_oos_sharpe
        # 표본 충분성도 함께 확인(며칠 안 되는 OOS로 Sharpe 판정 금지)
        if inp.oos_trading_days < t.min_oos_trading_days:
            checks.append(
                GateCheck(
                    "G2",
                    "OOS Sharpe ≥ 1.0",
                    "NA",
                    f"OOS {inp.oos_trading_days}일 < 최소 {t.min_oos_trading_days}일(표본 부족)",
                )
            )
        else:
            checks.append(
                GateCheck(
                    "G2",
                    "OOS Sharpe ≥ 1.0",
                    "PASS" if ok else "FAIL",
                    f"OOS Sharpe={inp.oos_sharpe:.3f} (기준 {t.min_oos_sharpe})",
                )
            )

    # G3 벤치 대비 초과수익 > 0
    bench_ret = _num(inp.benchmark_oos_return_pct)
    if bench_ret is None:
        checks.append(GateCheck("G3", "벤치 초과수익 > 0", "NA", "벤치 OOS 수익 미제공"))
    else:
        excess = inp.oos_total_return_pct - bench_ret
        ok = excess > t.min_excess_return
        checks.append(
            GateCheck(
                "G3",
                "벤치 초과수익 > 0",
                "PASS" if ok else "FAIL",
                f"전략 {inp.oos_total_return_pct:.2f}% − 벤치 "
                f"{bench_ret:.2f}% = {excess:+.2f}%p",
            )
        )

    # G4 약세장 MDD 벤치 대비 개선/동등 (MDD는 음수 → 전략 ≥ 벤치면 덜 나쁨)
    strat_mdd = _num(inp.strat_bear_mdd)
    bench_mdd = _num(inp.benchmark_bear_mdd)
    if strat_mdd is None or bench_mdd is None:
        checks.append(GateCheck("G4", "약세장 MDD ≤ 벤치", "NA", "약세장 MDD 미제공"))
    else:
        ok = strat_mdd >= bench_mdd
        checks.append(
            GateCheck(
                "G4",
                "약세장 MDD ≤ 벤치",
                "PASS" if ok else "FAIL",
                f"전략 {strat_mdd:.2f}% vs 벤치 {bench_mdd:.2f}%",
            )
        )

    # G5 PBO ≤ 0.2
    pbo = _num(inp.pbo)
    if pbo is None:
        checks.append(GateCheck("G5", "PBO ≤ 0.2", "NA", "PBO 정의 불가(후보 1개)"))
    else:
        ok = pbo <= t.max_pbo
        checks.append(
            GateCheck(
                "G5", "PBO ≤ 0.2", "PASS" if ok else "FAIL", f"PBO={pbo:.3f} (기준 {t.max_pbo})"
            )
        )

    # G6 IS→OOS Sharpe 감쇠 ≤ 30%
    mean_train = _num(inp.mean_train_sharpe)
    mean_test = _num(inp.mean_test_sharpe)
    if mean_train is None or mean_test is None:
        checks.append(GateCheck("G6", "IS→OOS 감쇠 ≤ 30%", "NA", "train/test Sharpe 미제공"))
    elif mean_train <= 0:
        # IS Sharpe가 이미 ≤0이면 "유지할 알파"가 없다 → 감쇠 개념 무의미.
        # 절대 성과(G2)에서 이미 걸리므로 여기선 판정 불가로 남긴다.
        checks.append(
            GateCheck(
                "G6",
                "IS→OOS 감쇠 ≤ 30%",
                "NA",
                f"IS Sharpe {mean_train:.2f}≤0 — 감쇠 정의 불가",
            )
        )
    else:
        decay = (mean_train - mean_test) / mean_train
        ok = decay <= t.max_is_oos_decay and mean_test > 0
        checks.append(
            GateCheck(
                "G6",
                "IS→OOS 감쇠 ≤ 30%",
                "PASS" if ok else "FAIL",
                f"IS {mean_train:.2f}→OOS {mean_test:.2f} (감쇠 {decay*100:.0f}%)",
            )
        )

    # G7 슬리피지 2배 민감도
    if inp.slippage_2x_positive is None:
        checks.append(GateCheck("G7", "슬리피지 2배 초과수익 유지", "NA", "비용 민감도 미측정"))
    else:
        ok = inp.slippage_2x_positive
        checks.append(
            GateCheck(
                "G7",
                "슬리피지 2배 초과수익 유지",
                "PASS" if ok else "FAIL",
                "2배에도 초과수익 유지" if ok else "2배에서 초과수익 소멸",
            )
        )

    passed = sum(1 for c in checks if c.status == "PASS")
    failed = sum(1 for c in checks if c.status == "FAIL")
    na = sum(1 for c in checks if c.status == "NA")

    if failed > 0:
        verdict: Verdict = "NO_GO"
        fails = ", ".join(c.key for c in checks if c.status == "FAIL")
        reason = f"게이트 {failed}개 미달({fails}) → 실자산 금지, paper-trade로 회부."
    elif na > 0:
        verdict = "INCOMPLETE"
        nas = ", ".join(c.key for c in checks if c.status == "NA")
        reason = (
            f"미달은 없으나 근거 부족 게이트 {na}개({nas}) → GO 불가. "
            "누락 근거(벤치/민감도)를 채워 재판정 필요."
        )
    else:
        verdict = "GO"
        reason = "전 게이트 통과. 단, 자동 실전 전환 아님 — 사람의 최종 결정·리스크 점검 필수."

    return GateResult(
        verdict=verdict, checks=checks, passed=passed, failed=failed, na=na, reason=reason
    )


def gate_inputs_from_report(
    report: Any,
    *,
    benchmark_oos_return_pct: float | None = None,
    benchmark_bear_mdd: float | None = None,
    slippage_2x_positive: bool | None = None,
) -> GateInputs:
    """WalkForwardReport(oos/stats/folds)에서 GateInputs를 추출한다.

    report는 walk_forward_runner.WalkForwardReport를 기대하지만, 순수 duck-typing으로
    받아 순환 import를 피한다(oos: dict, stats: dict, folds: list[FoldOutcome]).
    """
    oos = report.oos or {}
    stats = report.stats or {}
    regime = stats.get("regime") or {}
    bear = regime.get("bear") or {}

    # fold별 train/test Sharpe 평균(OOS가 있는 fold만)
    train_sharpes = [f.train.get("sharpe") for f in report.folds if f.test and f.train]
    test_sharpes = [f.test.get("sharpe") for f in report.folds if f.test]
    train_sharpes = [s for s in train_sharpes if s is not None]
    test_sharpes = [s for s in test_sharpes if s is not None]
    mean_train = sum(train_sharpes) / len(train_sharpes) if train_sharpes else None
    mean_test = sum(test_sharpes) / len(test_sharpes) if test_sharpes else None

    return GateInputs(
        dsr=stats.get("deflated_sharpe", float("nan")),
        oos_sharpe=oos.get("sharpe", float("nan")),
        oos_total_return_pct=oos.get("total_return", float("nan")),
        oos_trading_days=int(oos.get("trading_days", 0)),
        pbo=stats.get("pbo"),
        mean_train_sharpe=mean_train,
        mean_test_sharpe=mean_test,
        strat_bear_mdd=bear.get("mdd"),
        benchmark_oos_return_pct=benchmark_oos_return_pct,
        benchmark_bear_mdd=benchmark_bear_mdd,
        slippage_2x_positive=slippage_2x_positive,
    )
