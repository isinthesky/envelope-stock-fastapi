# DATABASE ADAPTER KNOWLEDGE BASE

## OVERVIEW
Outbound persistence adapter for async SQLAlchemy models, sessions, repositories, and Alembic
migrations. It stores state; it does not decide trading policy.

## STRUCTURE
```text
database/
|-- connection.py      # async engine/session factories and close_db
|-- models/            # SQLAlchemy ORM models
`-- repositories/      # repository pattern over AsyncSession
```

Migrations live in `alembic/versions/` and must track model/schema changes.

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Engine/session setup | `connection.py` | `AsyncSessionLocal`, `get_db`, `close_db` |
| Base CRUD | `repositories/base_repository.py` | shared CRUD, pagination/search/stat mixins |
| Strategy persistence | `models/strategy*.py`, `repositories/strategy*_repository.py` | strategy and symbol state tables |
| OHLCV cache | `models/ohlcv.py`, `repositories/ohlcv_repository.py` | used by backtest and OHLCV services |
| Analysis history | `models/analysis_history.py`, `repositories/analysis_history_repository.py` | strategy analysis persistence |
| Access logs | `models/access_log.py`, `repositories/access_log_repository.py` | public-page access log surface |
| Personal/credit snapshots | `models/personal_flow_snapshot.py`, `models/market_credit_snapshot.py` | sell-risk inputs |

## CONVENTIONS
- Repository methods should accept or use `AsyncSession`; keep transaction ownership aligned with
  the calling service/decorator.
- Models define storage shape only. DTO conversion and policy calculations stay in domain services.
- Pair schema-affecting model changes with an Alembic revision and a focused repository/domain test.
- Keep repository naming consistent: `<entity>_repository.py` with `<Entity>Repository`.
- Use explicit SQLAlchemy expressions and typed return values; avoid hiding broad query behavior in
  generic helper methods unless it is reused.

## ANTI-PATTERNS
- No KIS, Redis, Telegram, or HTTP calls from database adapters.
- No cache TTL, risk threshold, scan eligibility, or scheduler policy in repositories.
- No migrations that depend on local data files, secrets, or runtime API calls.
- No direct sync SQLAlchemy sessions in this async application path.

## TESTING NOTES
- Adapter tests live in `tests/adapters/`; repository-heavy tests currently sit mostly in
  `tests/domain/`.
- CodeGraph flagged `OHLCVRepository` as central with no direct covering test; verify callers when
  changing it.
