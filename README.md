# KIS Trading API Service

> 한국투자증권 Open API 기반 증권 자동매매 API 서버

## 📋 프로젝트 개요

**헥사고날 아키텍처(Hexagonal Architecture)** 기반 엔터프라이즈급 자동매매 시스템

### 주요 기능

- ✅ **다중 상품 지원** - 국내/해외 주식, 선물옵션, 채권, ETF/ETN (166개 API)
- ✅ **실전/모의투자** - 환경 분리 및 안전한 테스트
- ✅ **실시간 시세** - WebSocket 기반 실시간 데이터
- ✅ **자동매매 전략** - 조건 기반 자동 주문 실행
- ✅ **리스크 관리** - 손실 제한, 포지션 관리
- ✅ **대시보드** - 실시간 모니터링 및 관리

### 기술 스택

- **Backend**: FastAPI, Python 3.9+
- **Database**: PostgreSQL 14+, SQLAlchemy (async)
- **Cache**: Redis 7+
- **WebSocket**: websockets, asyncio
- **Package Manager**: UV

---

## 🚀 빠른 시작

### 1. 환경 설정

```bash
# 저장소 클론
git clone <repository-url>
cd hantwo-stock-fastapi

# UV로 의존성 설치
uv sync

# 환경 변수 설정
cp .env.example .env
# .env 파일 수정 (KIS API 키 입력)
```

### 2. KIS API 키 발급

