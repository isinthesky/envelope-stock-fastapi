# PROJECT KNOWLEDGE BASE

**Generated:** 2026-07-21 (commit 26e0226, branch main)
**Last synced with code:** 2026-11-07

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
|   |   |   |-- access_log/      # access log query, stats, retention cleanup
|   |   |   |-- admin_auth/      # admin ID/PW login, Redis session, IP lockout
|   |   |   |-- account/, auth/, backtest/, market_data/, ohlcv/, order/
|   |   |   |-- paper_trade/     # paper trading
|   |   |   |-- recommendation/  # readiness, scan, rule-set services and DTOs
|   |   |   |-- risk/            # SafetyGuard and risk/position-sizing DTOs
|   |   |   |-- screener/, strategy/  # strategies, schedulers, symbol validation, market regime
|   |   |-- interface/           # + admin_session_gate.py (global login gate middleware)
|   |       |-- api/             # REST and WebSocket routers, including ops/recommendation
|   |       `-- page/            # Jinja page routers, including /ops
|   |-- adapters/
|   |   |-- cache/, database/    # Redis and async SQLAlchemy models/repositories
|   |   `-- external/            # KIS, DART, KOFIA, Naver, Telegram, WebSocket I/O
|   `-- settings/                # Pydantic settings, logging bootstrap, exception-handler registration
|-- templates/                   # Jinja page templates used by interface/page routers
|-- static/                      # dashboard JavaScript and CSS
|-- tests/                       # pytest suite; domain/adapters/interface grouping
|-- scripts/                     # common/ helpers, research/ (offline), ops/ (backfill, seed, scan, admin hash)
|-- alembic/                     # async SQLAlchemy migrations
|-- docs/base/                   # architecture, service, and convention SSoT
`-- examples/                    # KIS endpoint examples and chk_* samples
```

Ignore generated or local-state directories when mapping the project: `.venv/`, `htmlcov/`,
`__pycache__/`, `_attic/`, `.omo/`, `.omx/`, `.pytest_cache/`, `.mypy_cache/`.

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| App startup/shutdown | `src/main.py` | DB/Redis checks, KIS token task, strategy/notification/OHLCV schedulers, `AdminSessionGateMiddleware` |
| REST endpoint | `src/application/interface/api/*_router.py` | Thin routers; usually return `ResponseDTO` |
| Admin/public page | `src/application/interface/page/*_page_router.py` | Page routers render `templates/page/*.html` and use `static/` assets |
| Strategy behavior | `src/application/domain/strategy/` | Golden-cross, sell-signal, universe, scheduler, notification logic |
| Backtest behavior | `src/application/domain/backtest/` | Engine, loaders, order/position managers, facade service |
| Order/account/market use case | `src/application/domain/{order,account,market_data}/` | Domain services wrap KIS clients and repositories |
| DB schema | `src/adapters/database/models/`, `alembic/versions/` | Keep model and migration changes paired |
| DB persistence | `src/adapters/database/repositories/` | Repository pattern over async SQLAlchemy sessions |
| External API client | `src/adapters/external/<provider>/` | Network I/O only; policy remains in domain services |
| Settings/env key | `src/settings/config.py`, `.env.example` | Add typed field plus template key |
| Logging bootstrap | `src/settings/logging_config.py` | `setup_logging()` dictConfig; called at the top of `src/main.py` |
| Client IP / proxy trust | `src/application/common/client_ip.py` | single source for admin IP checks, access logs, public cooldowns, WebSocket |
| Access log API/domain | `src/application/interface/api/access_log_router.py`, `src/application/domain/access_log/` | `/api/v1/access-logs`, admin-gated |
| Ops runbook | `README.md`, `docs/ops/` | Swagger/OpenAPI disabled; ops routes are protected |

## CODE MAP
| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `app` | FastAPI | `src/main.py` | ASGI entrypoint and router registry |
| `lifespan` | function | `src/main.py` | startup/shutdown resource orchestration |
| `DatabaseSession` | DI alias | `src/application/common/dependencies.py` | async DB session injection |
| `KISClientDep` | DI alias | `src/application/common/dependencies.py` | KIS REST client injection |
| `ResponseDTO` | DTO | `src/application/common/dto.py` | standard REST response envelope |
| `StrategyService` | facade | `src/application/domain/strategy/strategy_service.py` | strategy CRUD/analysis facade; delegates universe/recommendation/cash-plan |
| `UniverseService` | service | `src/application/domain/strategy/universe_service.py` | universe refresh: ETF+KRX seeding, worker pool, recount |
| `RecommendationService` / `RecommendationScorer` | service | `src/application/domain/strategy/recommendation_service.py` | golden-cross recommendation scan/scoring/Top-N |
| `PortfolioCashPlanner` | policy | `src/application/domain/strategy/portfolio_cash_planner.py` | portfolio cash-plan policy (urgency/ratio/heat) |
| `BuyStrategyService` | service | `src/application/domain/strategy/buy_strategy_service.py` | golden-cross scan and candidate filtering |
| `SellStrategyService` | service | `src/application/domain/strategy/sell_strategy_service.py` | sell signal scoring (`ScoreRule` pipeline in `sell_score_rules.py`) and overlays |
| `fetch_kind_corp_list` | adapter | `src/adapters/external/krx/kind_client.py` | KRX KIND corp-list scraping (pure I/O, moved out of the domain) |
| `StrategyScheduler` | scheduler | `src/application/domain/strategy/scheduler.py` | 08:00 universe refresh, 15:35 golden-cross execution (misfire 90s), 16:10 order reconcile (`daily_order_reconcile`) |
| `NotificationScheduler` | scheduler | `src/application/domain/strategy/notification_scheduler.py` | buy 11:20→11:30/14:20→14:30, sell 09:20→09:30/12:20→12:30; jobs registered only when `BUY_/SELL_NOTIFICATION_ENABLED` (both off in current prod env) |
| `is_valid_krx_symbol` | function | `src/application/domain/strategy/symbol_validation.py` | `^[0-9A-Z]{6}$` KRX symbol check; filters memo rows before the pipeline |
| `RecommendationScanService` | service | `src/application/domain/recommendation/recommendation_scan_service.py` | recommendation scan/readiness orchestration |
| `SafetyGuard` | guard | `src/application/domain/risk/safety_guard.py` | GoldenCross new-buy pre-check. Effective guards: market crash (benchmark day return <= -2%) and daily new-entry cap 3 (`record_entry`). Loss/consecutive-loss guards and its own `max_concurrent_positions`(3) are effectively inert; max holdings = strategy config `max_position_count`(5) enforced in `GoldenCrossEngine` |
| `GoldenCrossEngine` | engine | `src/application/domain/strategy/golden_cross_engine.py` | live/dry-run execution: kill-switch, regime gate (fail-closed), closing-auction orders (ORD_DVSN 06), `reconcile_open_orders` |
| `market_regime_ok` | function | `src/application/domain/strategy/market_regime.py` | shared ADX regime gate (scan/alerts fail-open, live fail-closed) |
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
- `docker compose build`와 `docker compose up -d --build`는 `kis_token_cache` named volume을 유지하므로 토큰 재발급 없이 안전하다.
  마운트 경로는 실행 사용자의 `HOME`이 결정한다: 하드닝 배포(2026-09-08) 이후 비루트 `uid 10001` 기준 `/home/appuser/KIS/config`다(롤백 시에만 root `/root/KIS/config`).
- 컨테이너 하드닝(비루트 `uid 10001` 실행, Redis 비밀번호 필수, DB/Redis 로컬 전용 바인딩)은 2026-09-08에 **배포 완료**됐다. 컨테이너 안에서 `uv run`은 실패하므로 `/app/.venv/bin/<cmd>`를 직접 실행한다. 롤백 절차는 `README.md`의 「컨테이너 하드닝 적용 절차」를 따른다.
- 하드닝 적용 후 api 컨테이너 안에서 `uv run ...` 은 `/app/.venv` 쓰기 때문에 실패한다. `/app/.venv/bin/python` 또는 `/app/.venv/bin/<cmd>` 를 직접 쓴다. `docker compose exec --user root api ...` 는 `HOME`을 바꾸지 않아 토큰 캐시에 root 소유 파일을 남길 수 있으므로 기본 수단으로 쓰지 않는다(README 「컨테이너 하드닝 적용 절차」).
- 전체 테스트의 현재 확인값은 `963 passed, 13 skipped`다(2026-11-07 실측, `--no-cov`).
- `/ops`, `/api/v1/ops/summary`, `/api/v1/ops/notification-scheduler-status`는 구현되어 있으며 전역 로그인 게이트(`AdminSessionGateMiddleware`) + `AdminAccessDep`(IP allowlist)로 보호된다.
  `ADMIN_ALLOWED_IPS`는 현재 전 대역이라 실질 방어선은 관리자 로그인 세션이다.
- 클라이언트 IP 판정은 `src/application/common/client_ip.py` 단일 출처를 쓴다(관리자 IP 검증·접근 로그·공개 스캔 쿨다운·WebSocket 공통). 프록시 헤더는 `TRUSTED_PROXY_IPS` 에 속한 직접 연결에서만 신뢰한다.
- 로깅 부트스트랩은 `src/settings/logging_config.py`의 `setup_logging()`이며 `src/main.py` 최상단에서 호출된다.
