# PROJECT KNOWLEDGE BASE

**Generated:** 2026-07-21
**Commit:** 26e0226
**Branch:** main

## OVERVIEW
FastAPI server for Korea Investment Securities (KIS) strategy execution, screening,
backtesting, admin pages, and Telegram/ops alerts. The codebase uses a hexagonal
split: inbound routers/pages, domain orchestration, outbound adapters, and typed settings.

## STRUCTURE
```text
kis-strategy-alert-server/
|-- src/
|   |-- main.py                  # ASGI app, lifespan, middleware, router mounting
|   |-- application/
|   |   |-- common/              # ResponseDTO, DI aliases, exceptions, decorators, metrics
|   |   |-- domain/
|   |   |   |-- account/, auth/, backtest/, market_data/, ohlcv/, order/
|   |   |   |-- recommendation/  # readiness, scan, rule-set services and DTOs
|   |   |   |-- risk/            # SafetyGuard and risk/position-sizing DTOs
|   |   |   |-- screener/, strategy/  # strategies, schedulers, symbol validation
|   |   |-- interface/
|   |       |-- api/             # REST and WebSocket routers, including ops/recommendation
|   |       `-- page/            # Jinja page routers, including /ops
|   |-- adapters/
|   |   |-- cache/, database/    # Redis and async SQLAlchemy models/repositories
|   |   `-- external/            # KIS, DART, KOFIA, Naver, Telegram, WebSocket I/O
|   `-- settings/                # Pydantic settings and exception-handler registration
|-- templates/                   # Jinja page templates used by interface/page routers
|-- static/                      # dashboard JavaScript and CSS
|-- tests/                       # pytest suite; domain/adapters/interface grouping
|-- scripts/                     # manual backtest, scan, DB init, and backfill entrypoints
|-- alembic/                     # async SQLAlchemy migrations
|-- docs/base/                   # architecture, service, and convention SSoT
`-- examples/                    # KIS endpoint examples and chk_* samples
```

Ignore generated or local-state directories when mapping the project: `.venv/`, `htmlcov/`,
`__pycache__/`, `_attic/`, `.omo/`, `.omx/`, `.pytest_cache/`, `.mypy_cache/`.

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| App startup/shutdown | `src/main.py` | DB/Redis checks, KIS token task, strategy/notification/OHLCV schedulers |
| REST endpoint | `src/application/interface/api/*_router.py` | Thin routers; usually return `ResponseDTO` |
| Admin/public page | `src/application/interface/page/*_page_router.py` | Page routers render `templates/page/*.html` and use `static/` assets |
| Strategy behavior | `src/application/domain/strategy/` | Golden-cross, sell-signal, universe, scheduler, notification logic |
| Backtest behavior | `src/application/domain/backtest/` | Engine, loaders, order/position managers, facade service |
| Order/account/market use case | `src/application/domain/{order,account,market_data}/` | Domain services wrap KIS clients and repositories |
| DB schema | `src/adapters/database/models/`, `alembic/versions/` | Keep model and migration changes paired |
| DB persistence | `src/adapters/database/repositories/` | Repository pattern over async SQLAlchemy sessions |
| External API client | `src/adapters/external/<provider>/` | Network I/O only; policy remains in domain services |
| Settings/env key | `src/settings/config.py`, `.env.example` | Add typed field plus template key |
| Ops runbook | `README.md`, `docs/ops/` | Swagger/OpenAPI disabled; ops routes are protected |

