---
slug: strategy-buy-sell-review
status: drafting
intent: unclear
pending-action: write .omo/plans/strategy-buy-sell-review.md
approach: Align buy signal semantics across scan/recommendation/execution, make sell-stage decisions reproducible from persisted history, and add calibration/QA guardrails around threshold-heavy strategy logic.
---

# Draft: strategy-buy-sell-review

## Components (topology ledger)
<!-- Lock the SHAPE before depth. One row per top-level component that can succeed or fail independently. -->
<!-- id | outcome (one line) | status: active|deferred | evidence path -->
| C1 | Buy scan and recommendation semantics are explainable and match execution entry rules | active | src/application/domain/strategy/buy_strategy_service.py:607, src/application/domain/strategy/signal_evaluator.py:29, src/application/domain/strategy/strategy_service.py:1028 |
| C2 | Live golden-cross execution uses the same buy/sell predicates and risk contract as surfaced to users | active | src/application/domain/strategy/state_machine.py:204, src/application/domain/strategy/golden_cross_engine.py:350 |
| C3 | Sell analysis scoring and overlay rules are calibrated, configurable, and test-backed | active | src/application/domain/strategy/sell_strategy_service.py:427, src/settings/sell_score_settings.py:10 |
| C4 | Sell decision persistence, portfolio cash plan, and notification surfaces are reproducible | active | src/adapters/database/models/analysis_history.py:26, src/application/domain/strategy/strategy_service.py:1330, src/application/domain/strategy/strategy_service.py:1675 |
| C5 | Verification covers unit seams plus API/manual surfaces without live trading side effects | active | tests/domain/test_golden_cross_strategy.py:1, tests/domain/test_sell_strategy_personal_flow.py:1 |

## Open assumptions (announced defaults)
<!-- Intent is UNCLEAR: research resolves ambiguity, defaults are adopted (not asked), and each is surfaced in the plan's human TL;DR for veto. -->
<!-- assumption | adopted default | rationale | reversible? -->
| Review target | Treat "매수 전략, 매도 전략" as current production strategy behavior, not old Bollinger/Envelope docs | Current code routes strategy work through golden-cross buy scans/execution and sell-stage analysis | yes |
| Execution safety | All follow-up work must default to dry-run or mocked orders until explicit trading credentials and operator approval are present | This repo integrates KIS order execution; review found enough risk to avoid live-order QA | yes |
| Priority | Fix semantic consistency and persistence before threshold tuning | Tuning a strategy whose scan/execution/persistence contracts disagree can improve the wrong behavior | yes |
| Scope size | HEAVY / Architecture | Multiple modules, DB persistence, API surfaces, scheduler/notification surfaces, and trading risk are involved | no downgrade |

