---
name: fastapi-api-server-structure
description: 이 저장소(FastAPI 헥사고날) API 서버의 계층 구조, 세션/트랜잭션 계약(@transaction), DI(SSOT), 응답/예외 표준, 라우터 등록 규칙. 리팩토링·신규 기능 추가 시 사용합니다.
---

# FastAPI API Server Structure

> 현황 2026-11-07 기준 실제 코드로 재작성. 이전 판의 범용 경로(`common/context.py`, `common/response.py`의 `ResponseData`, `interface/api/dependencies/service.py`, `settings/exceptions.py`의 `ErrorCodes`, `common/constants.py`, `dispatch.py`, `domain/permission|user/*`)는 이 저장소에 없음.
> 관련 스킬: `fastapi-page-architecture`(페이지), `fastapi-exception-handling`(예외). 레이어별 상세는 `src/**/CLAUDE.md`.

## 1. 계층 구조와 의존 방향

```
src/
├── main.py              # 앱, 미들웨어(CORS·AccessLogging·AdminSessionGate), 예외 핸들러, include_router
├── settings/            # config.py(get_settings), exception_handlers.py, logging_config.py
├── adapters/            # database(connection, models, repositories), cache(redis), external(kis_api, krx, dart_api, naver, telegram, websocket, kofia)
└── application/
    ├── common/          # dto.py, dependencies.py(DI), decorators.py, exceptions.py, indicators.py, performance_metrics.py, trading_calendar.py, client_ip.py, middleware/
    ├── domain/          # {feature}/ (dto.py, service.py, 엔진/스케줄러 등)
    └── interface/       # api/*_router.py, page/*_page_router.py, admin_session_gate.py
```

- **MUST**: `interface → domain → adapters`. domain은 FastAPI import 금지(현재 위반 0건). common은 interface/domain import 금지.
- Repository 구현은 `src/adapters/database/repositories/`(도메인 폴더 아님).

## 2. SSOT 위치

| 대상 | 위치 |
|------|------|
| DI(Repository/Service/외부 클라이언트/관리자 게이트) | `src/application/common/dependencies.py` (`*Dep = Annotated[...]` 별칭) |
| 트랜잭션 | `src/application/common/decorators.py` `@transaction` (+ `@retry`, `@cache`, `@log_execution`) |
| 응답 모델 | `src/application/common/dto.py` `ResponseDTO[T]`(`success_response`/`error_response`), `PaginatedResponseDTO`, `BaseDTO` |
| 예외 | `src/application/common/exceptions.py` (`ApplicationError` 계층) |
| 설정 | `src/settings/config.py` `get_settings()` |
| DB 세션 | `src/adapters/database/connection.py` `AsyncSessionLocal`, `get_db`, `get_async_session()`(백그라운드용 컨텍스트 매니저, 자동 commit/rollback) |

중복 DI 정의 금지 — 라우터에서 provider를 새로 만들지 말고 `dependencies.py`에 추가.

## 3. 세션/트랜잭션 계약 (현재 혼재)

| 계약 | 대상 | 규칙 |
|------|------|------|
| **신규(권장)** | `StrategyRepository`, `AnalysisHistoryRepository`, `StockUniverseRepository`, `StrategySymbolStateRepository` 등 `session: AsyncSession \| None = None` 생성자 | DI는 세션 없이 생성, 메서드가 `session` 파라미터 수신. Service 공개 메서드에 `@transaction` → `(self, session, ...)`로 세션 주입·commit/rollback. 이미 session이 전달된 내부 호출은 호출자 소유 |
| **레거시** | `OHLCVRepository`, `OrderRepository`, `StrategySignalRepository` (생성자 session 필수) | `get_order_repository(DatabaseSession)` 또는 `async with get_async_session() as s: Repo(s)` |

- Repository 내부 commit/rollback 금지(상위 경계에서 처리).
- 신규 코드는 신규 계약을 따른다. Service→Service 호출 시 세션 전달로 원자성 유지.

## 4. Interface 규칙

- 라우터: Pydantic 입력 검증 → `*Dep`로 서비스 주입 → 서비스 호출 → `ResponseDTO`로 래핑. 비즈니스 로직/세션 생성 금지.
- 등록: `src/main.py`에서 `include_router`. prefix는 라우터 내부(`/api/v1/backtest` 등) 또는 include 시 지정 — 혼재하므로 변경 시 main.py와 함께 확인.
- 접근 제어: `AdminSessionGateMiddleware`(공개 경로 외 로그인 세션 필수) → `verify_admin_access`(`AdminAccessDep`, IP allowlist + 쓰기 메서드 `X-Requested-With: XMLHttpRequest`) → 주문 API는 `require_admin_session` 추가. 공개 API는 `/api/v1/public/*`.
- 관리자 전용 전략 CUD 라우트(`strategy_admin_router`)는 `settings.enable_admin_strategy_routes`일 때만 등록.

## 5. 응답/예외 표준

- 성공: `ResponseDTO(success=True, message, data)`; 실패: 전역 핸들러가 `{"success": false, "message", "data": null, "error": {code, message, details}}`로 변환.
- 서비스/의존성은 `ApplicationError` 하위 예외를 raise(HTTPException 지양). 상세: `fastapi-exception-handling`.

## 6. 체크리스트 — 새 기능

```
□ domain/{feature}/dto.py (BaseDTO), service.py (@transaction, DTO 반환)
□ adapters/database/repositories/{feature}_repository.py (신규 세션 계약)
□ common/dependencies.py에 provider + *Dep 별칭
□ interface/api/{feature}_router.py (ResponseDTO, AdminAccessDep 등)
□ main.py include_router (+ 공개 여부/게이트 확인)
□ tests/ 단위(서비스 mock repo) + 라우터 테스트
```

테스트 실행: `docker run --rm -v <repo>:/work -w /work -e PYTHONPATH=/work -e UV_PROJECT_ENVIRONMENT=/tmp/kis-test-venv kis-strategy-alert-server-api uv run pytest tests/ -q`

## 7. 자주 깨지는 지점

- 중첩 세션: Service→Service 호출 시 각자 세션 생성 → 원자성 깨짐(세션 전달).
- Detached ORM: commit 후 ORM 접근 → 경계 안에서 DTO 변환.
- 민감정보(토큰/계좌/비밀번호) 로깅 금지.
