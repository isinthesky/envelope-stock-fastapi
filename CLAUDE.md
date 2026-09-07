# CLAUDE.md - KIS Strategy & Alert Server 프로젝트 가이드

> FastAPI 기반 KIS(Open API) 전략/알림 서버. **헥사고날(Ports & Adapters)** 구조를 유지합니다.

## 레이어(폴더) 한눈에 보기

```text
Inbound (HTTP/WS/Page)        Application                 Outbound (I/O)
src/application/interface  -> src/application/domain  ->  src/adapters/*
                                ↑
                           src/application/common
                                ↑
                           src/settings
```

## 의존성 규칙 (Do / Don't)
- **허용 방향**: `interface → domain → adapters`
- **공통 사용**: `settings`, `application/common`은 모든 레이어에서 사용 가능
- **금지**
  - `domain`에서 FastAPI 객체(`Request`, `Response`) 직접 사용 금지
  - `interface`에서 DB 모델/Repository 직접 호출 금지(서비스 호출만)
  - `adapters`에서 비즈니스 규칙/정책 결정 금지(순수 I/O)

## 실행/개발 명령
- **의존성 설치**: `uv sync`
- **개발 서버**: `uvicorn src.main:app --reload`
- **테스트**:
  ```bash
  docker run --rm -v /Users/m2-dev/Apps/kis-strategy-alert-server:/work -w /work -e PYTHONPATH=/work -e UV_PROJECT_ENVIRONMENT=/tmp/kis-test-venv kis-strategy-alert-server-api uv run pytest tests/ -q
  ```
- **품질 도구**: `black src/ tests/`, `isort src/ tests/`, `mypy src/`

## ⚠️ 운영 함정
- **전략 활성화는 실주문 경로를 연다**: 월~금 `15:35`(`strategy_execution_hour/minute` 기본 15/35)에 `StrategyScheduler._execute_strategies_job`가 `status="active"`인 `golden_cross` 전략을 `dry_run=False`로 실행한다(`domain/strategy/scheduler.py`). 이 경로의 kill-switch는 `strategy_live_trading_enabled`(env `STRATEGY_LIVE_TRADING_ENABLED`, 기본 `False`, `settings/config.py`)이며, `GoldenCrossEngine.execute`가 `not dry_run and not settings.strategy_live_trading_enabled`이면 주문 없이 에러만 담아 반환한다(`domain/strategy/golden_cross_engine.py:137`). 관리자 IP는 `POST /api/v1/strategies/{id}/execute`로 `dry_run=false` 수동 실행도 호출할 수 있으나 같은 kill-switch가 막는다. **단, 이 스위치는 골든크로스 전략 실행 경로 전용이지 서버 전체의 주문 차단기가 아니다** — 아래 별도 함정 참고. 전략 CRUD admin router는 `enable_admin_strategy_routes=False` 기본값으로 미마운트다(`src/main.py`). **안전의 근거를 "전략 행이 없음"에 두지 말 것** — 행 수와 `status`는 언제든 바뀌므로 kill-switch 기본값 + `status`를 근거로 삼는다. `status`를 `active`로 바꾸고 kill-switch를 켜는 순간 실주문이 나간다. 이 실주문 job만 `misfire_grace_time=90`초(`strategy_execution_misfire_grace_seconds`)이고 나머지 스케줄러 job은 `SCHEDULER_JOB_DEFAULTS`의 `300`초/`coalesce`를 쓴다. 현재 kill-switch 상태는 `/mypage/strategy/dashboard` 상단 배지(`실주문 스위치 ON/OFF`)로 확인한다.
- **`POST /api/v1/orders`는 kill-switch를 우회하는 별개의 실주문 경로**: `src/main.py`가 `order_router`를 조건 없이 마운트하고(`prefix="/api/v1/orders"`), `create_order` → `OrderService.create_order`(`domain/order/service.py`)가 KIS `/uapi/domestic-stock/v1/trading/order-cash`를 `TTTC0802U`(실전 매수)/`TTTC0801U`(실전 매도)로 호출한다. `TRADING_ENVIRONMENT=prod`면 `is_paper_trading=False`라 실계좌 주문이다. 이 경로에는 `strategy_live_trading_enabled` 검사가 **없고**(전체 grep 기준 참조 지점은 `config.py` 정의, `golden_cross_engine.py:137`, `strategy_dashboard_page_router.py`, 템플릿뿐), 유일한 게이트는 `AdminAccessDep`(= `verify_admin_access`: `ADMIN_ALLOWED_IPS` IP allowlist + 쓰기 메서드용 `X-Requested-With: XMLHttpRequest` 헤더)다. 따라서 `/mypage/strategy/dashboard`의 `실주문 스위치 OFF` 배지는 **전략 실행 경로**에 대한 표시일 뿐이며, 실질 방어선은 `ADMIN_ALLOWED_IPS` 범위 관리다.
- **재빌드·재배포는 안전함**: `kis_token_cache` named volume이 KIS 토큰 캐시를 보존하므로 `docker compose build`와 `docker compose up -d --build`는 토큰을 재발급하지 않는다. 단, `force_refresh=True`를 남발하지 말고 토큰은 1일 1회 발급 원칙을 지킨다.
- **컨테이너 하드닝은 파일 변경만 완료, 미배포(2026-09-08)**: `Dockerfile`은 비루트 `uid 10001`/`HOME=/home/appuser`로, `docker-compose.yml`은 토큰 볼륨을 `kis_token_cache:/home/appuser/KIS/config`로 바꿔 두었으나 **아직 재빌드하지 않았다.** 실행 중인 컨테이너는 여전히 root + `/root/KIS/config` 이미지다. 적용 절차·검증·롤백은 `README.md`의 「컨테이너 하드닝 적용 절차(미적용)」를 따른다. 적용 후에는 토큰 경로가 `HOME`으로 결정되므로(`auth.py`의 `Path.home()`), 컨테이너 안에서 `uv run`은 `/app/.venv` 쓰기 때문에 실패한다 — **`/app/.venv/bin/<cmd>`를 직접 실행한다**(`PYTHONPATH=/app`은 이미 이미지 ENV). `docker compose exec --user root api ...`는 기본 수단으로 쓰지 않는다: `--user`는 `HOME`을 재설정하지 않아 `ENV HOME=/home/appuser`를 그대로 상속하므로, KIS 인증을 타는 명령이면 토큰 캐시 볼륨에 root 소유 파일을 남겨 이후 `uid 10001` 프로세스의 토큰 재발급을 유발한다. 부득이하면 `-e HOME=/tmp`를 함께 주고, 작업 후 `chown -R 10001:10001`로 되돌린다(README 「컨테이너 하드닝 적용 절차」).

