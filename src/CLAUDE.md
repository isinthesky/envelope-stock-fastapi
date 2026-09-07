# CLAUDE.md - `src/` (소스 루트) 가이드

> FastAPI 애플리케이션 엔트리포인트(`main.py`)와 레이어 진입점(`application/`, `adapters/`, `settings/`)을 포함합니다.

## 이 레이어의 역할
- FastAPI 앱 생성/설정(CORS, OpenAPI 노출 정책, 전역 예외 핸들러)
- 애플리케이션 라이프사이클(startup/shutdown)에서 인프라/백그라운드 작업 시작/정리
- 라우터 등록(REST/WS/Page)

## 폴더 구조

```text
src/
  main.py          # FastAPI 앱/라이프사이클/라우터 등록
  settings/        # Pydantic Settings + 로깅 부트스트랩
  adapters/        # DB/Redis/KIS/Naver/Telegram/WS
  application/     # interface/domain/common
```

## `main.py` 실행 흐름(현재 코드 기준)
- **모듈 로드(import 시점)**
  - `settings.logging_config.setup_logging()` 호출 — dictConfig 로 콘솔(stdout) 로깅을 설정하고, `LOG_TO_FILE=true` 면 회전 파일 핸들러를 추가한다. 라우터/서비스 import 보다 반드시 앞서야 한다.
  - `AccessLoggingMiddleware` 등록(`/page` 경로만 DB 기록, 클라이언트 IP는 `common/client_ip.py` 규칙).
- **lifespan(startup)**
  - DB 연결 점검(`SELECT 1`)
  - Redis 연결 점검(`ping`)
  - `settings.auto_reauth`가 true면 KIS 토큰 발급 및 자동갱신 태스크 시작
  - 전략 스케줄러/알림/캐시 스케줄러 시작
    - `domain.strategy.scheduler` (Golden Cross)
    - `domain.strategy.notification_scheduler` (Telegram)
    - `domain.ohlcv.scheduler` (OHLCV cache)
- **라우터 등록**
  - REST:
    - `/api/v1/auth` (Auth)
    - `/api/v1/market` (MarketData)
    - `/api/v1/accounts` (Account)
    - `/api/v1/orders` (Order)
    - `/api/v1/strategies` (Strategy: 라우터 단위 `verify_admin_access` 보호. 전략 CRUD admin 라우터는 `enable_admin_strategy_routes=True` 일 때만 추가 마운트)
    - `/api/v1/strategies` (SellRuleResearch: 라우터 내부 prefix)
    - `/api/v1/ops` (Operations: `AdminAccessDep` 보호)
    - `/api/v1/public/strategies` (공개 전략 스캔: 라우터 내부 prefix)
    - `/api/v1/screener` (Screener: 라우터 내부 prefix)
    - `/api/v1/recommendations` (Recommendation: 라우터 내부 prefix)
    - `/api/v1/backtest` (Backtest: 라우터 내부 prefix)
    - `/api/v1/access-logs` (AccessLogs: 라우터 내부 prefix, 관리자 IP 전용)
  - WebSocket: `/ws`
  - Page(Jinja2): **두 개의 별도 루프**로 등록한다(각 라우터가 자체 prefix 보유).
    - `mypage_routers` → `dependencies=[Depends(verify_admin_access)]` 와 함께 include(= `/mypage/*`와 `/ops`의 include-level IP 게이트)
    - `public_page_routers` → 의존성 없이 include(`/page/*` 공개 포털)
    - `page/__init__.py`의 `page_routers`는 두 리스트를 합친 하위호환 별칭이며 `main.py`는 사용하지 않는다. 새 페이지는 반드시 위 두 리스트 중 하나에 넣어야 등록된다.
- **기본 엔드포인트**
  - `/` : 간단 상태 요약(dict)
  - `/health` : 인프라 실검사. DB `SELECT 1`, Redis `ping`, KIS 토큰 유효성(`get_kis_auth().token_info`)을 확인해
    `{"status", "database", "redis", "kis_api"}` 를 반환한다. DB/Redis 실패는 `status`를 `degraded`로 낮추지만
    KIS 토큰은 `kis_api: unauthenticated|unavailable`로만 표기하고 `status`에는 반영하지 않는다. HTTP 상태는 항상 200이다.
- **lifespan(shutdown)**
  - scheduler/task stop → httpx 클라이언트 close → DB/Redis close 순서로 정리

## 구현 규칙
- `src/main.py`는 **조립/설정/라이프사이클**만 담당하고, 비즈니스 로직을 넣지 않습니다.
- 라우터/서비스/인프라 코드는 각각:
  - `application/interface`, `application/domain`, `adapters`로 이동합니다.

## 관련 문서
- `src/application/CLAUDE.md`
- `src/application/interface/CLAUDE.md`
- `src/application/domain/CLAUDE.md`
- `src/adapters/CLAUDE.md`
- `src/settings/CLAUDE.md`

