# CLAUDE.md - 프로젝트 가이드

> **KIS Trading API Service**: 한국투자증권 Open API 기반 자동매매 FastAPI 서버

## ✅ 프로젝트 개요
- FastAPI + PostgreSQL(asyncpg) + Redis 기반 자동매매/분석 서버
- 헥사고날 아키텍처(Interface → Domain → Adapters)를 준수
- `src/main.py` lifespan에서 인프라 연결 및 백그라운드 스케줄러 구동

---

## 📁 상위 디렉터리 구조
```
envelope-stock-fastapi/
├── src/                    # 애플리케이션 코드
│   ├── main.py             # FastAPI 엔트리포인트 + 라우터 등록
│   ├── settings/           # 환경 설정(Pydantic Settings)
│   ├── adapters/           # DB/Redis/KIS/Telegram/WS 연동
│   └── application/        # interface/domain/common 계층
├── templates/              # Jinja2 대시보드 템플릿
├── tests/                  # 테스트 (pytest)
├── examples/               # 실행 가능한 예제 스크립트
├── docs/                   # 문서
├── scripts/                # 유틸/실험 스크립트
├── alembic/                # DB 마이그레이션
├── docker-compose.yml      # 로컬 개발용 인프라
└── .env.example            # 환경 변수 템플릿
```

---

## 🧠 실행 흐름 요약
`src/main.py`의 lifespan에서 아래 작업을 수행합니다.
- DB 연결 확인
- Redis 연결 확인
- KIS 토큰 발급 및 토큰 갱신 태스크 시작
- 레거시 전략 엔진(볼린저/엔벨로프) 시작
- 골든크로스 전략 스케줄러 시작
- Telegram 알림 스케줄러 시작(설정 시)

---

## 🧭 레이어 규칙
```
Interface → Domain → Adapters
         ↘ Common/Settings
```
- Interface는 HTTP/WS 진입점만 담당합니다.
- Domain은 비즈니스 규칙과 트랜잭션 경계를 관리합니다.
- Adapters는 외부 연동(DB/Redis/KIS/Telegram)을 담당합니다.
- Common/Settings는 모든 레이어에서 공통으로 사용합니다.

---

## 🔗 세부 가이드
- `src/CLAUDE.md`
- `src/application/CLAUDE.md`
- `src/application/domain/CLAUDE.md`
- `src/application/common/CLAUDE.md`
- `src/application/interface/CLAUDE.md`
- `src/adapters/CLAUDE.md`
- `src/settings/CLAUDE.md`
