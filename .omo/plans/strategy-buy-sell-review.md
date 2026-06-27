# strategy-buy-sell-review - Work Plan

## TL;DR (For humans)
<!-- Fill this LAST, after the detailed plan below is written, so it summarizes the REAL plan. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**What you'll get:** A safer, auditable buy/sell strategy path: the buy recommendation and real execution rules will agree, and sell-stage decisions will be stored with the context needed to reproduce portfolio cash and notification outputs later.

**Why this approach:** The highest-risk finding is semantic drift, not a failing test: the dashboard buy signal and execution state machine can currently disagree. The sell side has strong live scoring, but key final-stage fields are not persisted, so historical decisions are less reliable than the live analysis.

**What it will NOT do:** It will not place live orders, replace the strategy with a different model, or clean unrelated dirty worktree changes.

**Effort:** Medium
**Risk:** High - this touches strategy semantics, persistence, and trading-adjacent execution paths.
**Decisions I made for you:** I treated the current golden-cross buy flow and sell-stage scoring flow as the production strategy, prioritized consistency and persistence before threshold tuning, and required dry-run/mocked QA for all trading-adjacent verification.

Your next move: approve execution with `$start-work .omo/plans/strategy-buy-sell-review.md`, or ask for a narrower scope. Full execution detail follows below.

---

> TL;DR (machine): Medium/high-risk plan to align golden-cross buy semantics, persist sell-stage decisions, configure sell thresholds, and verify strategy surfaces without live orders.

## Scope
### Must have
1. Align buy scan/recommendation and execution entry semantics so one shared predicate decides when a pullback recovery is a real buy entry.
2. Preserve current public buy scan states unless tests explicitly prove a necessary correction.
3. Persist sell `final_stage`, stage ratios, score summary, ADX/volume/personal/credit inputs, and enough threshold/version metadata to reproduce the decision later.
4. Keep sell analysis runtime behavior compatible while adding config seams for currently hard-coded thresholds.
5. Update portfolio cash plan and notification consumers to prefer persisted rich fields and fall back to live re-analysis only when needed.
6. Add focused regression tests plus one real-surface API/manual QA path for buy recommendation and sell/portfolio outputs.

