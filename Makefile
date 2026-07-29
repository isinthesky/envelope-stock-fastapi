PYTHON ?= /opt/homebrew/bin/python3.11
VENV ?= .venv
PY ?= $(VENV)/bin/python
PIP ?= $(VENV)/bin/pip
TEST ?= tests
DOCKER_TEST_PROJECT ?= kis-stock-pipeline-test-$(shell date +%s)-$(shell printf '%s' "$$PPID")
DOCKER_TEST_COMPOSE := docker compose -p $(DOCKER_TEST_PROJECT) -f docker-compose.test.yml

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
	$(DOCKER_TEST_COMPOSE) build test
	$(DOCKER_TEST_COMPOSE) run --rm --no-deps test /app/.venv/bin/python -c "from src.main import app; print('APP_OK')"

docker-test:
	@set -e; \
	cleanup() { $(DOCKER_TEST_COMPOSE) down --volumes --remove-orphans >/dev/null 2>&1 || true; }; \
	trap cleanup EXIT; \
	$(DOCKER_TEST_COMPOSE) run --build --rm test /app/.venv/bin/python -m pytest -q $(TEST)

qa: sync lint smoke test-domain
