# 증권 전략·알림 서버 서비스 구현 가이드

> **KIS Strategy & Alert Server**의 도메인별 구현 규칙 및 개발 가이드 (현재 코드 기준, 2026-11-07 재동기화)

## 📋 프로젝트 개요

### 서비스 정보
- **서비스명**: KIS Strategy & Alert Server
- **포트**: 컨테이너 내부 `8000`(`settings.port`), 호스트 `127.0.0.1:10131`(`API_BIND_HOST`/`API_PORT`). 외부 접근은 `https://stock.lgetech.co.kr`(nginx-proxy)만
- **역할**: 한국투자증권 Open API 기반 전략 실행 및 알림 서비스
- **기술스택**: FastAPI, PostgreSQL + SQLAlchemy(async, asyncpg) + Alembic, Redis, httpx, APScheduler, Jinja2, UV

### 주요 기능
- ✅ **골든크로스 전략** — 매수 스캔/추천, FSM 기반 실행 엔진(실주문은 kill-switch로 기본 차단, 현재 전략 `paused`)
- ✅ **매도 분석** — `ScoreRule` 파이프라인 점수 → Stage(REDUCE_1 28 / REDUCE_2 49 / EXIT_ALL 70)
- ✅ **계좌/주문** — 잔고·포지션 조회, 수동 주문(관리자 로그인 필요)
- ✅ **알림** — Telegram 매수/매도 알림 슬롯(플래그로 on/off)
- ✅ **검증** — 백테스트, walk-forward, 라이브 패리티 리플레이
- ✅ **대시보드** — `/mypage/*`·`/ops`(관리자), `/page/*`(공개 포털)

---

## 🏛️ 아키텍처 개요

### 헥사고날 아키텍처

```
📁 src/
├── 🔌 adapters/           # 외부 시스템 연동(순수 I/O)
│   ├── database/          # connection.py, models/, repositories/(BaseRepository + Mixin)
│   ├── external/          # kis_api/, websocket/, telegram/, naver/, dart_api/, krx/, kofia_client.py
│   └── cache/             # redis_client.py
├── 🏢 application/
│   ├── common/            # dto.py, dependencies.py, decorators.py(@transaction 등), exceptions.py, ...
│   ├── domain/            # access_log, account, admin_auth, auth, backtest, market_data, ohlcv,
│   │                      # order, paper_trade, recommendation, risk, screener, strategy
│   └── interface/         # api/(REST·WS), page/(Jinja2), admin_session_gate.py
└── ⚙️  settings/           # config.py, sell_score_settings.py, logging_config.py, exception_handlers.py

📁 templates/              # Jinja2 템플릿 (대시보드)
📁 static/                 # 정적 파일 (CSS/JS)
```

> WebSocket은 별도 도메인이 아니라 `adapters/external/websocket/` + `interface/api/websocket_router.py`로 구성됩니다.

### 핵심 아키텍처 패턴
- **BaseRepository Pattern**: `BaseRepository[Model]` + `SearchableMixin`/`PaginationMixin`/`StatsMixin`
- **Facade Service**: `StrategyService`는 CRUD/분석 이력 facade, 유니버스·추천·현금계획은 협력 서비스에 위임
- **@transaction 데코레이터**: 외부 호출 public 메서드에만 적용(세션 생성·commit/rollback)
- **KIS API Client 분리**: `KISAuth`(토큰) / `KISAPIClient`(REST·레이트리밋) / `KISWebSocket`
- **스케줄러 기반 처리**: APScheduler(KST, coalesce, 기본 misfire 300초)로 전략·알림·OHLCV 작업 실행
- **Async/Await**: 모든 I/O 비동기

---

## 🎯 도메인별 구현 가이드

### 1. Auth / AdminAuth Domain (인증)

#### 핵심 기능
- KIS 접근 토큰 발급/재사용(`AuthService` → `KISAuth`): 1일 1회 발급 원칙, 캐시 디렉터리의 `KIS{YYYYMMDD}` 파일 중 유효·최장 만료 토큰 재사용, 만료는 KST aware
- WebSocket 승인키 발급
- 관리자 로그인(`AdminAuthService`): scrypt 해시 검증(`common/password_hash.py`), Redis 세션(SHA-256 키, 절대 TTL 12h), IP별 5회 실패 시 잠금, 미설정·Redis 장애 시 fail-closed

#### API 엔드포인트
- `POST /api/v1/auth/token` — 토큰 발급
- `POST /api/v1/auth/token/refresh` — 토큰 갱신
- `GET /api/v1/auth/token/status` — 토큰 상태
- `POST /api/v1/auth/websocket/approval` — 승인키
- `GET /api/v1/auth/environment` — 거래 환경 조회(전환 API 없음, `TRADING_ENVIRONMENT`로 결정)
- `POST /api/v1/admin-auth/login` · `POST /logout` · `GET /me` — 관리자 세션