## Findings (cited - path:lines)
1. Buy recommendation and buy execution are not using the same entry predicate. The scan classifier requires recent oversold history, a rising Stoch K, optional K>D momentum, and a healthy MA gap before `OPTIMAL_BUY` (`src/application/domain/strategy/signal_evaluator.py:29`). The execution state machine buys from `READY_TO_BUY` on recovery crossover or `stoch_k > strong_recovery_threshold`, without the scanner's K>D, rising, or MA-gap checks (`src/application/domain/strategy/state_machine.py:204`). The engine uses that state machine for real signals and orders (`src/application/domain/strategy/golden_cross_engine.py:280`, `src/application/domain/strategy/golden_cross_engine.py:350`). This can make the dashboard say "not optimal" while execution still buys.
2. The buy-side implementation has useful safeguards but they are split across services: scan/recommendation scoring lives in `BuyStrategyService`/`StrategyService` (`src/application/domain/strategy/buy_strategy_service.py:607`, `src/application/domain/strategy/strategy_service.py:1238`), order sizing lives in `GoldenCrossEngine._execute_buy` (`src/application/domain/strategy/golden_cross_engine.py:436`), and `SafetyGuard` is initialized with default guard config rather than strategy-position config (`src/application/domain/strategy/golden_cross_engine.py:620`, `src/application/domain/risk/safety_guard.py:111`). Follow-up should explicitly bind these contracts instead of assuming they already match.
3. Sell analysis is materially more complete than older docs claim: score-based staging, Stoch dead-cross, 52-week high, volume peak, ADX penalty, personal flow, market credit, and overlay upgrades are present (`src/application/domain/strategy/sell_strategy_service.py:640`, `src/application/domain/strategy/sell_strategy_service.py:878`, `src/application/domain/strategy/sell_strategy_service.py:1181`, `src/application/domain/strategy/sell_strategy_service.py:1722`). Older `docs/sell-strategy/implementation-review.md` is stale and should not drive implementation without reconciliation.
4. Sell decisions are not reproducibly persisted. `analysis_history` stores old/basic sell fields (`src/adapters/database/models/analysis_history.py:86`) and `save_analysis_history` persists only phase/reasons/basic indicators (`src/application/domain/strategy/strategy_service.py:1330`). `_history_to_dto` can add rich fields only when a live `sell_result` is supplied (`src/application/domain/strategy/strategy_service.py:1932`). If live enrichment fails, portfolio cash planning falls back to `sell_stage="HOLD"` (`src/application/domain/strategy/strategy_service.py:1729`). This weakens auditability and makes historical outputs depend on current market/API availability.
5. Threshold-heavy sell logic is partly configurable and partly hard-coded. `SellScoreSettings` covers score weights and some thresholds (`src/settings/sell_score_settings.py:10`), but volume sell signals still hard-code `1.3`, ADX strong trend hard-codes `25`, and sharp-v1 profit/ETF thresholds are inline (`src/application/domain/strategy/sell_strategy_service.py:1620`, `src/application/domain/strategy/sell_strategy_service.py:1713`, `src/application/domain/strategy/sell_strategy_service.py:1348`). This makes backtest calibration and operator review harder.
6. Focused current strategy tests pass: `uv run pytest tests/domain/test_golden_cross_strategy.py tests/domain/test_golden_cross_recommendations.py tests/domain/test_golden_cross_engine_dry_run.py tests/domain/test_sell_strategy_personal_flow.py tests/domain/test_sell_strategy_sharp_v1.py tests/domain/test_sell_rule_research_service.py tests/domain/test_buy_strategy_financial_filter.py tests/domain/test_buy_strategy_scan_concurrency.py tests/domain/test_backtest_signal_generators.py` collected 45 tests and passed all 45.
7. The worktree is already dirty across many files, including strategy modules. Any executor must re-read current files and avoid reverting unrelated user changes.

## Decisions (with rationale)
1. Plan a consistency-first fix: centralize or share the buy-entry predicate between `GoldenCrossSignalEvaluator` and `GoldenCrossStateMachine` before tuning buy thresholds.
2. Plan a persistence-first sell fix: store final stage, ratios, score summary, ADX/volume/personal/credit inputs, and threshold version in `analysis_history` before relying on portfolio cash plans or notifications as auditable outputs.
3. Treat sell threshold calibration as a config/API/backtest task, not ad hoc constants in `SellStrategyService`.
4. Keep live-order execution out of the follow-up QA. Use dry-run engine paths, mocked KIS/account/order services, API calls against local server routes, and focused tests.

## Scope IN
1. Review and plan improvements for current golden-cross buy scan/recommendation/execution.
2. Review and plan improvements for current sell signal scoring/staging/overlay logic.
3. Review and plan persistence/API/notification/cash-plan surfaces that consume strategy decisions.
4. Include tests and manual QA commands needed for a worker to verify changes without live trading.

## Scope OUT (Must NOT have)
1. No product-code changes during this planning/review turn.
2. No live KIS orders, live account mutations, or production credential usage.
3. No replacement of the strategy with a new model or unrelated Bollinger/Envelope strategy.
4. No broad cleanup of the existing dirty worktree.

## Open questions
None blocking. If the user had a specific non-golden-cross strategy in mind, they should redirect before execution starts.

## Approval gate
status: plan-written
<!-- When exploration is exhausted and unknowns are answered, set status: awaiting-approval. -->
<!-- That durable record is the loop guard: on a later turn read it and resume at the gate instead of re-running exploration. -->
pending user decision: start execution with `$start-work .omo/plans/strategy-buy-sell-review.md`, or request a narrower review scope first.