### Must NOT have (guardrails, anti-slop, scope boundaries)
1. Must not place live KIS orders or require production credentials during verification.
2. Must not rewrite the strategy into a different Bollinger/Envelope or ML model.
3. Must not revert or normalize unrelated dirty worktree changes.
4. Must not hide strategy disagreements by changing display text only.
5. Must not weaken existing tests or silence type/lint failures.

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: tests-after for characterization gaps, then implementation tests. Use `uv run pytest` with focused domain/interface suites.
- Evidence directory: `.omo/evidence/strategy-buy-sell-review/`
- Manual QA surfaces:
  - Buy API: `curl -i 'http://127.0.0.1:8000/api/v1/strategies/universe/golden-cross-recommendations?limit=5&gc_only=true&top_n=3'`
  - Sell API: `curl -i 'http://127.0.0.1:8000/api/v1/strategies/sell-signal/005930?entry_price=70000'` using mocked/local data where credentials are unavailable.
  - Portfolio API: `curl -i 'http://127.0.0.1:8000/api/v1/strategies/portfolio-cash-plan?target_cash_ratio=0.30&current_cash_ratio=0.10'`
  - Binary PASS observable: HTTP 200 with JSON containing expected state/stage fields and no live order side effects.

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.
Wave 1 can run T1 and T2 in parallel after re-reading the current dirty files. T3 depends on T2's persistence shape. T4 depends on T2/T3. T5 depends on T1-T4. T6 is final verification.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| T1 Buy predicate alignment | none | T5, T6 | T2 |
| T2 Sell persistence schema and DTO mapping | none | T3, T4, T5, T6 | T1 |
| T3 Sell threshold config seam | T2 shape awareness | T4, T5, T6 | none after T2 starts |
| T4 Consumer surface updates | T2, T3 | T5, T6 | none |
| T5 Tests and manual QA harness | T1-T4 | T6 | none |
| T6 Final verification and review | T1-T5 | final handoff | none |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [ ] T1. Align golden-cross buy-entry semantics
  What to do / Must NOT do: Re-read `src/application/domain/strategy/signal_evaluator.py`, `src/application/domain/strategy/state_machine.py`, `src/application/domain/strategy/buy_strategy_service.py`, and `src/application/domain/strategy/golden_cross_engine.py`. Make execution and scan/recommendation share one buy-entry rule for pullback recovery. Prefer extracting a reusable evaluator method over duplicating conditionals. Preserve public states `NOT_GC`, `GC_ACTIVE`, `WAITING_FOR_PULLBACK`, `READY_TO_BUY`, `BUY_INTEREST`, `OPTIMAL_BUY`. Must not create a separate, second definition of "buy-ready".
  Parallelization: Wave 1 | Blocked by: none | Blocks: T5, T6
  References (executor has NO interview context - be exhaustive): `src/application/domain/strategy/signal_evaluator.py:29`, `src/application/domain/strategy/buy_strategy_service.py:607`, `src/application/domain/strategy/state_machine.py:204`, `src/application/domain/strategy/golden_cross_engine.py:280`, `tests/domain/test_golden_cross_strategy.py:1`, `tests/domain/test_golden_cross_engine_dry_run.py:1`
  Acceptance criteria (agent-executable): `uv run pytest tests/domain/test_golden_cross_strategy.py tests/domain/test_golden_cross_engine_dry_run.py tests/domain/test_golden_cross_recommendations.py`
  QA scenarios (name the exact tool + invocation): happy: run `uv run pytest tests/domain/test_golden_cross_strategy.py::TestDetermineGCState::test_optimal_buy_after_pullback_recovery -q`, evidence `.omo/evidence/strategy-buy-sell-review/t1-buy-happy.txt`; failure: add/keep a regression test where K is above strong recovery but falling or K<=D and assert execution does not emit BUY, then run that test, evidence `.omo/evidence/strategy-buy-sell-review/t1-buy-regression.txt`.
  Commit: Y | `fix(strategy): align golden-cross buy entry predicate`

- [ ] T2. Persist reproducible sell decision fields
  What to do / Must NOT do: Add `analysis_history` persistence for sell `final_stage`, `sell_stage`, `sell_ratio_min/max`, `final_ratio_min/max`, score summary, `volume_ratio`, `is_volume_spike`, `is_volume_sell_signal`, `adx`, `plus_di`, `minus_di`, `is_strong_uptrend`, `overbought_sell_blocked`, personal-flow overheat fields, market-credit fields, and a decision/config version string. Update model, migration, repository usage, `AnalysisHistoryCreateDTO`, `AnalysisHistoryDTO`, `save_analysis_history`, `refresh_analysis_history`, and `_history_to_dto`. Must not rely on live `sell_result` as the only source for rich fields after persistence.
  Parallelization: Wave 1 | Blocked by: none | Blocks: T3, T4, T5, T6
  References (executor has NO interview context - be exhaustive): `src/adapters/database/models/analysis_history.py:86`, `src/application/domain/strategy/dto.py:872`, `src/application/domain/strategy/dto.py:1015`, `src/application/domain/strategy/strategy_service.py:1330`, `src/application/domain/strategy/strategy_service.py:1753`, `src/application/domain/strategy/strategy_service.py:1881`, `tests/domain/test_analysis_history_save.py:1`
  Acceptance criteria (agent-executable): `uv run pytest tests/domain/test_analysis_history_save.py tests/domain/test_sell_strategy_personal_flow.py`
  QA scenarios (name the exact tool + invocation): happy: create a sell analysis history DTO with non-HOLD final stage and assert `_history_to_dto` returns the same persisted stage without a live `sell_result`, evidence `.omo/evidence/strategy-buy-sell-review/t2-persist-happy.txt`; failure: simulate missing live sell analysis in portfolio fallback and assert persisted stage is still used instead of forced HOLD, evidence `.omo/evidence/strategy-buy-sell-review/t2-fallback-regression.txt`.
  Commit: Y | `feat(strategy): persist sell decision context`