---

### 2. Order Domain (주문 처리)

#### 핵심 기능
- 현금 주문(`OrderService.create_order` → KIS `order-cash`, 실전 `TTTC0802U`/`TTTC0801U`), 가격 유형 `limit`/시장가/`closing`(장후 시간외 종가 `ORD_DVSN 06`)
- 주문 조회·목록, 취소, 정정, 체결 상태 갱신(`inquire-daily-ccld`)
- ⚠️ 이 경로는 전략 kill-switch(`STRATEGY_LIVE_TRADING_ENABLED`)를 거치지 않는다 — 보호는 로그인 세션(`require_admin_session`) + `AdminAccessDep`

#### API 엔드포인트
- `POST /api/v1/orders` — 주문 생성
- `GET /api/v1/orders` — 주문 목록
- `GET /api/v1/orders/{order_id}` — 주문 조회
- `PATCH /api/v1/orders/{order_id}` — 주문 정정
- `POST /api/v1/orders/{order_id}/cancel` — 주문 취소
- `POST /api/v1/orders/{order_id}/refresh-status` — 체결 상태 갱신

---

### 3. Account Domain (계좌 관리)

#### 핵심 기능
- 잔고: 합계는 주식잔고조회(TTTC8434R) `output2`, 주문가능현금은 매수가능조회(TTTC8908R) `ord_psbl_cash`(`available_amount`)
- 보유 포지션 조회, Redis 캐시(`cache_ttl_account` 30초, 엔진은 `use_cache=False`)

#### API 엔드포인트
- `GET /api/v1/accounts/balance` — 잔고 조회
- `GET /api/v1/accounts/positions` — 포지션 조회

---

### 4. MarketData / OHLCV Domain (시세)

#### 핵심 기능
- 현재가·호가·차트(`MarketDataService`, Redis TTL: 시세 5초, 호가 스냅샷 15초, 일봉 86400초, 분봉 900초)
- 일봉 DB 캐시(`OHLCVRepository`, 로더 `OHLCVDataLoader`): KIS 1콜 100행 제한으로 청크 조회, 15:31 KST 전 당일 일봉은 저장하지 않음, 보존 3650일
- OHLCV 스케줄러: 정리 02:00, 워밍업 08:00, 증분 16:00(월~금)

#### API 엔드포인트
- `GET /api/v1/market/price/{symbol}` — 현재가 조회
- `GET /api/v1/market/orderbook/{symbol}` — 호가 조회
- `GET /api/v1/market/chart/{symbol}` — 차트 데이터

---

### 5. Strategy Domain (전략)

#### 핵심 기능
- **실행 엔진**(`GoldenCrossEngine.execute`): kill-switch → 직전 주문 대사 → MA drift 경고(55/165 단일 기준) → 벤치 당일 수익률(급락 가드 −2%) → 시장 국면 게이트(ADX14≥20, 실주문 fail-closed, 신규 매수만 차단) → 후보(ETF 모드: 활성 거래가능 ETF 전체, 보유 종목 먼저·종목코드 순) → FSM 전이 → 최대 보유 5 / `SafetyGuard`(일 신규 진입 3) → 주문 접수(`PENDING`+`order_no`)
- **체결 대사**(`reconcile_open_orders`, 16:10 job 및 다음 실행 시작 시): `EXECUTED`(실제 체결가·수량, 매도는 비용 반영 실현손익, ETF 매도세 면제) 또는 `CANCELLED`(매수 → WAITING, 매도 → 브로커 잔고 기준 IN_POSITION)
- **매수 스캔/추천**(`BuyStrategyService`, `RecommendationService`), **매도 분석**(`SellStrategyService` + `sell_score_rules.py`), **유니버스 갱신**(`UniverseService`), **현금화 계획**(`PortfolioCashPlanner`), **알림**(`NotificationScheduler`)
- **스케줄러**(`StrategyScheduler`, 월~금): 08:00 유니버스, 15:35 전략 실행(`status=active`만, misfire 90초), 16:10 대사

#### API 엔드포인트 (관리자, `/api/v1/strategies`)
- `GET /api/v1/strategies` · `GET /{strategy_id}` — 전략 목록/조회
- `POST /{strategy_id}/start|pause|stop`, `PATCH /{strategy_id}/config` — 상태/설정 변경
- `POST /{strategy_id}/execute` — 전략 실행(기본 dry-run)
- `GET /{strategy_id}/signals`, `/symbol-states`, `/signals/statistics`
- `GET /scheduler/status`, `/universe*`, `/sell-signal/{symbol}`, `/analysis-history*`, `/portfolio-cash-plan`, `/presets`
- 생성/삭제·알림 수동 실행·캐시 백필은 `ENABLE_ADMIN_STRATEGY_ROUTES=true`일 때만 마운트

