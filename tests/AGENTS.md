# TEST KNOWLEDGE BASE

## OVERVIEW
Pytest suite with async auto mode and coverage enabled by default. Tests are grouped by behavioral
surface rather than mirroring every source directory.

## STRUCTURE
```text
tests/
|-- adapters/    # external/client behavior
|-- domain/      # services, schedulers, strategy/backtest logic
|-- interface/   # routers, auth boundaries, pages, exception handlers
`-- test_*.py    # older/top-level backtest and utility tests
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Pytest config | `pyproject.toml` | `asyncio_mode=auto`, coverage reports, file patterns |
| KIS client behavior | `adapters/test_kis_*` | token refresh, metrics, auth formatting |
| DART client | `adapters/test_dart_client.py` | external client behavior |
| Strategy domain | `domain/test_*strategy*`, `domain/test_notification_scheduler*` | buy/sell/golden-cross/alerts |
| Order domain | `domain/test_order_*` | DTOs, IDs, order service ops |
| OHLCV/backtest | `domain/test_ohlcv_*`, top-level `test_backtest_*` | loaders, engine, managers |
| Interface security | `interface/test_admin_access.py`, `interface/test_mypage_admin_boundary.py` | protected/public route boundaries |
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
```bash
pytest
pytest tests/domain
pytest tests/interface
pytest tests/adapters
pytest --cov=src tests/
```
