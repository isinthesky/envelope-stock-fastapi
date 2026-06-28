# DOMAIN KNOWLEDGE BASE

## OVERVIEW
Business orchestration layer: services, engines, schedulers, DTOs, and trading policy. Keep it
framework-free and route-free.

## STRUCTURE
```text
domain/
|-- account/       # balance and position use cases
|-- auth/          # KIS token and approval-key use cases
|-- backtest/      # simulation engine, data loader, order/position managers
|-- market_data/   # current price, orderbook, candles
|-- ohlcv/         # cache manager, warmup/core loaders, scheduler
|-- order/         # order lifecycle and pacing/risk workflow
|-- risk/          # reusable guards such as SafetyGuard
|-- screener/      # Naver/value stock screening
`-- strategy/      # golden-cross, sell signal, universe, schedulers, notifications
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Strategy CRUD/universe | `strategy/strategy_service.py` | repository-backed use cases |
| Golden-cross candidate scan | `strategy/buy_strategy_service.py` | scan concurrency and financial filters |
| Sell signal analysis | `strategy/sell_strategy_service.py` | scoring, overlays, KOFIA/Naver hints |
| Telegram/ops alerts | `strategy/notification_scheduler.py` | data refresh and alert slots |
| OHLCV cache warmup | `ohlcv/warmup_service.py`, `ohlcv/core_loader.py` | KIS paging and freshness policy |
| Backtest facade | `backtest/service.py` | wraps engine and result summaries |
| Order operations | `order/service.py` | KIS order calls and repository updates |
| Common indicators | `../common/indicators.py` | shared technical indicators, not strategy-only |

## CONVENTIONS
- Services own policy: cache TTL choices, risk limits, scan filters, scheduler timing, retry budgets,
  and DTO shaping.
- External I/O goes through `src/adapters/*`; direct `httpx`, Redis, or SQLAlchemy model work in
  domain should be limited to established patterns already present in that service.
- Accept `AsyncSession | None` only where existing services support both repository-backed and
  read-only/network-only execution.
- Raise domain/application exceptions from `application/common/exceptions.py`; avoid leaking KIS,
  SQLAlchemy, or provider-specific exceptions to routers.
- Public service methods should be async when they touch KIS, DB, Redis, Telegram, or schedulers.

## ANTI-PATTERNS
- No FastAPI `Request`, `Response`, `APIRouter`, or dependency aliases in domain services.
- No route response wrapping here; `ResponseDTO` is an interface concern unless a shared DTO already
  requires it.
- No business decisions in adapters to compensate for missing domain logic.
- No live order submission from background jobs without existing safety guards and settings gates.

## TESTING NOTES
- Put domain tests under `tests/domain/`; `risk/` already uses a nested package pattern.
- Existing tests use inline fixtures and `@pytest.mark.asyncio`; there is no shared `conftest.py`.
- High-value existing coverage: order ops, notification scheduler, golden-cross, sell strategy,
  OHLCV loader, transaction decorator, screener.
