# -*- coding: utf-8 -*-
"""
Paper vs OOS Reconciliation (P6) — 실시간 paper 성과와 백테스트 OOS 괴리 측정

paper-trade(무비용 실시간 추적)가 백테스트 OOS 기대와 얼마나 벌어지는지 정량화한다.
괴리가 허용범위 안이면 '소액 실전 시작' 후보로 판정한다(설계 §10의 최종 관문).

⚠️ 이 판정은 자동 실전 전환을 의미하지 않는다. 사람의 명시적 결정을 위한 근거일 뿐.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.application.domain.paper_trade.ledger import PaperSummary


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    paper_daily_sharpe: float
    oos_daily_sharpe: float
    sharpe_gap: float  # paper - oos (음수면 실시간이 기대 미달)
    paper_win_rate: float
    paper_total_return: float
    min_closed_trades_met: bool
    within_tolerance: bool
    recommendation: str


def reconcile_paper_vs_oos(
    paper: PaperSummary,
    oos_daily_sharpe: float,
    *,
    min_closed_trades: int = 20,
    max_sharpe_shortfall: float = 0.5,
) -> ReconcileResult:
    """paper 요약과 OOS 일별 Sharpe를 비교한다.

    Args:
        paper: PaperLedger.summary()
        oos_daily_sharpe: 백테스트 OOS의 per-period Sharpe(WalkForwardReport.stats)
        min_closed_trades: 판정에 필요한 최소 청산 거래 수(표본 충분성)
        max_sharpe_shortfall: 허용 Sharpe 미달폭(paper가 OOS보다 이만큼 이상 낮으면 실격)
    """
    gap = round(paper.daily_sharpe - oos_daily_sharpe, 4)
    enough = paper.closed_trades >= min_closed_trades
    # paper가 OOS 대비 과도하게 낮지 않아야 하고, 표본이 충분해야 함
    within = enough and (gap >= -abs(max_sharpe_shortfall))

    if not enough:
        rec = (
            f"표본 부족(청산 {paper.closed_trades}/{min_closed_trades}). " "추적 지속 — 실전 금지."
        )
    elif within:
        rec = (
            "paper 성과가 OOS 기대 범위 내. 소액(전체의 5% 이하) 실전 시작 검토 가능 "
            "— 단, 사람의 최종 결정과 리스크 점검 필수."
        )
    else:
        rec = (
            f"paper Sharpe가 OOS 대비 {abs(gap)} 미달(허용 {max_sharpe_shortfall}). "
            "실전 금지 — 시그널/비용/체결 가정 재점검."
        )

    return ReconcileResult(
        paper_daily_sharpe=paper.daily_sharpe,
        oos_daily_sharpe=round(oos_daily_sharpe, 4),
        sharpe_gap=gap,
        paper_win_rate=paper.win_rate,
        paper_total_return=paper.total_return,
        min_closed_trades_met=enough,
        within_tolerance=within,
        recommendation=rec,
    )
