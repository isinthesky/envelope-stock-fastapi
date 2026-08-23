#!/usr/bin/env python3
"""활성 매도 분석 행의 보유 종가 고점을 로컬 일봉으로 복원한다.

기본은 dry-run이며 ``--apply`` 때만 갱신한다. 보유 시작일을 별도로 저장하지
않던 과거 행은 최초 등록 시각(created_at)을 추적 시작점으로 사용한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select, update

from src.adapters.database.connection import AsyncSessionLocal
from src.adapters.database.models.analysis_history import AnalysisHistoryModel
from src.adapters.database.models.ohlcv import OHLCVModel
from src.application.domain.strategy.risk_contract import effective_peak_price


async def run(*, apply: bool, rebuild_from_close: bool = False) -> list[dict]:
    async with AsyncSessionLocal() as session:
        as_of = datetime.now(timezone.utc)
        history_query = select(AnalysisHistoryModel).where(
            AnalysisHistoryModel.analysis_type == "sell",
            AnalysisHistoryModel.is_active.is_(True),
        )
        if apply and rebuild_from_close:
            history_query = history_query.with_for_update()
        histories = list((await session.execute(history_query)).scalars().all())
        audit: list[dict] = []
        for row in histories:
            observed_close_peak = await session.scalar(
                select(func.max(OHLCVModel.close)).where(
                    func.trim(OHLCVModel.symbol) == row.symbol.strip(),
                    OHLCVModel.interval == "1d",
                    OHLCVModel.timestamp >= row.created_at,
                    OHLCVModel.timestamp <= as_of,
                )
            )
            effective = effective_peak_price(
                current_price=row.current_price,
                entry_price=row.entry_price,
                highest_price=(
                    observed_close_peak
                    if rebuild_from_close
                    else max(
                        [
                            value
                            for value in (row.highest_price, observed_close_peak)
                            if value is not None
                        ],
                        default=None,
                    )
                ),
            )
            changed = effective is not None and Decimal(str(effective)) != row.highest_price
            audit.append(
                {
                    "id": row.id,
                    "symbol": row.symbol.strip(),
                    "tracking_started_at": row.created_at.isoformat(),
                    "previous_highest_price": str(row.highest_price) if row.highest_price else None,
                    "observed_close_peak": (
                        str(observed_close_peak) if observed_close_peak else None
                    ),
                    "effective_highest_price": str(effective) if effective is not None else None,
                    "changed": changed,
                }
            )
            if apply and changed and effective is not None:
                candidate = Decimal(str(effective))
                value = (
                    candidate
                    if rebuild_from_close
                    else func.greatest(
                        func.coalesce(AnalysisHistoryModel.highest_price, candidate),
                        candidate,
                    )
                )
                await session.execute(
                    update(AnalysisHistoryModel)
                    .where(AnalysisHistoryModel.id == row.id)
                    .values(highest_price=value)
                )

        if apply:
            await session.commit()
        else:
            await session.rollback()
        return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="검토한 고점 값을 DB에 반영")
    parser.add_argument(
        "--rebuild-from-close",
        action="store_true",
        help="기존 값을 무시하고 등록 이후 종가 고점으로 교정(정의 변경 시에만 사용)",
    )
    parser.add_argument(
        "--maintenance-confirm",
        action="store_true",
        help="maintenance window에서 교정 UPDATE를 실행함을 명시적으로 확인",
    )
    args = parser.parse_args()
    if args.apply and args.rebuild_from_close and not args.maintenance_confirm:
        raise SystemExit("--apply --rebuild-from-close requires --maintenance-confirm")
    rows = asyncio.run(run(apply=args.apply, rebuild_from_close=args.rebuild_from_close))
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "peak_source": "daily_close",
                "rebuild_from_close": args.rebuild_from_close,
                "active_rows": len(rows),
                "changed_rows": sum(row["changed"] for row in rows),
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