---

### 6. 기타 도메인

| 도메인 | 서비스 | 경로 |
|--------|--------|------|
| risk | `SafetyGuard` — 실효 가드는 시장 급락·일 신규 진입 3건, 손실/연속손실·자체 포지션 한도는 사실상 비활성 | (엔진 내부) |
| backtest | `BacktestService`, `BacktestEngine`, `PortfolioParityEngine`, walk-forward | `/api/v1/backtest/*` (raw DTO 응답) |
| recommendation | `RecommendationScanService`, `RecommendationRuleSetService`, `RecommendationRuleSetValidationService` | `/api/v1/recommendations/*` |
| screener | `ValueScreenerService`(Naver) | `/api/v1/screener/*` |
| access_log | `AccessLogService`(`@transaction`) | `/api/v1/access-logs*` |
| 공개 포털 | `PublicStrategyService`(쿨다운·전역 락·고정 한도) | `/api/v1/public/strategies/*`, `/page/*` |
| ops | 운영 요약/알림 스케줄러 상태 | `/api/v1/ops/summary`, `/api/v1/ops/notification-scheduler-status`, `/ops` |
| WebSocket | `KISWebSocket` + `websocket_manager` | `WS /ws/realtime`, `GET /ws/info` |

---

## 🛠️ 개발 환경

### 환경 설정
```bash
uv sync                                   # 의존성 설치
uvicorn src.main:app --reload             # 개발 서버
alembic upgrade head                      # DB 마이그레이션
# 전체 테스트(호스트에 uv 없음): 루트 CLAUDE.md의 docker run ... pytest 명령 사용
black src/ tests/ && isort src/ tests/ && mypy src/
```

### 환경 변수 (.env)
- 계약의 SSoT는 `src/settings/config.py` + `.env.example`이며, 새 키는 두 곳에 함께 추가합니다(실제 값은 커밋 금지).
- 주요 그룹: DB/Redis(`DATABASE_URL`, `REDIS_URL`, `REDIS_PASSWORD`), KIS 실전/모의(`KIS_*`, `KIS_PAPER_*`, `TRADING_ENVIRONMENT`), 접근 제어(`ADMIN_ALLOWED_IPS`, `TRUSTED_PROXY_IPS`, `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`, `ADMIN_SESSION_COOKIE_SECURE`), 전략(`STRATEGY_LIVE_TRADING_ENABLED`, `STRATEGY_ORDER_PRICE_TYPE`, `GC_*`, `ETF_UNIVERSE_ENABLED`), 알림(`TELEGRAM_*`, `BUY_/SELL_NOTIFICATION_ENABLED`), OHLCV(`OHLCV_RETENTION_DAYS`)
- 상세는 `src/settings/CLAUDE.md`

---

## 🔧 핵심 구현 규칙

### 1. Service Layer 규칙

**✅ DO:**
- Service가 정책(캐시 TTL, 리스크 한도, 스캔 필터, 재시도 예산)을 결정
- 여러 Repository/Client를 조합하고, 세션 경계는 DI(`DatabaseSession`) 또는 `@transaction`으로 관리
- 외부 API 호출은 adapters를 통해서만

**❌ DON'T:**
- domain에서 FastAPI `Request`/`Response`/`APIRouter` 사용 금지
- 스캔·연구·알림 경로에서 실주문 부수효과 금지
- 복잡한 비즈니스 로직을 Router에 작성 금지

### 2. Repository Layer 규칙
- `<entity>_repository.py` / `<Entity>Repository`, `BaseRepository[Model]` 상속 + 필요한 Mixin 조합
- 저장 형태만 다루고 DTO 변환·정책 계산은 domain에서 수행
- 스키마 변경은 Alembic revision과 짝지어 커밋

### 3. Router Layer 규칙
- 입력 파싱 → 서비스 호출 → `ResponseDTO.success_response(...)` 반환(예외: `backtest_router`는 raw DTO)
- DI는 `application.common.dependencies`의 Annotated 별칭 우선, 클라이언트 IP는 `get_client_ip()`만 사용
- 관리자 라우트는 전역 로그인 게이트로 자동 보호되며, 공개 라우트는 `admin_session_gate.py` 화이트리스트에 명시

