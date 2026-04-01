#!/usr/bin/env bash
set -euo pipefail

docker-compose run --rm \
  -v "$(pwd):/app" \
  api \
  sh -lc '
    uv sync --frozen &&
    python -m compileall src tests scripts &&
    uv run pytest \
      tests/domain/test_sell_strategy_personal_flow.py \
      tests/domain/test_sell_risk_backfill.py \
      tests/domain/test_sell_rule_research_service.py \
      tests/domain/test_kofia_client.py \
      tests/domain/test_personal_flow_cache.py -q
  '
