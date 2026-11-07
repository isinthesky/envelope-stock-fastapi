# SCRIPTS KNOWLEDGE BASE

## OVERVIEW
Manual operational entrypoints for scans, strategy research, and sell-risk
backfill. Treat them as production-adjacent tooling.

관심사별로 분리되어 있다:
- `common/` — 재사용 헬퍼(백테스트 러너/데이터 생성/결과 분석/프리셋)
- `research/` — 오프라인 전략 연구·백테스트·워크포워드 실험 (라이브 경로 아님)
- `ops/` — 데이터 백필/시딩/스캔 등 운영 작업

## STRUCTURE
```text
scripts/
|-- common/                              # reusable backtest/data/result helpers
|   |-- backtest_runner.py
|   |-- data_generator.py
|   |-- result_analyzer.py
|   |-- strategy_presets.py              # golden_cross + backtest-config presets
|   `-- print_backtest_cost_schedule.py
|-- research/                            # offline strategy research (not live)
|   |-- run_walk_forward.py              # GoldenCrossParity walk-forward + regime A/B entrypoint
|   |-- validate_strategy_walk_forward.py
|   |-- research_sell_peak_rules.py
|   |-- verify_simple_vs_hybrid_sell.py
|   |-- fear_buy_*.py                    # counter-trend dip-buy experiments
|   |-- compare_market_fear_filters.py
|   |-- relaxed_fear_buy_medium.py
|   |-- full_backtest_new_rules.py
|   |-- validate_sell_analysis_history.py
|   |-- research_suite_20261106.py       # 2026-11-06 pre-registered suite → reports/research_2026-11-06_*
|   |-- entry_guard_eval_20261107.py     # SafetyGuard replay → reports/entry_guard_eval_20261107.json
|   |-- state_overlay_prereg_20261107.py # → docs/plans/state-overlay-*.md
|   `-- leverage_overlay_prereg_20261107.py # → docs/plans/leverage-overlay-*.md
|-- ops/                                 # operational data tooling
|   |-- backfill_2y.py
|   |-- backfill_analysis_history_highest_price.py  # dry-run by default, --apply writes
|   |-- backfill_kospi.py
|   |-- backfill_sell_risk_data.py       # DB-affecting historical data helper
|   |-- backfill_universe_with_coverage.py
|   |-- scan_and_filter.py               # API-driven scan/filter workflow
|   |-- seed_etf_universe.py
|   `-- hash_admin_password.py           # prints ADMIN_PASSWORD_HASH (scrypt)
`-- verify_sell_risk_changes.sh          # containerized targeted verification
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Reusable backtest runner | `common/backtest_runner.py` | shared script execution helper |
| Synthetic data | `common/data_generator.py` | offline fixtures/data generation |
| Result summaries | `common/result_analyzer.py` | reporting helper |
| Strategy presets | `common/strategy_presets.py` | golden_cross + backtest-config presets |
| Walk-forward validation | `research/run_walk_forward.py` | `walk_forward_runner` + `portfolio_parity_engine` (live-FSM parity), optional regime A/B |
| Research verdicts | `research/research_suite_20261106.py`, `*_prereg_20261107.py` | golden cross NO-GO, state overlay CONDITIONAL, 2x leverage NO-GO (`reports/research_2026-11-06_summary.md`, `docs/plans/*-result.md`) |
| Admin password hash | `ops/hash_admin_password.py` | output goes to `.env` `ADMIN_PASSWORD_HASH`; never commit it |
| Strategy validation workflow | `research/validate_strategy_walk_forward.py` | |
| Sell-rule research | `research/research_sell_peak_rules.py` | offline rule exploration |
| Sell-risk verification | `verify_sell_risk_changes.sh` | `docker compose`, compileall, targeted pytest |
| Sell-risk backfill | `ops/backfill_sell_risk_data.py` | DB-affecting historical data helper |
| API scan/filter | `ops/scan_and_filter.py` | |

## CONVENTIONS
- Scripts may compose services for manual workflows, but reusable policy still belongs in
  `src/application/domain`.
- Prefer importing application services/settings over duplicating config parsing.
- Make DB-writing behavior explicit in names, logs, and arguments.
- Keep offline/research scripts able to run without live order submission.
- Use `scripts/common/` for helpers shared by multiple scripts.
- Script entrypoints do not call `setup_logging()` yet, so INFO logs from services are not shown.

## ANTI-PATTERNS
- No hard-coded real credentials, account numbers, or Telegram chat IDs.
- No live order placement from scripts unless a user intentionally invokes an existing guarded path.
- Do not let one-off research scripts become the only source of production strategy logic.

## COMMANDS
```bash
python -m scripts.research.run_walk_forward
python scripts/ops/scan_and_filter.py
bash scripts/verify_sell_risk_changes.sh
```
