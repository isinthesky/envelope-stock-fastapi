# FastAPI API Server Structure — 규칙 요약

> 원문: `skill.md` (현황 2026-11-07 기준 실제 코드로 재작성됨). 이 요약은 규칙만 압축한다.
> 이전 판(약 630줄)은 다른 프로젝트의 범용 템플릿(`ResponseBase/ResponseData`, `ErrorCodes`, `common/context.py`, `interface/api/dependencies/*`, `domain/permission|user`, QR 용어 매핑)을 담고 있어 제거했다.
> 규칙 강도: **MUST** 위반 시 설계/운영 리스크, **SHOULD** 권장.

## 1) 계층 (MUST)

- 방향: `interface → domain → adapters` (`settings`는 하위 공통). domain은 FastAPI import 금지, common은 interface/domain import 금지.
- 위치: 라우터 `src/application/interface/{api,page}/`, 서비스·DTO `src/application/domain/{feature}/`, Repository `src/adapters/database/repositories/`, 외부 IO `src/adapters/{external,cache}/`.

## 2) SSOT (MUST)

| 대상 | 위치 |
|------|------|
| DI provider + `*Dep` 별칭 | `src/application/common/dependencies.py` |
| `@transaction` | `src/application/common/decorators.py` |
| 응답 | `src/application/common/dto.py` `ResponseDTO[T]` |
| 예외 | `src/application/common/exceptions.py` |
| 예외 핸들러 | `src/settings/exception_handlers.py` |
| 설정 | `src/settings/config.py` `get_settings()` |
| DB 세션 | `src/adapters/database/connection.py` (`get_db`, `get_async_session`) |

## 3) 세션/트랜잭션 (MUST)

- 신규 계약: Repository 생성자에 세션 없이(`session=None`) 생성, 메서드가 `session` 수신, Service 공개 메서드는 `@transaction`(세션 주입 + commit/rollback; 세션이 이미 전달되면 호출자 소유).
- 레거시 계약(생성자 세션 필수): `OHLCVRepository`, `OrderRepository`, `StrategySignalRepository` — `DatabaseSession` 의존성 또는 `get_async_session()` 컨텍스트로 사용.
- Repository에서 commit/rollback 금지. Router에서 세션 생성 금지.

## 4) Interface (MUST)

- Router: 검증 → `*Dep` 주입 → 서비스 호출 → `ResponseDTO`. 비즈니스 로직 금지.
- Page Router: GET only (`fastapi-page-architecture`).
- 등록: `src/main.py` `include_router`. 관리자 페이지는 `page/__init__.py` `mypage_routers`, 공개는 `public_page_routers`.
- 접근 제어: `AdminSessionGateMiddleware`(fail-closed 로그인) + `verify_admin_access`(IP + 쓰기 `X-Requested-With`) + 주문 `require_admin_session`.

## 5) 예외/보안 (MUST)

- 서비스·의존성은 `ApplicationError` 하위 예외 raise, HTTPException 지양(잔존: `backtest_router`, `sell_rule_research_router`).
- 500 응답은 `settings.debug`일 때만 상세 노출.
- 로그 금지: KIS 토큰, appkey/secret, 계좌번호 원문, 비밀번호, 세션 쿠키.

## 6) 블라인드 스팟 (SHOULD)

- 중첩 세션(서비스→서비스 각자 세션) → 원자성 붕괴.
- commit 후 detached ORM 접근 → 경계 안에서 DTO 변환.
- 생성 직후 ID 필요 시 flush 정책 확인.

## 7) 새 기능 체크리스트

```
□ domain/{feature}/dto.py, service.py
□ adapters/database/repositories/{feature}_repository.py (신규 계약)
□ common/dependencies.py provider + *Dep
□ interface/api/{feature}_router.py + main.py include_router
□ tests/ (서비스 단위 + 라우터)
```
