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
- **전략 실주문 체결 모델(2026-11-06 수정)**: 엔진은 기본적으로 **장후 시간외 종가**(`STRATEGY_ORDER_PRICE_TYPE=closing`, KIS `ORD_DVSN 06`, 단가 0, 접수 15:30~16:00·체결 15:40~16:00)로 주문한다 — 15:35 실행에서 정규장 지정가(`00`)는 장 마감 뒤라 체결될 수 없었고, 시간외 종가는 백테스트의 "신호봉 종가 체결" 가정과 일치한다. 접수 직후 시그널은 `PENDING`+`order_no`(+`metadata_json.broker_order_id`, 매도는 `entry_price`)로 남고, **16:10 `daily_order_reconcile` job**(그리고 다음 실행 시작 시)이 `inquire-daily-ccld`(GET)로 체결을 확인해 `EXECUTED`(실제 평균체결가·수량, 매도는 수수료·매도세 차감 실현손익, 국내 ETF 거래세 면제) 또는 미체결 `CANCELLED`(매수 → WAITING, 매도 → 브로커 잔고 기준 IN_POSITION 복원)로 확정한다. 중복 주문 가드는 `order_no`가 있으면 `CANCELLED`가 아닌 한 재주문을 막고, 매도 일부 체결(`executed_quantity < target_quantity`)만 잔량 재매도를 허용한다. 매수 사이징은 `available_amount`(주문가능현금, TTTC8908R `ord_psbl_cash`) × `allocation_ratio`, 계좌 합계는 TTTC8434R `output2`. ⚠️ `06` 주문의 실제 KIS 수용 여부(단가 "0")는 실주문 전 소액으로 1회 확인할 것 — 모의투자는 시간외를 지원하지 않을 수 있다.
- **시장 국면 게이트는 실주문 엔진에도 적용된다**: `GC_REGIME_FILTER_ENABLED`면 엔진이 실행당 1회 벤치(`GC_REGIME_BENCHMARK`)로 판정해 **신규 매수만** 막는다(`SKIPPED`/`exit_reason=regime_block`, 상태 WAITING 리셋 = 백테스트 `regime_block`과 동일). 실주문은 데이터 불량 시 **fail-closed**, 스캔/알림은 fail-open(`domain/strategy/market_regime.py`). ⚠️ 2026-11-06 이전에는 `regime_filter.wilder_adx_series`가 `replace(0.0, pd.NA)`로 object dtype이 돼 **라이브 레짐 판정이 항상 예외 → fail-open**이었다(= 필터가 켜져 있어도 무효). 로그 `[regime] evaluation failed`가 보이면 재발이다.
- **`POST /api/v1/orders`는 kill-switch를 우회하는 별개의 실주문 경로**: `src/main.py`가 `order_router`를 조건 없이 마운트하고(`prefix="/api/v1/orders"`), `create_order` → `OrderService.create_order`(`domain/order/service.py`)가 KIS `/uapi/domestic-stock/v1/trading/order-cash`를 `TTTC0802U`(실전 매수)/`TTTC0801U`(실전 매도)로 호출한다. `TRADING_ENVIRONMENT=prod`면 `is_paper_trading=False`라 실계좌 주문이다. 이 경로에는 `strategy_live_trading_enabled` 검사가 **없고**(전체 grep 기준 참조 지점은 `config.py` 정의, `golden_cross_engine.py:137`, `strategy_dashboard_page_router.py`, 템플릿뿐), 게이트는 `AdminAccessDep`(= `verify_admin_access`: `ADMIN_ALLOWED_IPS` IP allowlist + 쓰기 메서드용 `X-Requested-With: XMLHttpRequest` 헤더)와 **관리자 로그인 세션**(`require_admin_session`, `main.py`가 `order_router` include-level로 부착) 두 겹이다. 따라서 `/mypage/strategy/dashboard`의 `실주문 스위치 OFF` 배지는 **전략 실행 경로**에 대한 표시일 뿐이며, 실질 방어선은 `ADMIN_ALLOWED_IPS` 범위 + 관리자 계정 비밀번호다.
- **배포 진입점(2026-11-06)**: 외부 접근은 `https://stock.lgetech.co.kr`(`~/Apps/nginx-proxy`의 `nginx/conf.d/stock-https.conf` → `host.docker.internal:10131`)뿐이다. api 포트는 `127.0.0.1:10131` 전용 바인딩(`API_BIND_HOST`)이라 `http://<LAN/공인 IP>:10131` 직접 접근은 제거됐다. 호스트발 연결은 kis-network 게이트웨이 `172.18.0.1`로 보이므로 `TRUSTED_PROXY_IPS`에 포함해 nginx의 `X-Forwarded-For`(실제 클라이언트 IP)를 쓴다. 같은 LAN에서 도메인으로 접속하면 헤어핀 NAT로 `192.168.0.1`로 기록된다.
- **전역 로그인 게이트**: `AdminSessionGateMiddleware`(`interface/admin_session_gate.py`, `main.py` 최외곽)가 공개 경로(`/page*`, `/static/*`, `/api/v1/public/*`, `/mypage/login`, `/api/v1/admin-auth/{login,logout}`, `/health`) **외 전 경로**(HTTP·WebSocket, 존재하지 않는 경로 포함)에 로그인 세션을 요구한다 — 기본 거부라 새 라우터도 자동 보호된다. 미로그인 HTML(`GET /mypage*`, `/ops*`)은 `/mypage/login/?next=`로 303, 그 외 401 JSON, WebSocket은 핸드셰이크 거부. 공개 경로를 늘릴 땐 `PUBLIC_EXACT_PATHS`/`PUBLIC_PATH_PREFIXES`와 `tests/interface/test_admin_login_boundary.py`를 함께 고친다. `ADMIN_ALLOWED_IPS`(현재 전 대역)는 게이트 안쪽의 부가 계층일 뿐이다.
- **관리자 로그인(ID/PW 세션)**: 전역 게이트에 더해 `/mypage/order`(미로그인 시 `/mypage/login/`으로 303)와 `/api/v1/orders/*` 전체(미로그인 401)는 라우트 단위로도 로그인 세션을 재검사한다. 계정은 단일 운영자 계정 `ADMIN_USERNAME` + `ADMIN_PASSWORD_HASH`(scrypt, `python3 scripts/ops/hash_admin_password.py`로 생성)이며, 둘 중 하나라도 비면 로그인이 비활성화되어 주문 경로는 **전부 거부**된다(fail-closed). 세션은 Redis `admin_session:<sha256(token)>`에 절대 TTL(`ADMIN_SESSION_TTL_SECONDS`, 기본 12h)로 저장되고, 쿠키 `kis_admin_session`은 `HttpOnly`/`SameSite=Strict`다. IP별 실패 `ADMIN_LOGIN_MAX_FAILURES`(기본 5)회 초과 시 `ADMIN_LOGIN_LOCKOUT_SECONDS`(기본 900초) 동안 429. 비밀번호 해시를 바꾸면 기존 세션은 전부 무효화된다. 로그인 API는 `/api/v1/admin-auth/{login,logout,me}`(IP 게이트 적용). HTTPS 전용 배포이므로 `ADMIN_SESSION_COOKIE_SECURE=true`(Secure 쿠키)다 — 로컬 점검 시 `http://127.0.0.1:10131`에서는 브라우저 로그인이 유지되지 않을 수 있다(curl `-b`는 동작).
- **일봉 캐시는 장 마감(15:31 KST) 전 당일 봉을 저장하지 않는다(2026-11-06)**: 장전/장중에 받은 당일 일봉(현재가·누적거래량)이 확정 봉처럼 캐시되면 16:00 증분 업데이트가 "오늘 봉 있음"으로 보고 덮어쓰지 않아 15:35 전략·스캔·백테스트가 잠정값을 썼다(2026-03-30~11-06 사이 5개 날짜에 유니버스 전체 보합 봉, 다수 장중 봉 — 221종 재조회로 복구). 가드는 `OHLCVRepository.save_candles_bulk`(`common/trading_calendar.is_provisional_daily_bar`)이며 로더는 API 결과를 메모리로는 그대로 반환한다(장중 스캔 영향 없음). 업서트는 이제 `updated_at`을 갱신하므로 "봉 날짜와 같은 날 15:31 전 updated_at" 쿼리로 재발을 탐지할 수 있다. 보존 기간은 `OHLCV_RETENTION_DAYS`(기본 3650) — 줄이면 02:00 정리 job이 연구용 과거 데이터(2018~)를 지운다.
- **재빌드·재배포는 안전함**: `kis_token_cache` named volume이 KIS 토큰 캐시를 보존하므로 `docker compose build`와 `docker compose up -d --build`는 토큰을 재발급하지 않는다. 기동 로그 `KIS API token ready (source=cache|issued, ...)`로 확인한다. 단, `force_refresh=True`를 남발하지 말고 토큰은 1일 1회 발급 원칙을 지킨다.
- **토큰 캐시 규칙(2026-11-06 수정)**: `KISAuth`(`adapters/external/kis_api/auth.py`)는 캐시 디렉터리의 모든 `KIS{YYYYMMDD}` 파일 중 **유효하고 가장 늦게 만료되는 토큰**을 재사용한다(파일명 날짜 무관). 이전엔 파일명이 프로세스 시작일로 고정돼 다른 날 재기동하면 재발급했다. 만료 시각은 KIS가 주는 **KST 벽시계 시각**이므로 `TokenInfo.expires_at`은 KST aware로 정규화된다(컨테이너는 UTC — 이전엔 naive 비교로 실제 만료 후 9시간 동안 유효로 오판해 매일 최대 ~8시간 KIS 호출이 실패할 수 있었다). KIS가 토큰을 거부(EGW00123/401)하면 클라이언트는 `refresh_token(rejected_token=...)`으로 그 토큰을 후보에서 제외한다. 저장은 발급일(KST) 파일에 임시 파일 + `os.replace`(0600)로 원자적으로 하고, `valid-date`는 `+09:00` ISO 문자열이다(레거시 naive 값은 KST로 해석). 회귀 테스트: `tests/adapters/test_kis_token_cache.py`.
- **컨테이너 하드닝 적용 완료(2026-09-08 배포)**: api는 비루트 `uid 10001`/`HOME=/home/appuser`로 실행되고, 토큰 볼륨은 `kis_token_cache:/home/appuser/KIS/config`에 마운트된다. Redis는 비밀번호 없이는 기동을 거부하고 `gosu redis`(uid 999)로 강등되며, postgres/redis는 `127.0.0.1` 전용 바인딩이다. 배포 시 토큰 재발급은 없었다(파일 35개 해시 불변, 2회차 재기동으로 확정). 롤백 절차는 `README.md`의 「컨테이너 하드닝 적용 절차」를 따른다. 토큰 경로가 토큰 경로가 `HOME`으로 결정되므로(`auth.py`의 `Path.home()`), 컨테이너 안에서 `uv run`은 `/app/.venv` 쓰기 때문에 실패한다 — **`/app/.venv/bin/<cmd>`를 직접 실행한다**(`PYTHONPATH=/app`은 이미 이미지 ENV). `docker compose exec --user root api ...`는 기본 수단으로 쓰지 않는다: `--user`는 `HOME`을 재설정하지 않아 `ENV HOME=/home/appuser`를 그대로 상속하므로, KIS 인증을 타는 명령이면 토큰 캐시 볼륨에 root 소유 파일을 남겨 이후 `uid 10001` 프로세스의 토큰 재발급을 유발한다. 부득이하면 `-e HOME=/tmp`를 함께 주고, 작업 후 `chown -R 10001:10001`로 되돌린다(README 「컨테이너 하드닝 적용 절차」).

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
