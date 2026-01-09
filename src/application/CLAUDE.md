# CLAUDE.md - application 디렉토리 가이드

> **Application 계층**: API 진입점, 비즈니스 로직, 공통 유틸을 묶는 핵심 레이어

## ✅ 역할
- Interface: HTTP/WS 라우터 + 관리자 페이지 라우터 제공
- Domain: 서비스/엔진/스케줄러 등 비즈니스 로직 실행
- Common: DTO/의존성/데코레이터/지표 계산 등 공통 규칙 제공

---

## 📂 구조
```
application/
├── interface/              # API/페이지 라우터
│   ├── api/                # REST/WS 라우터
│   └── page/               # 대시보드 페이지 라우터
├── domain/                 # 비즈니스 로직 (서비스, 엔진, 스케줄러)
└── common/                 # 공통 DTO/데코레이터/유틸
```

---

## 🌐 interface/ 역할
- FastAPI 라우터만 담당하며 비즈니스 로직을 포함하지 않습니다.
- 의존성은 `common/dependencies.py`의 Alias를 사용합니다.
- 응답은 `ResponseDTO`를 기본으로 사용합니다(예외: backtest 라우터).
- `/page/market-data`는 기본 탭 + 고급 필터 탭을 제공하며, 고급 필터는 클라이언트 입력 데이터 기준으로 동작합니다.

---

## 💼 domain/ 역할
- 서비스 단에서 데이터 검증, 캐시 전략, 트랜잭션 경계를 관리합니다.
- Repository/Client 등 외부 연동은 Adapter 계층을 통해 수행합니다.
- 전략 모듈은 매수/매도 분석을 분리 서비스로 관리합니다.

---

## 🔧 common/ 역할
- `BaseDTO`, `ResponseDTO` 등 계약 객체 제공
- `@transaction`, `@retry`, `@cache` 등의 횡단 관심사를 캡슐화
- 의존성 주입 진입점(`dependencies.py`) 제공

---

## ✅ 레이어 규칙
- **Interface → Domain → Adapters** 방향만 허용
- Interface는 Repository/DB 세션을 직접 다루지 않음
- Domain은 FastAPI Request/Response 객체에 의존하지 않음
- Common은 상위 레이어(Interface/Domain)에 대한 의존을 두지 않음

---

## 🔗 관련 문서
- `src/application/interface/CLAUDE.md`
- `src/application/domain/CLAUDE.md`
- `src/application/common/CLAUDE.md`
