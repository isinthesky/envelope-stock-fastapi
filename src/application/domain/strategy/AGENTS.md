# STRATEGY DOMAIN KNOWLEDGE BASE

## OVERVIEW
Highest-complexity trading domain: buy scans, sell scoring, strategy state, schedulers, Telegram
notifications, OHLCV loading, and universe analysis.

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Strategy CRUD/history | `strategy_service.py` | strategy configs, universe, analysis history |
| Buy candidates | `buy_strategy_service.py` | golden-cross scan, MA/stochastic filters, concurrency |
| Sell analysis | `sell_strategy_service.py` | MA/Stoch/RSI/ATR/ADX, personal flow, market credit overlays |
| Sell rule research | `sell_rule_research_service.py` | peak-rule input evaluation and scoring helpers |
| Risk backfill | `sell_risk_backfill_service.py` | persists derived sell-risk fields |
| Notifications | `notification_scheduler.py` | scheduled data refresh plus Telegram alert slots |
| Golden-cross execution | `golden_cross_engine.py`, `state_machine.py` | state transition and dry-run/live execution |
| OHLCV for strategies | `ohlcv_data_loader.py` | DB cache plus KIS/Naver loading for strategy services |
| Shared DTOs | `dto.py` | large contract surface; check router/template consumers |
| Presets/signals | `presets.py`, `signal_evaluator.py`, `stock_screener.py` | reusable strategy calculations |

## CONVENTIONS
- Preserve the current split: scan/selection in `buy_strategy_service.py`, exit analysis in
  `sell_strategy_service.py`, persistence-heavy CRUD in `strategy_service.py`.
- Treat `dto.py` as a cross-interface contract. Router responses, templates, scripts, and tests may
  depend on field names.
- Keep market-data loading behind `OHLCVDataLoader` or domain services; do not duplicate KIS/Naver
  fetching loops in new strategy code.
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
