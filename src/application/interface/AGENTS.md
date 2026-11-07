# INTERFACE KNOWLEDGE BASE

## OVERVIEW
Inbound layer for REST APIs, WebSocket, and server-rendered pages. Routers stay thin and delegate
policy to domain services.

## STRUCTURE
```text
interface/
|-- api/                   # REST and WebSocket routers
|-- page/                  # Jinja page routers registered through mypage_routers / public_page_routers
`-- admin_session_gate.py  # global login-gate middleware (default deny)
```

Related assets outside this tree: `templates/page/*.html`, `templates/layouts/*.html`,
`static/js/pages/*.js`, and `static/styles/*.css`.

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Router mount table | `src/main.py` | prefixes, tags, admin route gating |
| API dependencies | `../common/dependencies.py` | `DatabaseSession`, `KISClientDep`, `RedisDep`, `AdminAccessDep` |
| Strategy API | `api/strategy_router.py` | `router` (admin-only: `verify_admin_access` at include level) plus `admin_router` (CRUD) mounted only when `enable_admin_strategy_routes=True` |
| Backtest API | `api/backtest_router.py` | legacy/raw DTO responses, internal prefix |
| Ops API | `api/ops_router.py` | internal `/api/v1/ops` prefix; per-endpoint `AdminAccessDep` |
| Access log API | `api/access_log_router.py` | `/api/v1/access-logs`, admin-gated; delegates to `domain/access_log/service.py` |
| Public page | `page/public_strategy_page_router.py` | `/page/*`, intentionally public |
| Admin pages | `page/*_page_router.py` | `/mypage/*`, include-level admin protection |
| Page registry | `page/__init__.py` | `main.py` consumes `mypage_routers` (with `verify_admin_access`) and `public_page_routers`; `page_routers` is a legacy alias NOT used by `main.py` |
| Login gate | `admin_session_gate.py` | `PUBLIC_EXACT_PATHS`/`PUBLIC_PATH_PREFIXES` whitelist; everything else needs an admin session |
| Admin login API | `api/admin_auth_router.py` | `/api/v1/admin-auth/{login,logout,me}`; cookie `kis_admin_session` |

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
- Never read `request.client.host` or `X-Forwarded-For` directly; use `get_client_ip()` from
  `../common/client_ip.py` so admin checks, public cooldowns, access logs, and WebSocket agree.
- Sell-related pages carry an engine-origin badge (`p.engine-note` + `span.engine-badge`) so E1/E2/E3
  results are never confused; see `docs/buy-sell-usage-guide.md` §2 and
  `tests/interface/test_admin_page_engine_badges.py`.

## ANTI-PATTERNS
- Do not call repositories or SQLAlchemy models directly from routers.
- Do not add `/mypage/*` routes outside the protected include path in `src/main.py`.
- Do not accidentally wrap `/page/*` public routes in admin dependencies.
- Do not re-enable OpenAPI docs from routers; docs are disabled at the FastAPI app level.
- Do not widen the login-gate whitelist without updating `tests/interface/test_admin_login_boundary.py`.

## TESTING NOTES
- Interface tests live under `tests/interface/`.
- Existing tests cover admin access, admin login boundary/global gate, exception handlers,
  mypage/public boundary, ops page, sell strategy page, strategy router security, and Telegram
  notifier behavior.
