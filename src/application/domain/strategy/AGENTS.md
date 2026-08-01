# STRATEGY DOMAIN KNOWLEDGE BASE

## OVERVIEW
Highest-complexity trading domain: buy scans, sell scoring, strategy state, schedulers, Telegram
notifications, OHLCV loading, and universe analysis.

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Strategy CRUD/history | `strategy_service.py` | **facade** — CRUD/analysis history; delegates universe/recommendation/cash-plan |
| Universe refresh | `universe_service.py` | ETF + KRX seeding, worker pool, recount (KRX scraping in `adapters/external/krx/`) |
| Recommendation scoring | `recommendation_service.py` | `RecommendationScorer`: scan → financial filter → score → Top-N |
| Portfolio cash plan | `portfolio_cash_planner.py` | pure policy: urgency scores, ratio maps, heat thresholds |
| Buy candidates | `buy_strategy_service.py` | golden-cross scan; `_run_scan_workers`/`_evaluate_gc_row` shared pipeline |
| Sell analysis | `sell_strategy_service.py` | `analyze_sell_signal` split into load/overlay/score/format stages |
| Sell scoring rules | `sell_score_rules.py` | `ScoreRule` list — each rule emits points AND max from one place (no mirror) |
| Sell rule research | `sell_rule_research_service.py` | peak-rule input evaluation; thresholds from `PeakRuleThresholds` |
| Risk backfill | `sell_risk_backfill_service.py` | persists derived sell-risk fields |
| Canonical contract | `strategy_contract.py` | GC state enum, `GOLDEN_CROSS_SCAN_STATE_ORDER`, `SELL_STAGE_ORDER` |
| Notifications (wiring) | `notification_scheduler.py` | scheduler wiring + thin job orchestrators |
| Alert payloads | `alert_builders.py` | ETF leader summary, buy/sell alert assembly (pure functions) |
| Notification dedupe | `notification_dedupe.py` | freshness/signature/dedupe cache |
| Golden-cross execution | `golden_cross_engine.py`, `state_machine.py` | state transition and dry-run/live execution |
| OHLCV for strategies | `ohlcv_data_loader.py` | DB cache plus KIS/Naver loading for strategy services |
| Shared DTOs | `dto.py` | large contract surface; check router/template consumers |
| Presets/signals | `presets.py`, `signal_evaluator.py`, `stock_screener.py` | reusable strategy calculations |

## CONVENTIONS
- Preserve the current split: scan/selection in `buy_strategy_service.py`, exit analysis in
  `sell_strategy_service.py`. `strategy_service.py` is a thin **facade** delegating to
  `universe_service.py` / `recommendation_service.py` / `portfolio_cash_planner.py` — keep public
  facade signatures and `@transaction` decorators intact when extending.
- Reuse canonical constants from `strategy_contract.py` (`GOLDEN_CROSS_SCAN_STATE_ORDER`,
  `DEFAULT_GOLDEN_CROSS_PULLBACK`, `SELL_STAGE_ORDER`) — do not redefine state/order literals.
- Add sell-score weights/thresholds to `SellScoreSettings`/`PeakRuleThresholds`
  (`src/settings/sell_score_settings.py`); model a new sell-score component as a `ScoreRule` so
  points and max stay a single source.
- Treat `dto.py` as a cross-interface contract. Router responses, templates, scripts, and tests may
  depend on field names.
- Keep market-data loading behind `OHLCVDataLoader` or domain services; do not duplicate KIS/Naver
  fetching loops in new strategy code. KRX corp-list scraping lives in `adapters/external/krx/`.
- Settings-backed thresholds belong in `src/settings/config.py` or `sell_score_settings.py`, with
  `.env.example` updated when environment-controlled.
- For scheduler changes, verify both status endpoints and Telegram-disabled behavior.

## ANTI-PATTERNS
- No live KIS order side effects in scan, research, or notification paths.
- No new hard-coded account IDs, stock lists, credentials, or Telegram chat IDs.
- No broad `except Exception` that hides trading decisions unless it logs debug context and returns a
  conservative fallback, matching existing provider-overlay patterns.
- No pandas column assumptions without minimum-candle and missing-column guards.

## TESTING NOTES
- Existing focused tests live in `tests/domain/test_buy_strategy_*`,
  `tests/domain/test_sell_strategy_*`, `tests/domain/test_notification_scheduler*`,
  `tests/domain/test_golden_cross_*`, and `tests/domain/test_personal_flow_cache.py`.
- Favor deterministic fixtures for OHLCV DataFrames and provider clients; avoid network-dependent
  assertions unless a test is explicitly an integration check.
