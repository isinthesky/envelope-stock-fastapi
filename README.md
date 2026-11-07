# KIS Strategy & Alert Server

한국투자증권 Open API 기반의 **전략 실행 + 알림 운영 서버**입니다.
이 저장소는 단순 예제 API가 아니라, 실제 운영 관점에서 아래 흐름을 다룹니다.

- KIS 토큰/인증 관리
- 계좌/포지션/주문 조회
- 골든크로스 기반 매수 후보 스캔
- 매도 추적 이력/사전 현금화 계획
- 전략 스케줄러(08:00 유니버스 갱신, 15:35 전략 실행, 16:10 주문 체결 대사)
- 알림 스케줄러(매수 11:30/14:30, 매도 09:30/12:30 Telegram 알림 — `BUY_/SELL_NOTIFICATION_ENABLED`로 on/off, 현재 운영 env는 둘 다 OFF)
- `/ops` 운영 대시보드와 `/api/v1/ops/*` 운영 요약 API

## 핵심 운영 포인트

- **접속 주소**: `https://stock.lgetech.co.kr` (nginx-proxy 경유, Let's Encrypt). api 포트는 `127.0.0.1:10131` 전용이라 `http://<IP>:10131` 직접 접근은 불가합니다(2026-11-06 제거).
- **로그인**: `/page/*` 공개 포털·`/api/v1/public/*`·`/static`·`/health`를 제외한 모든 화면/API(`/mypage/*`, `/ops`, `/api/v1/*`, `/ws`)는 `/mypage/login/`에서 관리자 로그인해야 열립니다(`AdminSessionGateMiddleware`).

- FastAPI 기본 Swagger/ReDoc/OpenAPI는 모든 환경에서 의도적으로 비활성화되어 있습니다.
  - API 문서는 운영 인증으로 우회 노출하지 않습니다. 재노출은 별도 보안 검토와 정책 변경을 거쳐야 합니다.
  - `docs_url=None`
  - `redoc_url=None`
  - `openapi_url=None`
- `/api/v1/ops/*` 와 `/ops` 는 전역 로그인 게이트에 더해 **IP allowlist(`AdminAccessDep`/`verify_admin_access`)** 를 거칩니다. 현재 `ADMIN_ALLOWED_IPS`는 전 대역이라 실질 방어선은 로그인 세션입니다.
- `main.py` 기준 `/mypage/*`는 include-level 관리자 보호를 사용하고, `/page/*` 공개 페이지는 별도로 열어둡니다.
- 접근 로그는 현재 전체 API가 아니라 **`/page` 공개 경로 중심**으로 수집됩니다.
- 전략 스케줄러와 알림 스케줄러는 별개입니다.
  - 전략 스케줄러 status: `/api/v1/strategies/scheduler/status`
  - 알림 스케줄러 status: `/api/v1/ops/notification-scheduler-status`

## 디렉터리 개요

```text
kis-strategy-alert-server/
├── src/
│   ├── application/
│   │   ├── interface/api/          # API 라우터
│   │   ├── interface/page/         # HTML 페이지 라우터
│   │   ├── domain/strategy/        # 전략/스케줄러/알림 로직
│   │   └── common/                 # 공통 DTO, 의존성, 예외
│   ├── adapters/                   # DB, Redis, KIS, Telegram 연동
│   └── settings/                   # 설정, 예외 처리, 로깅
├── templates/                      # HTML 템플릿
├── static/                         # 페이지 JS/CSS
├── docs/base/                      # 아키텍처/서비스/컨벤션 SSoT
├── docs/ops/                       # 운영 backlog / README 개편안 / ops 설계 / 운영 루틴
├── scripts/                        # common/ · research/(오프라인 연구) · ops/(백필·시딩·관리자 해시)
├── reports/                        # 연구·walk-forward 리포트(api 컨테이너에 마운트)
├── tests/                          # pytest 테스트
├── docker-compose.yml
└── README.md
```

## 주요 엔드포인트

### 헬스/운영
- `GET /health`
- `GET /ops`
- `GET /api/v1/ops/summary`
- `GET /api/v1/ops/notification-scheduler-status`

### 인증/환경
- `POST /api/v1/admin-auth/login` · `POST /api/v1/admin-auth/logout` · `GET /api/v1/admin-auth/me` (관리자 로그인 세션)
- `POST /api/v1/auth/token`
- `POST /api/v1/auth/token/refresh`
- `GET /api/v1/auth/token/status`
- `POST /api/v1/auth/websocket/approval`
- `GET /api/v1/auth/environment`

### 계좌/주문
- `GET /api/v1/accounts/balance`
- `GET /api/v1/accounts/positions`
- `GET /api/v1/orders`
- ⚠️ `POST /api/v1/orders` — **수동 실주문 API**입니다. `TRADING_ENVIRONMENT=prod`에서는 KIS 실전 주문(`TTTC0802U`/`TTTC0801U`)이 나갑니다.
  `STRATEGY_LIVE_TRADING_ENABLED` kill-switch를 **거치지 않으며**, 보호 장치는 `ADMIN_ALLOWED_IPS` IP allowlist와
  쓰기 요청용 `X-Requested-With: XMLHttpRequest` 헤더 검사(`verify_admin_access`), 그리고 **관리자 로그인 세션**입니다.
  `/api/v1/orders/*`와 `/mypage/order`는 `/mypage/login/`에서 로그인해야 열립니다(`ADMIN_USERNAME`/`ADMIN_PASSWORD_HASH`, 미설정 시 전부 거부).
  비밀번호 해시 생성/교체: `python3 scripts/ops/hash_admin_password.py` → `.env` 반영 → `docker compose up -d --build`.

### 전략/분석
- `GET /api/v1/strategies`
- `GET /api/v1/strategies/scheduler/status`
- `GET /api/v1/strategies/portfolio-cash-plan`
- `GET /api/v1/strategies/universe/golden-cross-recommendations`
- `GET /api/v1/strategies/analysis-history`
- `POST /api/v1/strategies/{id}/execute` (`dry_run=false`도 `STRATEGY_LIVE_TRADING_ENABLED` kill-switch가 막음)

### 페이지
- 공개 페이지: `/page/*`
- 관리자 성격 페이지: `/mypage/*`
- 운영 허브: `/ops`

## 빠른 시작

### 1) 환경 파일 준비

```bash
cd /Users/m2-dev/Apps/kis-strategy-alert-server
cp .env.example .env
```

필수 항목 예시:

```env
APP_NAME="KIS Strategy & Alert Server"
POSTGRES_PASSWORD=change-me
REDIS_PASSWORD=change-me   # 필수. 비우면 redis 컨테이너가 기동을 거부합니다
DB_BIND_HOST=127.0.0.1     # DB/Redis 호스트 포트는 로컬 전용 바인딩
API_PORT=10131
KIS_APP_KEY=...
KIS_APP_SECRET=...
KIS_ACCOUNT_NO=12345678
KIS_HTS_ID=...
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

> 현재 로컬 `.env` 예시에서는 `API_PORT=10131` 로 오버라이드될 수 있습니다. 실제 노출 포트는 `.env` 값을 기준으로 확인하세요.

### 2) Docker Compose 기동

```bash
/opt/homebrew/bin/docker compose up -d --build
```

> 토큰은 `kis_token_cache` named volume에 보존되므로 재빌드는 안전합니다.
> 마운트 경로는 컨테이너 실행 사용자의 `HOME`이 결정합니다 — 하드닝 배포(2026-09-08) 이후 현재 배포본은 비루트 `uid 10001` 기준
> `/home/appuser/KIS/config`이며, 아래 「컨테이너 하드닝 적용 절차」의 롤백을 하면 root 기준 `/root/KIS/config`로 돌아갑니다.
> 볼륨 이름은 그대로이므로 토큰 파일은 어느 방향으로도 이동/복사되지 않습니다.

검증:

```bash
/opt/homebrew/bin/docker compose ps
curl -fsS http://localhost:${API_PORT:-10131}/health
```

### 3) 컨테이너 하드닝 적용 절차 (2026-09-08 **적용 완료**)

`Dockerfile`(비루트 `uid 10001`), `docker-compose.yml`(Redis 비밀번호 필수화, DB/Redis 로컬 전용 바인딩,
토큰 볼륨 경로 변경), `.dockerignore`가 **2026-09-08에 배포 완료**됐습니다.
아래 절차는 재적용·재현·롤백용으로 보존합니다.

적용 시 실측 결과:

| 항목 | 결과 |
|---|---|
| api 실행 사용자 | `uid=10001(appuser)`, `HOME=/home/appuser` |
| redis 실행 사용자 | `uid=999(redis)` (공식 entrypoint의 `gosu` 강등 보존) |
| 토큰 캐시 | 파일 35개 mtime·해시 **전부 불변** — 재발급 없음(2회차 재기동으로 확정) |
| `/health` | `database/redis: connected`, `kis_api: authenticated` |
| Redis 인증 | 비밀번호 없이 `NOAUTH Authentication required` |
| 포트 | postgres/redis `127.0.0.1` 전용, api `0.0.0.0`(당시) → 2026-11-06부터 api도 `127.0.0.1:10131` 전용(`API_BIND_HOST`, 외부는 nginx-proxy HTTPS) |

⚠️ KIS 토큰은 **1일 1회 발급 원칙**입니다. 아래 절차는 장 마감 후 또는 주말에 1회만 수행하고,
`force_refresh=True`를 임의로 추가하지 않습니다. 재기동 1회차에는 프로세스 시작 시각 기준 토큰 파일이
새로 생길 수 있으므로, "재발급 없음"은 **2회차** `docker compose restart api` 후 토큰 파일 목록/mtime이
변하지 않는 것으로 판정합니다.

```bash
# ① .env 에 필수 키 설정 (URL 예약문자 @ : / % 금지)
#    REDIS_PASSWORD=$(openssl rand -hex 24)
#    DB_BIND_HOST=127.0.0.1

# ② api 정지
docker compose stop api

# ③ 토큰 볼륨 소유권을 새 실행 uid 로 변경 (파일 복사 없음)
docker run --rm -v kis-strategy-alert-server_kis_token_cache:/data alpine \
  sh -c 'chown -R 10001:10001 /data && chmod 700 /data'

# ④ 재빌드 + 기동
docker compose up -d --build

# ⑤ 실행 사용자 확인
docker exec kis-strategy-alert-server id            # uid=10001 이어야 함
docker exec kis-strategy-alert-server sh -c 'echo $HOME'   # /home/appuser 이어야 함

# ⑥ 토큰 캐시 쓰기 가능 검증 — WRITABLE 이 나오지 않으면 즉시 롤백
docker exec kis-strategy-alert-server sh -c \
  'touch /home/appuser/KIS/config/.wtest && rm /home/appuser/KIS/config/.wtest && echo WRITABLE'
```

롤백(⑥ 실패 시):

⚠️ **`git checkout -- <path>` 는 쓰지 마세요.** 그 명령은 index(= 커밋된 내용)로 되돌리므로,
하드닝이 커밋된 뒤에는 하드닝 버전을 그대로 복원하는 **무동작**이 됩니다(에러도 나지 않습니다).
그 상태에서 아래 `chown 0:0` 만 적용되면 컨테이너는 `uid 10001` 인데 토큰 캐시는 `root:root 0700` 이 되어
**토큰 파일을 읽지도 쓰지도 못합니다.** 이때 `auth.py` 는 토큰 파일 읽기 실패를
"토큰 없음"으로 삼키고(`_parse_cache_file()` 의 `except Exception: return None`) 조용히 **새 토큰을 발급**하므로 1일 1회 발급 원칙이 깨집니다
(디렉터리 자체를 못 읽으면 `_load_token_from_file()` 의 `iterdir()` 가 `PermissionError` 로 실패해 토큰 확보가 아예 실패합니다).

하드닝 직전 커밋은 `f12f240`(`Dockerfile`/`docker-compose.yml` 를 마지막으로 변경한 커밋)입니다.
커밋 전/후 모두에서 동작하도록 SHA 를 명시해 되돌립니다.

```bash
# R1 하드닝 직전 버전으로 명시적 복원 (커밋 여부와 무관하게 동작)
git checkout f12f240 -- docker-compose.yml Dockerfile
rm -f .dockerignore

# R2 복원 결과 확인 — 아래 두 결과가 모두 맞아야 chown 0:0 이 안전하다
grep -n 'kis_token_cache:/root/KIS/config' docker-compose.yml   # 토큰 마운트가 root HOME 기준인지
grep -n 'USER ' Dockerfile                                       # 출력이 없어야 함(= root 실행)

# R3 R2 가 확인된 경우에만 볼륨 소유권을 root 로 되돌린다
docker run --rm -v kis-strategy-alert-server_kis_token_cache:/data alpine chown -R 0:0 /data

# R4 재빌드 + 실행 사용자 재확인
docker compose up -d --build
docker exec kis-strategy-alert-server id            # uid=0(root) 이어야 함
docker exec kis-strategy-alert-server sh -c 'ls -la /root/KIS/config'
```

> R2 가 기대와 다르면(= 여전히 하드닝 버전이면) **`chown 0:0` 을 실행하지 마세요.** 그 경우 올바른 소유권은
> `10001:10001` 이며, 이미 `0:0` 으로 바꿨다면 `chown -R 10001:10001` 로 되돌린 뒤
> 토큰 파일 목록/mtime 이 변하지 않았는지 확인합니다.

- Redis 비밀번호가 비어 있어도 `docker compose ps/logs/down/config`는 정상 동작합니다(파싱 시점이 아니라
  **런타임 가드**로 막습니다). 비어 있으면 redis 컨테이너만 `FATAL: REDIS_PASSWORD ...` 로그를 남기고 종료합니다.
- 적용 후에는 컨테이너 안에서 `uv run ...`이 `/app/.venv` 쓰기 실패로 동작하지 않습니다.
  **`/app/.venv/bin/<cmd>` 를 직접 실행하세요**(예: `docker compose exec api /app/.venv/bin/python scripts/...`).
  `PYTHONPATH=/app` 은 이미 이미지 ENV 에 있으므로 추가 설정이 필요 없습니다.
- ⚠️ **`docker compose exec --user root api ...` 는 기본 수단으로 쓰지 않습니다.** `--user` 는 `HOME` 을 재설정하지 않아
  `Dockerfile` 의 `ENV HOME=/home/appuser` 를 그대로 상속합니다. 그 상태에서 KIS 인증을 타는 명령을 돌리면
  `auth.py` 의 `Path.home()/"KIS"/"config"` 아래에 **root 소유 0600 토큰 파일**이 마운트된 `kis_token_cache` 볼륨에 남고,
  이후 `uid 10001` 프로세스가 그 파일을 읽지 못해 토큰을 조용히 재발급합니다(1일 1회 원칙 위반).
  부득이하게 root 가 필요하면 KIS 인증을 타지 않는 명령으로 한정하고, `-e HOME=/tmp` 를 함께 지정한 뒤
  작업 후 소유권을 되돌립니다.

  ```bash
  docker compose exec --user root -e HOME=/tmp api <cmd>
  docker run --rm -v kis-strategy-alert-server_kis_token_cache:/data alpine \
    sh -c 'chown -R 10001:10001 /data && ls -la /data'
  ```

## 운영 확인 순서

### 1. 기본 생존 확인

```bash
curl -fsS http://localhost:${API_PORT:-10131}/health
# /health 외 API는 로그인 세션 필요: 로그인 응답 쿠키(kis_admin_session)를 저장해 -b 로 전달
curl -fsS -b cookies.txt http://localhost:${API_PORT:-10131}/api/v1/ops/summary
```

`/health`는 DB(`SELECT 1`)·Redis(`ping`)·KIS 토큰 유효성만 보는 연결 수준 점검입니다.
DB/Redis가 끊기면 `status`가 `degraded`로 내려가지만 HTTP 상태는 항상 200이므로, `curl -fsS`의 성공 여부가 아니라
응답 본문의 `status` 값을 확인해야 합니다(KIS 토큰 실패는 `kis_api` 필드에만 반영되고 `status`는 바꾸지 않습니다).
WebSocket/전략 스케줄/알림 스케줄의 세부 상태는 `/api/v1/ops/summary` 또는 각 status API로 확인하세요.

### 2. 전략 스케줄러 확인

```bash
curl -fsS -b cookies.txt http://localhost:${API_PORT:-10131}/api/v1/strategies/scheduler/status
```

현재 코드 기준 전략 스케줄러(월~금)는 다음 세 작업을 다룹니다.

- `08:00` 유니버스 갱신(`daily_universe_refresh`)
- `15:35` 일일 전략 실행(`daily_strategy_execution`, misfire 90초)
- `16:10` 주문 체결 대사(`daily_order_reconcile`, `STRATEGY_RECONCILE_HOUR/MINUTE`) — 장후 시간외 종가 주문의 `PENDING` 시그널을 `EXECUTED`/`CANCELLED`로 확정

OHLCV 캐시 스케줄러는 별도로 `02:00` 정리·`08:00` 워밍업(매일), `16:00` 증분 업데이트(월~금)를 돈다.

### 3. 알림 스케줄러 확인

```bash
curl -fsS -b cookies.txt http://localhost:${API_PORT:-10131}/api/v1/ops/notification-scheduler-status
```

알림 슬롯(설정 기본값):

- 매도 알림: `09:30`, `12:30` (`SELL_NOTIFICATION_ENABLED`, 기본 false)
- 매수 알림: `11:30`, `14:30` (`BUY_NOTIFICATION_ENABLED`, 기본 true)
- 각 알림 10분 전 데이터 갱신 수행
- 플래그가 꺼진 종류는 job 자체를 등록하지 않는다. 현재 운영 env는 매수·매도 모두 OFF다.

### 4. 운영 허브 페이지 확인

브라우저에서 아래 주소를 열면(미로그인 시 `/mypage/login/`으로 이동) 운영 요약 대시보드를 볼 수 있습니다.

```text
https://stock.lgetech.co.kr/ops
```

> 세션 쿠키가 `Secure`(`ADMIN_SESSION_COOKIE_SECURE=true`)라 `http://localhost:10131`에서는 브라우저 로그인이 유지되지 않을 수 있습니다.

표시 항목:
- service / env / 거래환경
- KIS token 상태
- 전략/알림 스케줄러 상태
- 계좌 잔고 / 포지션 / 미체결 주문
- 매수 추천 요약
- 매도 추적 종목 요약
- 현금화 계획 / 운영 alert

## 운영 문서

`docs/ops/` 아래에 운영 중심 문서를 정리했습니다.

- `01-priority-backlog.md` — 운영 개선 우선순위 backlog
- `02-readme-revamp-draft.md` — README 개편 초안 원본
- `03-ops-dashboard-proposal.md` — `/ops` 설계안
- `04-api-operations-routine.md` — 하루 운영 루틴 기준 API 시나리오
- `05-public-scan-etf-mode-transition.md` — `ETF_UNIVERSE_ENABLED` 전환이 `/page` 공개 스캔에 미치는 영향

## 테스트

⚠️ 호스트에는 `uv`가 없고 API 이미지에는 `tests/`가 없으므로, 저장소를 bind mount한 아래 명령만 사용합니다.

```bash
docker run --rm -v /Users/m2-dev/Apps/kis-strategy-alert-server:/work -w /work -e PYTHONPATH=/work -e UV_PROJECT_ENVIRONMENT=/tmp/kis-test-venv kis-strategy-alert-server-api uv run pytest tests/ -q
```

현재 확인값: `963 passed, 13 skipped` (2026-11-07 실측, `--no-cov`; 이전 `790 passed, 13 skipped` 2026-09-08).

> 이 이미지는 비루트(`uid 10001`)로 실행되지만 위 명령은 **`--user root` 없이 그대로 동작합니다**
> (2026-09-08 실측: 794 passed). `UV_PROJECT_ENVIRONMENT=/tmp/kis-test-venv`가 venv를 쓰기 가능한
> `/tmp` 아래로 돌리므로 `uv run`이 `/app/.venv` 쓰기를 시도하지 않기 때문입니다.
> 이 환경변수를 빼면 비루트에서 실패합니다.

## 알려진 함정

- ⚠️ 월~금 `15:35` 활성 `golden_cross` 전략 실행은 `STRATEGY_LIVE_TRADING_ENABLED=true`일 때만 실주문한다. 기본값은 `false`이며 운영 검증과 명시적 승인 뒤에만 켠다.
- ⚠️ **`STRATEGY_LIVE_TRADING_ENABLED`는 서버 전체의 주문 차단기가 아니다.** 강제 지점은 `GoldenCrossEngine.execute`(`domain/strategy/golden_cross_engine.py`) 첫 분기 **한 곳**뿐이므로, 이 스위치가 막는 것은 전략 자동 실행(15:35 스케줄러)과 `POST /api/v1/strategies/{id}/execute` 경로다. `POST /api/v1/orders`(`order_router` → `OrderService.create_order`)는 이 검사를 전혀 거치지 않는 **별개의 실주문 경로**이며, 관리자 IP allowlist와 로그인 세션을 통과한 요청은 스위치가 OFF여도 KIS 실전 주문을 낼 수 있다. 즉 실질 방어선은 `ADMIN_ALLOWED_IPS` 범위 + 관리자 로그인 세션(`require_admin_session`)이다.
- ⚠️ 전략 현황(2026-11-07): 골든크로스 전략은 `status=paused`, 연구 결론 **NO-GO**(`reports/research_2026-11-06_summary.md`; state overlay CONDITIONAL, 2x 레버리지 NO-GO는 `docs/plans/*-result.md`). 재개하면 실주문은 장후 시간외 종가(`STRATEGY_ORDER_PRICE_TYPE=closing`, KIS `ORD_DVSN 06`)로 접수되고 16:10 대사로 확정된다. 시장 국면 게이트(`GC_REGIME_FILTER_ENABLED=true`, ADX14≥20, 벤치 069500)는 실주문에서 fail-closed로 신규 매수만 막는다. MA는 55/165 단일 기준(불일치 시 엔진이 `MA drift` 에러 로그).
- ⚠️ `analysis_history`의 종목코드 칸에는 `MEMO-BROADCAST-1` 같은 메모 행을 넣지 않는다. 파이프라인이 `^[0-9A-Z]{6}$`로 자동 필터하지만, 종목코드 칸은 종목코드 전용이다.
- ⚠️ 실운영 `KIS_API_RATE_LIMIT=8`은 KIS 실전 한도 `20/s`의 40%로 설정한 보수값이다. `EGW00201`은 `0.5 → 1.0 → 2.0`초 지수 백오프로 최대 3회 재시도한다.
- ⚠️ 알림은 플래그가 켜진 슬롯만(매수 `11:20→11:30`/`14:20→14:30`, 매도 `09:20→09:30`/`12:20→12:30`) 데이터 갱신 뒤 전송한다(현재 운영 env는 매수·매도 모두 OFF). 20분 내 성공 갱신이 없으면 조용히 skip하고, 동일 시그니처는 6시간 동안 중복 차단한다.
- ⚠️ 매도 판단 엔진은 3벌(E1 실주문 / E2 화면·API·텔레그램 분석 / E3 백테스트)이고 규칙이 서로 다르다. 각 화면 상단의 엔진 배지로 출처를 확인한다. 상세는 `docs/sell-strategy.md` §1, 화면↔엔진 매핑은 `docs/buy-sell-usage-guide.md` §2.
- ⚠️ 컨테이너 하드닝(비루트 `uid 10001` 실행 · Redis 비밀번호 필수 · DB/Redis `127.0.0.1` 전용 바인딩)은 2026-09-08에 **적용 완료**됐다. 컨테이너 안에서 `uv run`은 `/app/.venv` 쓰기 실패로 죽으므로 `/app/.venv/bin/<cmd>`를 직접 실행한다(단 위 호스트 테스트 명령은 `UV_PROJECT_ENVIRONMENT`가 `/tmp`를 가리켜 그대로 동작한다). 되돌리려면 「컨테이너 하드닝 적용 절차」의 롤백 순서를 지킨다.

## 알려진 한계

- 개별 page router를 테스트/별도 앱에서 직접 include하면 `main.py`와 동일한 관리자 guard를 별도로 붙여야 합니다.
- access log는 여전히 `/page` 경로만 기록합니다(`AccessLoggingMiddleware.LOG_PATHS`). `/api`, `/mypage`, `/health`는 대상이 아닙니다.
  - 다만 기록되는 클라이언트 IP는 2026-09-08에 신뢰 프록시 기반 공통 판정(`application/common/client_ip.py`)으로 통일되어, 관리자 IP 검증·공개 스캔 쿨다운·WebSocket 접근 제어와 같은 값을 씁니다.
- `/api/v1/ops/summary` 는 여러 서비스 호출을 집계하므로, 일부 외부 API 상태가 나쁘면 응답이 느려질 수 있습니다.
- 애플리케이션 로깅은 `src/settings/logging_config.py`의 `setup_logging()`이 `src/main.py` 최상단에서 적용합니다. `scripts/` CLI 진입점은 아직 이 부트스트랩을 호출하지 않아 백테스트/스캔/백필 실행 시 INFO 로그가 보이지 않습니다.
- 현재 운영 `ADMIN_ALLOWED_IPS`는 전 대역(`0.0.0.0/0`, `::/0`)이라 `/mypage/*`·`/api/v1/ops/*`·`/api/v1/access-logs`의 IP 보호는 무력하고, 방어선은 전역 로그인 게이트(관리자 계정 비밀번호 + IP별 5회 실패 시 최대 15분 잠금)뿐입니다.

## 다음 우선 개발 후보

- `/ops` summary 경량화 및 부분 실패 tolerant aggregation
- `ADMIN_ALLOWED_IPS` 범위 재조정(로그인 게이트와 이중 방어)
- access log 범위를 `/api`, `/mypage` 까지 확장
- `scripts/` CLI 진입점에 `setup_logging()` 배선
- notification scheduler 결과 이력 영속화
- README와 운영 문서의 지속 동기화
