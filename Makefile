PYTHON ?= /opt/homebrew/bin/python3.11
VENV ?= .venv
PY ?= $(VENV)/bin/python
PIP ?= $(VENV)/bin/pip

.PHONY: sync lint test test-domain test-interface test-adapters smoke qa docker-smoke docker-test

sync:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -e .
	$(PIP) install pytest pytest-asyncio pytest-cov ruff

lint:
	$(VENV)/bin/ruff check src tests

test:
	$(PY) -m pytest -q

test-domain:
	$(PY) -m pytest -q tests/domain

test-interface:
	$(PY) -m pytest -q tests/interface

test-adapters:
	$(PY) -m pytest -q tests/adapters

smoke:
	$(PY) -c "from src.main import app; print('APP_OK')"

docker-smoke:
	docker compose --profile test run --rm --no-deps test /app/.venv/bin/python -c "from src.main import app; print('APP_OK')"

docker-test:
	docker compose --profile test run --rm --no-deps test /app/.venv/bin/python -m pytest -q $(TEST)

qa: sync lint smoke test-domain
