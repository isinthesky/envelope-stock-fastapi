#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pydantic>=2.9.0",
#     "pyyaml>=6.0.0",
# ]
# ///

# --- How to run ---
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run from the repository root:
#      uv run python scripts/validate_strategy_walk_forward.py --config examples/backtest/golden_cross_walk_forward.example.yaml --output .omo/evidence/task-6-strategy-validation-improvement-happy.md
# 3. Or make executable and run:
#      chmod +x scripts/validate_strategy_walk_forward.py && ./scripts/validate_strategy_walk_forward.py --config examples/backtest/golden_cross_walk_forward.example.yaml --output report.md
# ------------------

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from pydantic import ValidationError

from src.application.domain.backtest.validation import (
    WalkForwardValidationError,
    load_walk_forward_config,
)
from src.application.domain.backtest.walk_forward import WalkForwardValidationRunner


@dataclass(frozen=True, slots=True)
class CliArgs:
    config_path: Path
    output_path: Path


@dataclass(frozen=True, slots=True)
class CliUsageError(Exception):
    reason: str

    def __str__(self) -> str:
        return self.reason


def parse_args(argv: Sequence[str]) -> CliArgs:
    config_path: Path | None = None
    output_path: Path | None = None
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--config":
            config_path = _next_path(argv, index, "--config")
            index += 2
            continue
        if token == "--output":
            output_path = _next_path(argv, index, "--output")
            index += 2
            continue
        raise CliUsageError(f"unknown argument: {token}")
    if config_path is None:
        raise CliUsageError("--config is required")
    if output_path is None:
        raise CliUsageError("--output is required")
    return CliArgs(config_path=config_path, output_path=output_path)


def _next_path(argv: Sequence[str], index: int, flag: str) -> Path:
    value_index = index + 1
    if value_index >= len(argv):
        raise CliUsageError(f"{flag} requires a path")
    return Path(argv[value_index])


def run(args: CliArgs) -> Path:
    config = load_walk_forward_config(args.config_path.read_text(encoding="utf-8"))
    report = WalkForwardValidationRunner(config).run().to_markdown()
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(report, encoding="utf-8")
    return args.output_path


def main(argv: Sequence[str] | None = None) -> int:
    actual_argv = sys.argv[1:] if argv is None else argv
    try:
        output_path = run(parse_args(actual_argv))
    except (CliUsageError, WalkForwardValidationError, ValidationError) as exc:
        print(f"validation error: {exc}", file=sys.stderr)
        return 2
    print(f"wrote walk-forward validation report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
