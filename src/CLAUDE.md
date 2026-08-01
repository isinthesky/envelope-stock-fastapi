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
  settings/        # Pydantic Settings
  adapters/        # DB/Redis/KIS/Naver/Telegram/WS
  application/     # interface/domain/common
```

## `main.py` 실행 흐름(현재 코드 기준)
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
    - `/api/v1/strategies` (Strategy)
    - `/api/v1/ohlcv` (OHLCV Cache)
    - `/api/v1/screener` (Screener: 라우터 내부 prefix)
    - `/api/v1/backtest` (Backtest: 라우터 내부 prefix)
  - WebSocket: `/ws`
  - Page(Jinja2): `page_routers` 루프 등록(각 라우터가 자체 prefix 보유)
- **기본 엔드포인트**
  - `/` : 간단 상태 요약(dict)
  - `/health` : 헬스체크 스텁(TODO 존재)
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

