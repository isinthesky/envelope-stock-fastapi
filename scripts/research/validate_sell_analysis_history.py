#!/usr/bin/env python3
"""Read-only post-validation of persisted sell recommendations against OHLCV."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from src.adapters.database.connection import AsyncSessionLocal
from src.adapters.database.models.analysis_history import AnalysisHistoryModel
from src.adapters.database.repositories.ohlcv_repository import OHLCVRepository
from src.application.domain.strategy.analysis_history_validation import (
    ForwardClose,
    SellRecommendationObservation,
    evaluate_sell_recommendations,
    render_sell_validation_markdown,
    resolve_historical_sell_stage,
)


async def run(output_dir: Path, limit: int) -> tuple[Path, Path]:
    async with AsyncSessionLocal() as session:
        statement = (
            select(AnalysisHistoryModel)
            .where(AnalysisHistoryModel.analysis_type == "sell")
            .order_by(AnalysisHistoryModel.analyzed_at)
            .limit(limit)
        )
        histories = list((await session.execute(statement)).scalars().all())
        observations = []
        for row in histories:
            resolved = resolve_historical_sell_stage(
                row.sell_stage,
                row.sell_phase,
                float(row.sell_ratio_min) if row.sell_ratio_min is not None else None,
                float(row.sell_ratio_max) if row.sell_ratio_max is not None else None,
            )
            if resolved is None:
                continue
            stage, ratio_min, ratio_max, stage_source = resolved
            observations.append(
                SellRecommendationObservation(
                    history_id=row.id,
                    symbol=row.symbol.strip(),
                    analyzed_at=row.analyzed_at,
                    signal_price=float(row.current_price),
                    sell_stage=stage,
                    sell_ratio_min=ratio_min,
                    sell_ratio_max=ratio_max,
                    stage_source=stage_source,
                )
            )
        closes_by_symbol: dict[str, list[ForwardClose]] = {}
        repo = OHLCVRepository(session)
        for symbol in sorted({row.symbol for row in observations}):
            symbol_rows = [row for row in observations if row.symbol == symbol]
            start = min(row.analyzed_at for row in symbol_rows)
            end = max(row.analyzed_at for row in symbol_rows) + timedelta(days=45)
            frame = await repo.get_candles_to_dataframe(symbol, start, end, "1d")
            closes_by_symbol[symbol] = [
                ForwardClose(timestamp=row.timestamp, close=float(row.close))
                for row in frame.itertuples()
            ]

    result = evaluate_sell_recommendations(observations, closes_by_symbol)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = "sell_analysis_history_forward_validation"
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    markdown_path.write_text(render_sell_validation_markdown(result), encoding="utf-8")
    return json_path, markdown_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--limit", type=int, default=10_000)
    args = parser.parse_args()
    json_path, markdown_path = asyncio.run(run(args.output_dir, args.limit))
    print(f"wrote {json_path}")
    print(f"wrote {markdown_path}")


if __name__ == "__main__":
    main()