## 코드 추가 위치 가이드
- **새 REST API**: `src/application/interface/api/*_router.py` + `src/main.py`에 `include_router`
- **새 페이지(대시보드)**: `src/application/interface/page/*_page_router.py` + `page/__init__.py`의 **`mypage_routers`(관리자 `/mypage/*`) 또는 `public_page_routers`(공개 `/page/*`)** 중 하나에 등록. `src/main.py`는 이 두 리스트만 import하며 `mypage_routers`만 `dependencies=[Depends(verify_admin_access)]`로 include한다. `page_routers`는 두 리스트를 합친 하위호환 별칭이고 `main.py`는 사용하지 않으므로, 여기에만 추가하면 라우트가 등록되지 않는다.
- **새 유즈케이스/서비스**: `src/application/domain/<domain>/service.py` (DTO는 `dto.py`)
- **새 외부 연동(KIS 외 API 등)**: `src/adapters/external/<provider>/...`
- **새 DB 엔티티/Repository**: `src/adapters/database/models`, `src/adapters/database/repositories`
- **환경 변수/설정 추가**: `src/settings/config.py` (+ `.env.example`는 템플릿만)

## 보안/운영 주의
- **절대 커밋 금지**: `.env`, 실전 키/시크릿/계좌번호, 토큰 캐시 파일류
- 로그에 인증정보를 남기지 말 것(특히 URL credential, 토큰)

## 레이어별 상세 문서
- `docs/base/CLAUDE.md` (문서 레이어 운영 규칙)
- `src/CLAUDE.md` (서버 엔트리포인트/라우터/라이프사이클)
- `src/application/CLAUDE.md` (application 하위 레이어 개요)
- `src/application/common/CLAUDE.md` (DTO/DI/데코레이터/태스크)
- `src/application/domain/CLAUDE.md` (도메인 서비스/엔진/스케줄러)
- `src/application/interface/CLAUDE.md` (API/WS/Page 라우팅 규칙)
- `src/adapters/CLAUDE.md` (DB/Redis/KIS/Naver/Telegram/WS 인프라)
- `src/settings/CLAUDE.md` (설정 규칙/환경 변수)
