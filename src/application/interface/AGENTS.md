# INTERFACE KNOWLEDGE BASE

## OVERVIEW
Inbound layer for REST APIs, WebSocket, and server-rendered pages. Routers stay thin and delegate
policy to domain services.

## STRUCTURE
```text
interface/
|-- api/    # REST and WebSocket routers
`-- page/   # Jinja page routers registered through page_routers
```

Related assets outside this tree: `templates/page/*.html`, `templates/layouts/*.html`,
`static/js/pages/*.js`, and `static/styles/*.css`.

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Router mount table | `src/main.py` | prefixes, tags, admin route gating |
| API dependencies | `../common/dependencies.py` | `DatabaseSession`, `KISClientDep`, `RedisDep`, `AdminAccessDep` |
| Strategy API | `api/strategy_router.py` | public router plus `admin_router` gated in `main.py` |
| Backtest API | `api/backtest_router.py` | legacy/raw DTO responses, internal prefix |
| Ops API | `api/ops_router.py` | `/api/v1/ops` prefix and admin protection from `main.py` |
| Public page | `page/public_strategy_page_router.py` | `/page/*`, intentionally public |
| Admin pages | `page/*_page_router.py` | `/mypage/*`, include-level admin protection |
| Page registry | `page/__init__.py` | `page_routers` list consumed by `main.py` |

## CONVENTIONS
- Routers parse inputs, call a service, and return a response. Business rules and query
  composition belong in domain services.
- REST responses usually use `ResponseDTO.success_response(...)`; `backtest_router.py` is the known
  raw DTO exception.
- Prefer dependency aliases from `application.common.dependencies` over direct `Depends(...)`
  wiring in new endpoint signatures.
- Page routes render templates only; keep page behavior in matching `static/js/pages/*` files and
  data behavior in APIs.
- Prefix changes must be checked against `src/main.py`, README endpoint lists, page JavaScript, and
  interface tests.

## ANTI-PATTERNS
- Do not call repositories or SQLAlchemy models directly from routers.
- Do not add `/mypage/*` routes outside the protected include path in `src/main.py`.
- Do not accidentally wrap `/page/*` public routes in admin dependencies.
- Do not re-enable OpenAPI docs from routers; docs are disabled at the FastAPI app level.

## TESTING NOTES
- Interface tests live under `tests/interface/`.
- Existing tests cover admin access, exception handlers, mypage/public boundary, ops page, sell
  strategy page, strategy router security, and Telegram notifier behavior.