## CODE MAP
| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `app` | FastAPI | `src/main.py` | ASGI entrypoint and router registry |
| `lifespan` | function | `src/main.py` | startup/shutdown resource orchestration |
| `DatabaseSession` | DI alias | `src/application/common/dependencies.py` | async DB session injection |
| `KISClientDep` | DI alias | `src/application/common/dependencies.py` | KIS REST client injection |
| `ResponseDTO` | DTO | `src/application/common/dto.py` | standard REST response envelope |
| `StrategyService` | service | `src/application/domain/strategy/strategy_service.py` | strategy CRUD/universe/analysis orchestration |
| `BuyStrategyService` | service | `src/application/domain/strategy/buy_strategy_service.py` | golden-cross scan and candidate filtering |
| `SellStrategyService` | service | `src/application/domain/strategy/sell_strategy_service.py` | sell signal scoring and overlays |
| `StrategyScheduler` | scheduler | `src/application/domain/strategy/scheduler.py` | 08:00 universe refresh and 15:35 golden-cross execution |
| `NotificationScheduler` | scheduler | `src/application/domain/strategy/notification_scheduler.py` | 09:20/11:20/12:20/14:20 data refresh and 09:30/11:30/12:30/14:30 Telegram alerts |
| `is_valid_krx_symbol` | function | `src/application/domain/strategy/symbol_validation.py` | `^[0-9A-Z]{6}$` KRX symbol check; filters memo rows before the pipeline |
| `RecommendationScanService` | service | `src/application/domain/recommendation/recommendation_scan_service.py` | recommendation scan/readiness orchestration |
| `SafetyGuard` | guard | `src/application/domain/risk/safety_guard.py` | GoldenCross order pre-check using `RiskLimitConfigDTO` and `PositionSizingConfigDTO` for daily/weekly/monthly loss, consecutive losses, cooldown, and max positions |
| `OrderService` | service | `src/application/domain/order/service.py` | order create/query/cancel/modify workflow |
| `BacktestService` | service | `src/application/domain/backtest/service.py` | backtest facade and summary generation |
| `OHLCVRepository` | repository | `src/adapters/database/repositories/ohlcv_repository.py` | OHLCV cache persistence |
| `KISAPIClient` / `SlidingWindowRateLimiter` | client / limiter | `src/adapters/external/kis_api/client.py` | KIS REST calls; production `.env` uses `KIS_API_RATE_LIMIT=8` (40% of `20/s`); EGW00201 backs off `0.5 → 1.0 → 2.0` seconds for up to 3 retries |
| `build_golden_cross_recommendations_message` | builder | `src/adapters/external/telegram/notifier.py` | Telegram buy recommendation message builder |
| `build_sell_signals_summary_message` | builder | `src/adapters/external/telegram/notifier.py` | Telegram sell-signal summary builder |
| `TelegramNotifier` / `get_telegram_notifier` | notifier / factory | `src/adapters/external/telegram/notifier.py` | Telegram Bot API notifier singleton |
| `ops_summary` / `notification_scheduler_status` | API handlers | `src/application/interface/api/ops_router.py` | Admin-protected operations summary and notification scheduler status |
| `operations_dashboard` | page handler | `src/application/interface/page/ops_page_router.py` | Admin-protected operations dashboard |
| `Settings` | config | `src/settings/config.py` | typed env contract; config default `kis_api_rate_limit=10`, production `.env` value `8`, and admin route switch |

## CONVENTIONS
- Architecture direction is `interface -> domain -> adapters`; `settings` and
  `application/common` are shared support layers.
- `domain` must not depend on FastAPI `Request`/`Response`; convert external errors into
  domain/application exceptions before returning to interfaces.
- `interface` parses inputs, calls services, and formats responses only. Do not compose DB
  queries or business policy in routers.
- `adapters` perform I/O only. Cache TTLs, risk limits, trading decisions, and retry policy
  decisions belong in domain services unless already part of a low-level client.
- Add new env vars in both `src/settings/config.py` and `.env.example`; never document real
  credentials.
- API/path naming for KIS-style examples follows `docs/base/convention.md`: REST path segments
  become snake_case folders/files, and check scripts use `chk_<module>.py`.

## ROOT-CAUSE RESOLUTION
- Fix the mechanism that causes a failure, not only the specific case that revealed it.
- State the intended result and the observed behavior that violates it before selecting a fix.
- Identify the root cause, relevant constraints, and invariants. Prefer changes that handle the
  entire class of similar failures across code paths, inputs, and timing.
- Do not hide symptoms by weakening or narrowing requirements, or by adding a narrowly scoped
  prohibition. If a temporary mitigation is necessary, document its limitation and the follow-up
  needed for a structural solution.
- Before considering the work complete, ask: “Would this solution still work if the same failure
  occurred through another path, with different input, or at a different time?” If not, seek a
  more structural solution. Apply judgment when the issue is genuinely local.

Trade-off: prioritize sustainable, generalizable solutions over the fastest local patch, while
remaining proportionate for issues that are truly local.

## ANTI-PATTERNS (THIS PROJECT)
- Do not commit `.env`, token caches, real KIS keys, account numbers, Telegram tokens, or DB URLs
  with credentials.
- Do not place live trading/order side effects in tests or examples without explicit safety guards.
- Do not route `/mypage/*` without admin protection; `/page/*` is the intentionally public page
  surface.
- Do not re-enable FastAPI Swagger/ReDoc/OpenAPI casually; `README.md` documents them as disabled.
- Do not use generated artifacts (`htmlcov/`, caches, `_attic/`) to infer source structure.

## COMMANDS
```bash
# Rebuild/redeploy: kis_token_cache named volume preserves the KIS token cache.
docker compose build
docker compose up -d --build

# Full test: host has no uv and the API image has no tests/ directory.
docker run --rm -v /Users/m2-dev/Apps/kis-strategy-alert-server:/work -w /work -e PYTHONPATH=/work -e UV_PROJECT_ENVIRONMENT=/tmp/kis-test-venv kis-strategy-alert-server-api uv run pytest tests/ -q
```

## NOTES
- ⚠️ `force_refresh=True`를 남발하지 않는다. KIS 토큰은 1일 1회 발급 원칙이다.
- `docker compose build`와 `docker compose up -d --build`는 `kis_token_cache:/root/KIS/config` named volume을 유지하므로 토큰 재발급 없이 안전하다.
- 전체 테스트의 현재 확인값은 `490 passed, 13 skipped`다.
- `/ops`, `/api/v1/ops/summary`, `/api/v1/ops/notification-scheduler-status`는 구현되어 있으며 `AdminAccessDep`로 보호된다.