1. [한국투자증권 Open API 포털](https://apiportal.koreainvestment.com/) 접속
2. 앱키(App Key), 앱시크릿(App Secret) 발급
3. `.env` 파일에 키 입력

```env
# 실전투자
KIS_APP_KEY=your_real_app_key
KIS_APP_SECRET=your_real_app_secret

# 모의투자
KIS_PAPER_APP_KEY=your_paper_app_key
KIS_PAPER_APP_SECRET=your_paper_app_secret
```

### 3. 서버 실행

```bash
# 개발 서버 실행
python -m src.main

# 또는 uvicorn 직접 실행
uvicorn src.main:app --reload --port 8000
```

### 4. API 문서 확인

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

## 📁 프로젝트 구조

```
hantwo-stock-fastapi/
├── docs/                       # 프로젝트 문서
│   ├── CLAUDE.md               # 프로젝트 개요
│   ├── ARCHITECTURE.md         # 아키텍처 설계
│   ├── SERVICE.md              # 서비스 구현 가이드
│   └── convention.md           # 코딩 컨벤션
│
├── examples/                   # KIS API 샘플 코드
│   ├── examples_user/          # 사용자용 통합 예제
│   └── examples_llm/           # LLM용 기능 단위 샘플
│
├── src/                        # 소스 코드
│   ├── adapters/               # 어댑터 계층
│   │   ├── database/           # DB 모델 & Repository
│   │   ├── external/           # KIS API, WebSocket
│   │   └── cache/              # Redis 캐싱
│   │
│   ├── application/            # 애플리케이션 계층
│   │   ├── common/             # 공통 유틸리티
│   │   ├── domain/             # 도메인 서비스
│   │   │   ├── auth/           # 인증
│   │   │   ├── order/          # 주문
│   │   │   ├── account/        # 계좌
│   │   │   ├── market_data/    # 시세
│   │   │   ├── strategy/       # 전략
│   │   │   └── websocket_domain/  # 실시간 데이터
│   │   └── interface/          # API Router
│   │
│   ├── settings/               # 환경 설정
│   │   └── config.py           # Pydantic Settings
│   │
│   └── main.py                 # FastAPI 애플리케이션
│
├── tests/                      # 테스트 코드
├── .env.example                # 환경 변수 템플릿
├── .gitignore                  # Git 제외 파일
├── pyproject.toml              # 프로젝트 의존성
└── README.md                   # 본 문서
```

---

## 🏗️ 아키텍처

### 헥사고날 아키텍처 (Ports & Adapters)

```
┌─────────────────────────────────────────────┐
│            외부 세계 (External)              │
│  Client, KIS API, Database, Redis, WebSocket │
└─────────────────────────────────────────────┘
                    ↕
┌─────────────────────────────────────────────┐
│         Adapters Layer (어댑터 계층)          │
│  REST Router, DB Adapter, KIS Client, Cache  │
└─────────────────────────────────────────────┘
                    ↕
┌─────────────────────────────────────────────┐
│      Application Layer (애플리케이션 계층)     │
│     Service, Repository, DTO, Utils          │
└─────────────────────────────────────────────┘
                    ↕
┌─────────────────────────────────────────────┐
│          Domain Layer (도메인 계층)           │
│   Auth, Order, Account, MarketData, Strategy │
└─────────────────────────────────────────────┘
```

### 핵심 패턴

- **BaseRepository + Mixin**: 40% 코드 감소
- **의존성 주입 중앙화**: 100% 일관성
- **@transaction 데코레이터**: 선언적 트랜잭션 관리
- **비동기 처리**: asyncio + SQLAlchemy async
- **캐싱 전략**: Redis (시세 5초, 계좌 30초, 토큰 24시간)

---

## 📚 개발 가이드

### 개발 명령어

```bash
# 의존성 설치
uv sync

# 개발 서버 실행
python -m src.main

# 테스트 실행
pytest

# 테스트 커버리지
pytest --cov=src tests/

# 코드 포맷팅
black src/
isort src/

# 타입 체크
mypy src/

# 데이터베이스 마이그레이션
alembic upgrade head
alembic revision --autogenerate -m "description"
```

### 환경 변수

주요 환경 변수는 `.env.example` 참고

- `TRADING_ENVIRONMENT`: `prod` (실전) / `vps` (모의)
- `DATABASE_URL`: PostgreSQL 연결 URL
- `REDIS_URL`: Redis 연결 URL
- `KIS_APP_KEY`, `KIS_APP_SECRET`: KIS API 인증

---

## 🔒 보안 및 리스크 관리

### 보안 원칙

- ✅ API 키는 환경 변수로만 관리
- ✅ 토큰은 안전한 경로에 암호화 저장
- ✅ 실전/모의 환경 완전 분리
- ✅ WebSocket 연결 시 approval_key 검증

### 리스크 관리

- ⚠️ **모의투자 우선**: 실전 투자 전 충분한 테스트
- ⚠️ **손실 제한**: 일일 손실 한도 설정
- ⚠️ **포지션 관리**: 최대 보유 종목 수 제한
- ⚠️ **긴급 정지**: 전체 주문 취소 기능

---

## 📖 문서

- [프로젝트 개요](docs/CLAUDE.md)
- [아키텍처 설계](docs/base/ARCHITECTURE.md)
- [서비스 구현 가이드](docs/base/SERVICE.md)
- [코딩 컨벤션](docs/base/convention.md)

---

## 🔗 참고 링크

- [한국투자증권 Open API 포털](https://apiportal.koreainvestment.com/)
- [FastAPI 공식 문서](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0 Async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [UV Package Manager](https://docs.astral.sh/uv/)

---

## 📞 문의 및 지원

- **프로젝트**: KIS Trading API Service
- **버전**: 0.1.0
- **최종 업데이트**: 2025년 10월 7일

---

## ⚠️ 투자 책임 고지

**본 시스템은 한국투자증권 OPEN API를 활용한 자동매매 도구이며, 투자 조언이나 권유를 제공하지 않습니다.**

- 📈 **투자 결정 책임**: 모든 투자 결정과 그에 따른 손익은 전적으로 투자자 본인의 책임입니다
- 💰 **손실 위험**: 주식, 선물, 옵션 등 모든 금융상품 투자에는 원금 손실 위험이 있습니다
- 🎯 **모의투자 권장**: 실전 투자 전 반드시 모의투자를 통해 충분히 연습하시기 바랍니다

**투자는 본인의 판단과 책임 하에 이루어져야 하며, 본 시스템 사용으로 인한 어떠한 손실에 대해서도 개발자는 책임지지 않습니다.**

---

## 📄 라이선스

MIT License
