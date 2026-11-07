# TEST KNOWLEDGE BASE

## OVERVIEW
Pytest suite with async auto mode and coverage enabled by default. Tests are grouped by behavioral
surface rather than mirroring every source directory.

## STRUCTURE
```text
tests/
|-- adapters/     # external/client behavior
|-- application/  # application/common utilities (e.g. common/test_client_ip.py)
|-- domain/       # services, schedulers, strategy/backtest logic
|-- interface/    # routers, auth boundaries, pages, middleware, exception handlers
`-- test_*.py     # older/top-level backtest, logging bootstrap, utility tests
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Pytest config | `pyproject.toml` | `asyncio_mode=auto`, coverage reports, file patterns |
| KIS client behavior | `adapters/test_kis_*` | token refresh, metrics, auth formatting, rate-limit pacing, token cache (`test_kis_token_cache.py`: latest-expiring/KST-aware/rejected-token rules) |
| DART client | `adapters/test_dart_client.py` | external client behavior |
| Strategy domain | `domain/test_*strategy*`, `domain/test_notification_scheduler*` | buy/sell/golden-cross/alerts |
| Order domain | `domain/test_order_*` | DTOs, IDs, order service ops |
| OHLCV/backtest | `domain/test_ohlcv_*`, top-level `test_backtest_*` | loaders, engine, managers |
| Interface security | `interface/test_admin_access.py`, `interface/test_mypage_admin_boundary.py`, `interface/test_admin_login_boundary.py` | protected/public route boundaries, global login gate whitelist |
| Admin login | `domain/test_admin_auth_service.py`, `application/common/test_password_hash.py` | scrypt hash, Redis session, IP lockout |
| Live order path | `domain/test_live_order_path_fixes.py`, `domain/test_golden_cross_engine_dry_run.py`, `test_golden_cross_live_parity.py` | closing-auction order, reconcile, duplicate guard, max positions, live/backtest parity |
| Regime / risk guards | `domain/test_regime_entry_gate.py`, `domain/test_regime_filter.py`, `domain/risk/test_safety_guard.py`, `domain/test_entry_guard.py` | ADX gate fail-open/closed, SafetyGuard and its backtest replay |
| OHLCV provisional bar | `adapters/test_ohlcv_provisional_bar_guard.py` | same-day 1d bar before 15:31 KST is not cached |
| Client IP / proxy trust | `application/common/test_client_ip.py`, `interface/test_access_logging_middleware.py` | XFF/X-Real-IP trust rules shared by admin checks, access logs, WebSocket |
| Access log API/domain | `interface/test_access_log_router.py`, `domain/test_access_log_service.py` | admin-gated `/api/v1/access-logs` and its `@transaction` service |
| Logging bootstrap | `test_logging_config.py` | dictConfig wiring, credential-logger muting, file-handler opt-in |
| Engine badges (E1/E2/E3) | `interface/test_admin_page_engine_badges.py`, `interface/test_sell_strategy_page_router.py`, `interface/test_public_strategy_pages.py`, `adapters/test_telegram_message_builders.py` | every sell surface must state which engine produced it |
| Threshold SSOT / ADX parity | `domain/test_threshold_ssot.py`, `domain/test_adx_implementation_parity.py` | pins intentional threshold differences and the intentional ADX non-parity |
| Exception handlers | `interface/test_exception_handlers.py` | FastAPI error conversion |

## CONVENTIONS
- File patterns are `test_*.py` and `*_test.py`; classes `Test*`; functions `test_*`.
- There is no root `conftest.py`; fixtures are currently local to test modules.
- Tests may use untyped defs; runtime source must still satisfy strict mypy rules.
- Prefer fake clients, fake repositories, monkeypatching, and DataFrame fixtures over real KIS/Naver
  calls.
- For async service/router behavior, use `@pytest.mark.asyncio` where the local test style already
  does.

## ANTI-PATTERNS
- No live trading, production credentials, real account numbers, or real Telegram sends in tests.
- Do not weaken or delete failing tests to get a green run.
- Do not assert against generated `htmlcov/` contents.
- Avoid network-dependent tests unless explicitly marked or isolated as integration checks.

## COMMANDS
The host has no `uv`/pytest and the API image has no `tests/`; run the full suite by bind-mounting the repo
(2026-11-07: `963 passed, 13 skipped`):
```bash
docker run --rm -v /Users/m2-dev/Apps/kis-strategy-alert-server:/work -w /work -e PYTHONPATH=/work -e UV_PROJECT_ENVIRONMENT=/tmp/kis-test-venv kis-strategy-alert-server-api uv run pytest tests/ -q
```
Inside that environment (`uv run ...`) the usual subsets are:
```bash
pytest
pytest tests/domain
pytest tests/interface
pytest tests/adapters
pytest tests/application
pytest --cov=src tests/
```