- [ ] T3. Move hard-coded sell thresholds behind versioned config
  What to do / Must NOT do: Extend `SellScoreSettings` or a dedicated sell decision config DTO for volume spike/sell threshold, ADX trend threshold, sharp-v1 stock/ETF/leveraged profit thresholds, and stage ratio defaults. Thread this config into `SellStrategyService` and persist the applied config/version through T2 fields. Must not change default behavior except where existing constants are copied into defaults.
  Parallelization: Wave 2 | Blocked by: T2 shape awareness | Blocks: T4, T5, T6
  References (executor has NO interview context - be exhaustive): `src/settings/sell_score_settings.py:10`, `src/application/domain/strategy/sell_strategy_service.py:1539`, `src/application/domain/strategy/sell_strategy_service.py:1620`, `src/application/domain/strategy/sell_strategy_service.py:1663`, `src/application/domain/strategy/sell_strategy_service.py:1722`, `src/application/domain/strategy/dto.py:872`, `docs/sell_strategy_status_and_requirements.md:1`
  Acceptance criteria (agent-executable): `uv run pytest tests/domain/test_sell_strategy_personal_flow.py tests/domain/test_sell_strategy_sharp_v1.py tests/domain/test_sell_rule_research_service.py`
  QA scenarios (name the exact tool + invocation): happy: instantiate `SellStrategyService` with default config and assert existing sharp-v1/personal-flow tests remain green, evidence `.omo/evidence/strategy-buy-sell-review/t3-defaults-happy.txt`; failure: instantiate with a stricter volume threshold and assert a 1.3x volume case no longer triggers volume spike/sell behavior, evidence `.omo/evidence/strategy-buy-sell-review/t3-config-regression.txt`.
  Commit: Y | `refactor(strategy): version sell decision thresholds`

- [ ] T4. Update strategy consumers to use persisted rich sell decisions
  What to do / Must NOT do: Update portfolio cash plan and notification scheduler paths to prefer persisted `final_stage`/score/volume/ADX fields, then optionally refresh live data when explicitly requested or stale. Keep live re-analysis as an enhancement, not a requirement for historical correctness. Must not break current notification dedupe/freshness behavior.
  Parallelization: Wave 3 | Blocked by: T2, T3 | Blocks: T5, T6
  References (executor has NO interview context - be exhaustive): `src/application/domain/strategy/strategy_service.py:1468`, `src/application/domain/strategy/strategy_service.py:1675`, `src/application/domain/strategy/notification_scheduler.py:947`, `tests/domain/test_portfolio_cash_plan.py:1`, `tests/domain/test_notification_scheduler.py:1`, `tests/domain/test_notification_scheduler_status.py:1`
  Acceptance criteria (agent-executable): `uv run pytest tests/domain/test_portfolio_cash_plan.py tests/domain/test_notification_scheduler.py tests/domain/test_notification_scheduler_status.py tests/domain/test_notification_scheduler_etf_summary.py`
  QA scenarios (name the exact tool + invocation): happy: run `uv run pytest tests/domain/test_portfolio_cash_plan.py -q` and capture persisted REDUCE/EXIT ordering, evidence `.omo/evidence/strategy-buy-sell-review/t4-cash-plan-happy.txt`; failure: mock live sell analysis failure and assert persisted non-HOLD stage remains in cash plan/notification candidates, evidence `.omo/evidence/strategy-buy-sell-review/t4-live-failure-regression.txt`.
  Commit: Y | `fix(strategy): use persisted sell stages in consumers`

