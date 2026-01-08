# CLAUDE.md - 프로젝트 가이드

> **KIS Trading API Service**: 한국투자증권 Open API 기반 자동매매 FastAPI 서버

## ✅ 프로젝트 개요
- FastAPI + PostgreSQL(asyncpg) + Redis 기반의 자동매매 서버
- 헥사고날 아키텍처(Interface → Domain → Adapters)를 기준으로 모듈을 분리
- `src/main.py`의 lifespan에서 DB/Redis 연결, KIS 토큰 갱신 태스크, 전략 엔진/스케줄러를 구동

---

## 📁 상위 디렉터리 구조
```
envelope-stock-fastapi/
├── src/                    # 애플리케이션 코드
│   ├── main.py             # FastAPI 엔트리포인트 + 라우터 등록
│   ├── settings/           # 환경 설정(Pydantic Settings)
│   ├── adapters/           # DB/Redis/KIS/WebSocket 연동
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

## 🧭 레이어 규칙 요약
```
Interface → Domain → Adapters
         ↘ Common/Settings
```
- Interface는 HTTP/WS 진입점만 담당하고 비즈니스 로직을 두지 않습니다.
- Domain은 비즈니스 규칙과 트랜잭션 경계를 관리합니다.
- Adapters는 외부 시스템(DB/Redis/KIS/WebSocket) 연동만 담당합니다.
- Common/Settings는 모든 레이어에서 사용하는 공통 규칙과 설정을 제공합니다.

---

## 🛠️ 운영/개발 규칙
- **Docker 재빌드 주의**: 컨테이너 재빌드 시 KIS 토큰이 재발급될 수 있으므로 재시작 위주로 운용합니다.
- **KIS 토큰 정책**: 접근 토큰은 1일 1회 발급 원칙을 준수하고 Redis 캐시를 활용합니다.
- **DB 드라이버**: `DATABASE_URL`은 asyncpg 드라이버를 사용합니다(설정에서 자동 보정).

---

## 🔗 세부 가이드
- `src/CLAUDE.md`
- `src/application/CLAUDE.md`
- `src/application/domain/CLAUDE.md`
- `src/application/common/CLAUDE.md`
- `src/application/interface/CLAUDE.md`
- `src/adapters/CLAUDE.md`
- `src/settings/CLAUDE.md`
