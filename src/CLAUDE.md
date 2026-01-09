# CLAUDE.md - src 디렉토리 가이드

> 소스 코드 루트: FastAPI 애플리케이션 엔트리포인트와 레이어 진입점

## ✅ 역할
- FastAPI 앱 생성/라우터 등록 (`main.py`)
- CORS/예외 핸들러 설정 및 전역 설정 로드
- 애플리케이션 시작/종료 lifecycle 관리

---

## 📂 구조
```
src/
├── main.py                 # FastAPI 앱 생성/라우터 등록/라이프사이클
├── settings/               # 환경 설정(Pydantic Settings)
├── adapters/               # DB/Redis/KIS/Telegram/WS 연동
└── application/            # interface/domain/common 계층
```

---

## 🧠 main.py 핵심 흐름
- Startup
  - 환경 정보 로그 출력
  - DB 연결 확인 (`adapters.database.connection.engine`)
  - Redis 연결 확인 (`adapters.cache.redis_client`)
  - `auto_reauth` 활성화 시 KIS 토큰 발급 및 갱신 태스크 시작
  - 레거시 전략 엔진 시작 (`strategy.engine`)
  - 골든크로스 전략 스케줄러 시작 (`strategy.scheduler`)
  - Telegram 알림 스케줄러 시작 (`strategy.notification_scheduler`)
- Router 등록
  - `/api/v1/auth`, `/api/v1/market`, `/api/v1/accounts`, `/api/v1/orders`, `/api/v1/strategies`
  - `/api/v1/backtest` (라우터 내부 prefix)
  - `/ws` (WebSocket)
  - `/page/*` (대시보드)
- 기본 엔드포인트
  - `/` (서비스 상태 요약)
  - `/health` (헬스체크 스텁)
- Shutdown
  - 스케줄러/엔진/토큰 태스크 정리
  - KIS API HTTP 클라이언트 종료
  - DB/Redis 연결 종료

---

## ✅ 레이어 의존성 규칙
```
Interface → Domain → Adapters
         ↘ Common/Settings
```
- `main.py`는 라우터 등록/라이프사이클만 담당합니다.
- 비즈니스 로직은 `application/domain`에만 위치합니다.
- 외부 I/O는 `adapters`를 통해서만 수행합니다.

---

## 🔗 관련 문서
- `src/application/CLAUDE.md`
- `src/adapters/CLAUDE.md`
- `src/settings/CLAUDE.md`
