# KIS Strategy & Alert Server

한국투자증권 Open API 기반의 **전략 실행 + 알림 운영 서버**입니다.
이 저장소는 단순 예제 API가 아니라, 실제 운영 관점에서 아래 흐름을 다룹니다.

- KIS 토큰/인증 관리
- 계좌/포지션/주문 조회
- 골든크로스 기반 매수 후보 스캔
- 매도 추적 이력/사전 현금화 계획
- 전략 스케줄러(08:00 유니버스 갱신, 15:35 전략 실행)
- 알림 스케줄러(09:30/11:30/12:30/14:30 Telegram 알림)
- `/ops` 운영 대시보드와 `/api/v1/ops/*` 운영 요약 API

## 핵심 운영 포인트

- FastAPI 기본 Swagger/ReDoc/OpenAPI는 비활성화되어 있습니다.
  - `docs_url=None`
  - `redoc_url=None`
  - `openapi_url=None`
- `/api/v1/ops/*` 와 `/ops` 는 **IP allowlist 기반 관리자 보호**를 사용합니다.
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
├── docs/ops/                       # 운영 backlog / README 개편안 / ops 설계 / 운영 루틴
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
- `POST /api/v1/auth/token`
- `POST /api/v1/auth/token/refresh`
- `GET /api/v1/auth/token-status`
- `GET /api/v1/auth/environment`

### 계좌/주문
- `GET /api/v1/accounts/balance`
- `GET /api/v1/accounts/positions`
- `GET /api/v1/orders`

### 전략/분석
- `GET /api/v1/strategies`
- `GET /api/v1/strategies/scheduler/status`
- `GET /api/v1/strategies/portfolio-cash-plan`
- `GET /api/v1/strategies/universe/golden-cross-recommendations`
- `GET /api/v1/strategies/analysis-history`

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

검증:

```bash
/opt/homebrew/bin/docker compose ps
curl -fsS http://localhost:${API_PORT:-10131}/health
```

## 운영 확인 순서

### 1. 기본 생존 확인

```bash
curl -fsS http://localhost:${API_PORT:-10131}/health
curl -fsS http://localhost:${API_PORT:-10131}/api/v1/ops/summary
```

`/health`는 최소 연결 상태 확인용입니다.
WebSocket/전략 스케줄/알림 스케줄의 세부 상태는 `/api/v1/ops/summary` 또는 각 status API로 확인하세요.

### 2. 전략 스케줄러 확인

```bash
curl -fsS http://localhost:${API_PORT:-10131}/api/v1/strategies/scheduler/status
```

현재 코드 기준 전략 스케줄러는 다음 두 작업을 다룹니다.

- `08:00` 유니버스 갱신
- `15:35` 일일 전략 실행

### 3. 알림 스케줄러 확인

```bash
curl -fsS http://localhost:${API_PORT:-10131}/api/v1/ops/notification-scheduler-status
```

현재 알림 슬롯:

- 매도 알림: `09:30`, `12:30`
- 매수 알림: `11:30`, `14:30`
- 각 알림 10분 전 데이터 갱신 수행

### 4. 운영 허브 페이지 확인

브라우저에서 아래 주소를 열면 운영 요약 대시보드를 볼 수 있습니다.

```text
http://localhost:${API_PORT:-10131}/ops
```

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

## 테스트

로컬 Python 환경 기준:

```bash
uv run pytest tests/interface/test_ops_page_router.py tests/domain/test_notification_scheduler_status.py -q
```

프로젝트 전체 테스트는 환경 의존성이 있으므로 필요한 범위부터 점진적으로 실행하는 것을 권장합니다.

## 알려진 한계

- 개별 page router를 테스트/별도 앱에서 직접 include하면 `main.py`와 동일한 관리자 guard를 별도로 붙여야 합니다.
- access log는 아직 `/api`, `/mypage`, `/health` 전체를 포괄하지 않습니다.
- `/api/v1/ops/summary` 는 여러 서비스 호출을 집계하므로, 일부 외부 API 상태가 나쁘면 응답이 느려질 수 있습니다.

## 다음 우선 개발 후보

- `/ops` summary 경량화 및 부분 실패 tolerant aggregation
- `/mypage/*` route-level 관리자 보호 확대
- access log 범위를 `/api`, `/mypage` 까지 확장
- notification scheduler 결과 이력 영속화
- README와 운영 문서의 지속 동기화
