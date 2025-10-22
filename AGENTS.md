# Repository Guidelines

## Project Structure & Module Organization
The FastAPI application lives under `src/`, with `src/main.py` exposing the ASGI entry point. Hexagonal layers are split into `src/application` for services and interfaces, `src/adapters` for database, cache, and external API clients, and `src/settings` for Pydantic-driven configuration. Shared documentation sits in `docs/`, and runnable samples for KIS endpoints are under `examples/`. Static dashboard assets reside in `static/`. Place new automated tests in a top-level `tests/` package to align with the Pyproject configuration, grouping them by domain (`tests/order/`, `tests/strategy/`, etc.).

## Build, Test, and Development Commands
```bash
uv sync                         # install runtime + dev dependencies
python -m src.main              # start the development server with defaults
uvicorn src.main:app --reload   # hot-reload server during local work
pytest                          # run the async-aware unit test suite
pytest --cov=src tests/         # generate terminal and HTML coverage
black src/ tests/               # format code to the project line length
isort src/ tests/               # normalize import ordering
mypy src/                       # enforce typing rules
```

## Coding Style & Naming Conventions
Code is formatted by Black with a 100-character line limit and import order enforced by isort’s Black profile. Modules, functions, and variables use `snake_case`; classes use `PascalCase`; constants stay in `UPPER_SNAKE_CASE`. Prefer explicit type hints and docstrings that document purpose, parameters, and return types with runnable snippets when possible. Follow the `docs/base/convention.md` guidance for naming API adapters after their REST paths (e.g., `/uapi/domestic-stock/...` ⇒ `domestic_stock/comp_program_trade_daily.py`) and keep modules narrowly scoped.

## Testing Guidelines
Use `pytest` with `pytest-asyncio` for asynchronous routes and services. Test files should follow `test_*.py` or `*_test.py` patterns inside `tests/`, while adapter “check” samples may mirror the `chk_<module>.py` style described in the conventions doc. Target meaningful coverage with `--cov=src`; investigate any gaps reported in `htmlcov/index.html`. When adding domain services, create focused fixtures for KIS clients and exercise both success and failure paths.

## Commit & Pull Request Guidelines
This snapshot ships without Git metadata, so adopt Conventional Commit prefixes (`feat:`, `fix:`, `docs:`, `refactor:`, etc.) for clarity and changelog automation. Keep subjects under 70 characters and elaborate in the body when behavior changes or rollbacks are required. Pull requests should include: a concise summary, related issue or ticket, a checklist of local test commands executed, and screenshots or API traces when endpoints change. Highlight schema or environment variable updates prominently so operators can react before deployment.

## Security & Configuration Tips
Never commit `.env` files or KIS credentials; use the provided `.env.example` as a template and document new entries in `src/settings/config.py`. Distinguish between paper and production keys via `TRADING_ENVIRONMENT`, and validate Redis/PostgreSQL URLs before pushing. Log sensitive data only at debug level and scrub tokens in exception handlers to keep trading accounts safe.
