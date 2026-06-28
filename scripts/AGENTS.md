# SCRIPTS KNOWLEDGE BASE

## OVERVIEW
Manual operational entrypoints for scans, backtests, universe maintenance, DB initialization, and
sell-risk research/backfill. Treat them as production-adjacent tooling.

## STRUCTURE
```text
scripts/
|-- common/                         # reusable backtest/data/result helpers
|-- run_backtests.py                # manual backtest runner
|-- evaluate_strategy*.py           # online/offline strategy evaluation
|-- simulate_golden_cross_strategy.py
|-- scan_and_filter.py              # API-driven scan/filter workflow
|-- init_db_tables.py               # DB bootstrap helper
|-- add_*stocks*.py                 # universe maintenance helpers
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
| Universe seeding | `add_stocks_to_universe.py`, `add_40_stocks.py`, `activate_all_stocks.py` | DB-affecting helpers |

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
python scripts/run_backtests.py
python scripts/evaluate_strategy_offline.py
python scripts/scan_and_filter.py
bash scripts/verify_sell_risk_changes.sh
```
