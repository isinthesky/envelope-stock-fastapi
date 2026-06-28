# PROJECT KNOWLEDGE BASE

**Generated:** 2026-06-28
**Commit:** 82b89a4
**Branch:** main

## OVERVIEW
FastAPI server for Korea Investment Securities (KIS) strategy execution, screening,
backtesting, admin pages, and Telegram/ops alerts. The codebase uses a hexagonal
split: inbound routers/pages, domain orchestration, outbound adapters, and typed settings.

## STRUCTURE
```text
kis-strategy-alert-server/
|-- src/main.py                  # ASGI app, lifespan, middleware, router mounting
|-- src/application/domain/      # business services, engines, schedulers, DTOs
|-- src/application/interface/   # REST, WebSocket, and Jinja page routers
|-- src/application/common/      # ResponseDTO, DI aliases, exceptions, decorators, metrics
|-- src/adapters/                # DB, Redis, KIS, DART, Naver, Telegram, WebSocket I/O
|-- src/settings/                # Pydantic settings and exception-handler registration
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
| Symbol | Type | Location | Refs | Role |
|--------|------|----------|------|------|
| `app` | FastAPI | `src/main.py` | central | ASGI entrypoint and router registry |
| `lifespan` | function | `src/main.py` | central | startup/shutdown resource orchestration |
| `DatabaseSession` | DI alias | `src/application/common/dependencies.py` | high | async DB session injection |
| `KISClientDep` | DI alias | `src/application/common/dependencies.py` | high | KIS REST client injection |
| `ResponseDTO` | DTO | `src/application/common/dto.py` | high | standard REST response envelope |
| `StrategyService` | service | `src/application/domain/strategy/strategy_service.py` | high | strategy CRUD/universe/analysis orchestration |
| `BuyStrategyService` | service | `src/application/domain/strategy/buy_strategy_service.py` | high | golden-cross scan and candidate filtering |
| `SellStrategyService` | service | `src/application/domain/strategy/sell_strategy_service.py` | high | sell signal scoring and overlays |
| `NotificationScheduler` | scheduler | `src/application/domain/strategy/notification_scheduler.py` | 18 callers | Telegram data/alert schedule orchestration |
| `OrderService` | service | `src/application/domain/order/service.py` | 22 callers | order create/query/cancel/modify workflow |
| `BacktestService` | service | `src/application/domain/backtest/service.py` | 17 callers | backtest facade and summary generation |
| `OHLCVRepository` | repository | `src/adapters/database/repositories/ohlcv_repository.py` | 16 callers | OHLCV cache persistence |
| `KISAPIClient` | client | `src/adapters/external/kis_api/client.py` | high | REST calls, auth refresh, rate limit, metrics |
| `Settings` | config | `src/settings/config.py` | global | typed env contract and KIS environment switching |

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
uv sync
uvicorn src.main:app --reload
pytest
pytest tests/domain
pytest tests/interface
pytest tests/adapters
pytest --cov=src tests/
black src/ tests/
isort src/ tests/
mypy src/
make qa
docker compose up -d --build
```

## NOTES
- `Makefile qa` runs `sync lint smoke test-domain`, not the full suite.
- `pyproject.toml` configures pytest to emit coverage and `htmlcov/` by default.
- There is no committed `.github/workflows/`; local verification is Makefile, pytest, and targeted
  scripts.
- `ruff` is referenced by the Makefile, but previous local notes recorded that the executable may
  be absent until `make sync` installs it.
