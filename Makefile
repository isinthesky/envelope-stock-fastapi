PYTHON ?= /opt/homebrew/bin/python3.11
VENV ?= .venv
PY ?= $(VENV)/bin/python
PIP ?= $(VENV)/bin/pip

.PHONY: sync test test-domain test-interface test-adapters smoke qa

sync:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -e .
	$(PIP) install pytest pytest-asyncio pytest-cov

test:
	$(PY) -m pytest -q

test-domain:
	$(PY) -m pytest -q tests/domain

test-interface:
	$(PY) -m pytest -q tests/interface

test-adapters:
	$(PY) -m pytest -q tests/adapters

smoke:
	$(PY) -c "from src.main import app; print(APP_OK)"

qa: sync smoke test-domain