- [ ] T5. Add API/manual QA coverage for strategy review surfaces
  What to do / Must NOT do: Add or update interface tests for golden-cross recommendations, sell signal analysis, and portfolio cash plan where feasible. Start a local server only with safe local/test settings. Use dry-run/mocked services for trading-adjacent behavior. Capture HTTP evidence. Must not require real KIS credentials.
  Parallelization: Wave 4 | Blocked by: T1-T4 | Blocks: T6
  References (executor has NO interview context - be exhaustive): `src/application/interface/api/strategy_router.py:156`, `src/application/interface/api/strategy_router.py:203`, `src/application/interface/api/strategy_router.py:476`, `src/application/interface/api/strategy_router.py:652`, `tests/interface/test_strategy_router_security.py:1`, `tests/interface/test_sell_strategy_page_router.py:1`
  Acceptance criteria (agent-executable): `uv run pytest tests/interface/test_strategy_router_security.py tests/interface/test_sell_strategy_page_router.py tests/domain/test_golden_cross_recommendations.py tests/domain/test_portfolio_cash_plan.py`
  QA scenarios (name the exact tool + invocation): happy: `curl -i 'http://127.0.0.1:8000/api/v1/strategies/universe/golden-cross-recommendations?limit=5&top_n=3'`, evidence `.omo/evidence/strategy-buy-sell-review/t5-buy-api.txt`; happy: `curl -i 'http://127.0.0.1:8000/api/v1/strategies/portfolio-cash-plan?target_cash_ratio=0.30&current_cash_ratio=0.10'`, evidence `.omo/evidence/strategy-buy-sell-review/t5-cash-api.txt`; failure: call sell signal for a symbol with mocked insufficient OHLCV and assert non-2xx/structured error without order side effects, evidence `.omo/evidence/strategy-buy-sell-review/t5-sell-error-api.txt`.
  Commit: Y | `test(strategy): cover strategy API decision surfaces`

- [ ] T6. Final verification, docs reconciliation, and handoff
  What to do / Must NOT do: Re-run focused strategy tests, run relevant type/lint checks for changed Python files, and update docs only where stale review/status docs would mislead operators. Summarize remaining trading assumptions. Must not update broad docs unrelated to buy/sell strategy.
  Parallelization: Wave 5 | Blocked by: T1-T5 | Blocks: final handoff
  References (executor has NO interview context - be exhaustive): `docs/sell-strategy/implementation-review.md:1`, `docs/sell_strategy_status_and_requirements.md:1`, `docs/strategy_guide.md:1`, `pyproject.toml`
  Acceptance criteria (agent-executable): `uv run pytest tests/domain/test_golden_cross_strategy.py tests/domain/test_golden_cross_recommendations.py tests/domain/test_golden_cross_engine_dry_run.py tests/domain/test_sell_strategy_personal_flow.py tests/domain/test_sell_strategy_sharp_v1.py tests/domain/test_sell_rule_research_service.py tests/domain/test_buy_strategy_financial_filter.py tests/domain/test_buy_strategy_scan_concurrency.py tests/domain/test_backtest_signal_generators.py tests/domain/test_portfolio_cash_plan.py`; plus `uv run mypy src/application/domain/strategy src/adapters/database/models src/adapters/database/repositories`
  QA scenarios (name the exact tool + invocation): happy: capture full focused test log, evidence `.omo/evidence/strategy-buy-sell-review/t6-tests.txt`; failure: capture mypy or route-test failure log with exact failing file/line before fixing, evidence `.omo/evidence/strategy-buy-sell-review/t6-failure-before-fix.txt`.
  Commit: Y | `docs(strategy): reconcile buy sell strategy review`

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [ ] F1. Plan compliance audit
- [ ] F2. Code quality review
- [ ] F3. Real manual QA
- [ ] F4. Scope fidelity

## Commit strategy
Use one Conventional Commit per todo. Do not auto-commit unless the user explicitly approves commits in the execution turn. Suggested order:
1. `fix(strategy): align golden-cross buy entry predicate`
2. `feat(strategy): persist sell decision context`
3. `refactor(strategy): version sell decision thresholds`
4. `fix(strategy): use persisted sell stages in consumers`
5. `test(strategy): cover strategy API decision surfaces`
6. `docs(strategy): reconcile buy sell strategy review`

## Success criteria
1. Scan/recommendation and execution cannot disagree on the core buy-entry predicate for pullback recovery.
2. Sell analysis decisions are reproducible from stored history without live API re-analysis.
3. Sell threshold defaults remain behavior-compatible but are configurable/versioned.
4. Portfolio cash plan and notification consumers use rich persisted sell-stage context.
5. Focused strategy tests pass and API/manual QA evidence is captured under `.omo/evidence/strategy-buy-sell-review/`.
6. No live orders are placed and unrelated dirty worktree changes are preserved.
