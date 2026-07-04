# SCRIPTS KNOWLEDGE BASE

## OVERVIEW
Manual operational entrypoints for scans, strategy evaluation, and sell-risk
research/backfill. Treat them as production-adjacent tooling.

## STRUCTURE
```text
scripts/
|-- common/                         # reusable backtest/data/result helpers
|-- evaluate_strategy.py            # offline strategy evaluation (stock-backtest-offline skill entrypoint)
|-- simulate_golden_cross_strategy.py
|-- scan_and_filter.py              # API-driven scan/filter workflow
|-- validate_strategy_walk_forward.py
|-- optimize_with_stock_selection.py
|-- backfill_sell_risk_data.py
|-- research_sell_peak_rules.py
`-- verify_sell_risk_changes.sh     # containerized targeted verification
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Reusable backtest runner | `common/backtest_runner.py` | shared script execution helper |
| Synthetic data | `common/data_generator.py` | offline fixtures/data generation |
| Result summaries | `common/result_analyzer.py` | reporting helper |
| Strategy presets | `common/strategy_presets.py` | script-level preset definitions |
| Sell-risk verification | `verify_sell_risk_changes.sh` | `docker compose`, compileall, targeted pytest |
| Sell-risk backfill | `backfill_sell_risk_data.py` | DB-affecting historical data helper |
| Sell-rule research | `research_sell_peak_rules.py` | offline rule exploration |
| Walk-forward validation | `validate_strategy_walk_forward.py` | strategy validation workflow |

## CONVENTIONS
- Scripts may compose services for manual workflows, but reusable policy still belongs in
  `src/application/domain`.
- Prefer importing application services/settings over duplicating config parsing.
- Make DB-writing behavior explicit in names, logs, and arguments.
- Keep offline/evaluation scripts able to run without live order submission.
- Use `scripts/common/` for helpers shared by multiple scripts.

## ANTI-PATTERNS
- No hard-coded real credentials, account numbers, or Telegram chat IDs.
- No live order placement from scripts unless a user intentionally invokes an existing guarded path.
- Do not import from `_attic/`, generated coverage output, or local tool-state directories.
- Do not let one-off research scripts become the only source of production strategy logic.

## COMMANDS
```bash
python -m scripts.evaluate_strategy
python scripts/scan_and_filter.py
bash scripts/verify_sell_risk_changes.sh
```

## ARCHIVED

Moved to `_attic/cleanup_2026-07-04/`: `run_backtests.py`, `init_db_tables.py`,
`add_40_stocks.py`, `add_stocks_to_universe.py`, `activate_all_stocks.py`,
`evaluate_strategy_offline.py`.

`evaluate_strategy_offline.py` duplicated `evaluate_strategy.py`'s purpose (offline
synthetic-data strategy evaluation) with a standalone inline implementation. Kept
`evaluate_strategy.py` instead because: (1) it is the script actually documented and
invoked by the `.claude/skills/stock-backtest-offline/SKILL.md` skill (`uv run python -m
scripts.evaluate_strategy ...`), (2) it already composes `scripts/common/` (`data_generator`,
`strategy_presets`, `backtest_runner`, `result_analyzer`) instead of duplicating that logic
inline, and (3) its hardcoded strategy config in the offline script was identical to
`StrategyPresets.default_bollinger()`, so nothing unique was lost. The offline script's only
distinguishing bit — a stub that scans `logs/` for `*.log` files and prints a reminder to
compare with live trades — did no actual comparison, so it was not ported.