### 4. DTO 규칙
- 공통 응답 계약은 `common/dto.py`(`BaseDTO`, `ResponseDTO[T]`, `PaginatedResponseDTO[T]` 등)
- 도메인 DTO는 `domain/<domain>/dto.py`. `strategy/dto.py`는 라우터·템플릿·스크립트가 필드명에 의존하는 교차 계약이므로 변경 시 소비처 확인

### 5. 에러 처리 규칙
- 외부/인프라 예외는 `common/exceptions.py`의 `ApplicationError` 계열(`KISAPIServiceError`, `OrderError`, `RateLimitExceededError` 등)로 변환
- HTTP 변환은 `settings/exception_handlers.py`의 전역 핸들러(`application_error_handler`, `http_exception_handler`, `validation_error_handler`, `generic_exception_handler`)가 담당 — 라우터에서 개별 `HTTPException` 변환을 반복하지 않음

---

## 📊 성능 최적화 전략

### 1. 캐싱 전략 (설정 기본값)
- **시세 데이터**: Redis 5초 TTL / **호가 스냅샷** 15초
- **계좌 정보**: Redis 30초 TTL
- **일봉/분봉**: 86400초 / 900초, 일봉은 DB(`OHLCVRepository`) 캐시가 1차 저장소

### 2. Connection Pooling
- **HTTP**: httpx `AsyncClient` 재사용(`KISAuth`/`KISAPIClient`, 종료 시 `aclose`)
- **Database**: SQLAlchemy async pool(`pool_size=10`, `max_overflow=20`, `pool_pre_ping`)
- **Redis**: `redis_max_connections` 50

### 3. 비동기/동시성
- 스캔 동시 처리 `SCAN_CONCURRENCY_LIMIT`(기본 5), 공개 스캔 동시성 2 + IP 쿨다운 + 전역 락
- KIS 레이트리밋: 운영 `KIS_API_RATE_LIMIT=8`/s(설정 기본 10), EGW00201 지수 백오프

---

## 🔒 보안 및 리스크 관리

### 보안 규칙
- API 키·계좌·토큰은 `.env`/토큰 캐시 볼륨에만, 로그에 자격증명 금지(`httpx` 등 로거 WARNING 고정)
- 전역 로그인 게이트 + IP allowlist(현재 운영 전 대역) + 쓰기 메서드 CSRF 헤더
- 프록시 헤더는 `TRUSTED_PROXY_IPS`에서 온 연결만 신뢰
- Swagger/ReDoc/OpenAPI 비활성

### 리스크 관리
- 전략 실주문 kill-switch `STRATEGY_LIVE_TRADING_ENABLED`(기본 false) — 서버 전체 차단기는 아님(`POST /api/v1/orders` 별도)
- 시장 국면 게이트, 시장 급락 가드(−2%), 일 신규 진입 3건, 최대 보유 5(전략 config)
- 중복 주문 가드(`order_no` 존재 시 `CANCELLED` 외 재주문 금지)
- 리스크 한도의 단일 출처는 `domain/risk/dto.py`(SafetyGuard)와 전략 config(`max_position_count`)다. 미사용이던 `risk_*` 설정 7종은 2026-11-07 제거

---

## 📚 테스트 전략

- 위치: `tests/domain/`(서비스·엔진·스케줄러), `tests/interface/`(라우터·보안 경계), `tests/adapters/`(클라이언트), `tests/application/`(common 유틸), 최상위 `test_*.py`(백테스트 등)
- 공유 `conftest.py` 없음 — 모듈 로컬 픽스처, fake client/repository, monkeypatch 사용
- 실주문·실계좌·실 Telegram 발송 금지
- 현재 확인값: `963 passed, 13 skipped`(2026-11-07, `--no-cov`). 상세는 `tests/AGENTS.md`

---

## 🎯 다음 개발 단계

- `/ops` summary 경량화 및 부분 실패 tolerant aggregation
- `ADMIN_ALLOWED_IPS` 범위 재조정
- access log 범위를 `/api`, `/mypage`까지 확장
- `scripts/` CLI 진입점에 `setup_logging()` 배선
- notification scheduler 결과 이력 영속화
- 전략: 연구 결론 NO-GO(`reports/research_2026-11-06_summary.md`) — 새 가설은 사전등록(`docs/plans/`) 후 검증

---

## 📞 참고 문서

- [FastAPI 공식 문서](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0 Async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [한국투자증권 Open API](https://apiportal.koreainvestment.com/)
- [UV Package Manager](https://docs.astral.sh/uv/)

---

**💡 중요**: 이 서비스는 **금융 자동매매**를 다루므로 **안정성과 정확성**이 최우선입니다. 실주문 경로를 여는 변경(kill-switch, 전략 `status`, 주문 API)은 테스트·소액 검증·명시적 승인 후에만 적용합니다.
