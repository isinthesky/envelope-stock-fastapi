#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

# --- How to run ---
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly:
#      uv run python scripts/common/print_backtest_cost_schedule.py --date YYYY-MM-DD
# 3. Or make executable and run:
#      chmod +x scripts/common/print_backtest_cost_schedule.py
#      ./scripts/common/print_backtest_cost_schedule.py --date YYYY-MM-DD
# ------------------

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Sequence

from src.application.domain.backtest.cost_schedule import (
    UnsupportedBacktestCostDateError,
    get_backtest_cost_schedule,
)


@dataclass(frozen=True, slots=True)
class CostScheduleCommand:
    selected_date: date


@dataclass(frozen=True, slots=True)
class CommandLineError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def parse_command(args: Sequence[str]) -> CostScheduleCommand:
    match args:
        case ["--date", raw_date]:
            try:
                selected_date = date.fromisoformat(raw_date)
            except ValueError as exc:
                raise CommandLineError(
                    message=f"invalid --date {raw_date!r}; expected YYYY-MM-DD",
                ) from exc
            return CostScheduleCommand(selected_date=selected_date)
        case _:
            raise CommandLineError(
                message=(
                    "usage: uv run python scripts/common/print_backtest_cost_schedule.py "
                    "--date YYYY-MM-DD"
                ),
            )


def format_rate(rate: Decimal) -> str:
    return f"{rate} ({rate * Decimal('100')}%)"


def run(command: CostScheduleCommand) -> int:
    schedule = get_backtest_cost_schedule(command.selected_date)
    print(f"date: {command.selected_date}")
    print(f"effective_from: {schedule.effective_from}")
    print(f"commission: {format_rate(schedule.default_commission_rate)}")
    print(f"sell tax: {format_rate(schedule.sell_tax_rate)}")
    print(f"slippage: {format_rate(schedule.default_slippage_rate)}")
    print(f"price_tick: {schedule.price_tick}")
    print(f"source label: {schedule.source_label}")
    return 0


def main(args: Sequence[str] | None = None) -> int:
    command_args = sys.argv[1:] if args is None else args
    try:
        command = parse_command(command_args)
        return run(command)
    except CommandLineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except UnsupportedBacktestCostDateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
