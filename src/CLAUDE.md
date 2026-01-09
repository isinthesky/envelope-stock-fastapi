# CLAUDE.md - src 디렉토리 가이드

> **소스 코드 루트**: FastAPI 애플리케이션의 핵심 모듈이 모이는 디렉터리

## ✅ 역할
- FastAPI 엔트리포인트(`main.py`) 제공
- 환경 설정/외부 연동/비즈니스 로직을 레이어로 분리
- 헥사고날 아키텍처 규칙을 유지

---

## 📂 구조
```
src/
├── main.py                 # FastAPI 앱 생성/라우터 등록/라이프사이클
├── settings/               # 환경 설정(Pydantic Settings)
├── adapters/               # 외부 연동(DB/Redis/KIS/Telegram/WS)
└── application/            # interface/domain/common 계층
```

---

## 🧠 main.py 핵심 흐름
- lifespan에서 다음을 순차적으로 수행합니다.
  - DB 연결 확인
  - Redis 연결 확인
  - KIS 토큰 발급 및 갱신 태스크 시작
  - 레거시 전략 엔진 시작
  - 골든크로스 전략 스케줄러 시작
  - Telegram 알림 스케줄러 시작
- 라우터 등록은 `main.py`에서 일괄 수행합니다.
  - `/api/v1/*` REST 라우터
  - `/ws` WebSocket 라우터
  - `/page/*` 대시보드 라우터

---

## ✅ 레이어 의존성 규칙
```
Interface → Domain → Adapters
         ↘ Common/Settings
```
- Interface는 Domain 서비스만 호출합니다.
- Domain은 Repository/Client를 통해 외부 연동을 수행합니다.
- Adapters는 비즈니스 로직을 포함하지 않습니다.
- Common/Settings는 모든 레이어에서 공통으로 참조합니다.

---

## 🔗 관련 문서
- `src/application/CLAUDE.md`
- `src/adapters/CLAUDE.md`
- `src/settings/CLAUDE.md`
