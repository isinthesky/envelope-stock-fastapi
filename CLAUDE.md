# CLAUDE.md - hantwo-stock-fastapi 프로젝트 가이드

> FastAPI 기반 KIS(Open API) 트레이딩/분석 서버. **헥사고날(Ports & Adapters)** 구조를 유지합니다.

## 레이어(폴더) 한눈에 보기

```text
Inbound (HTTP/WS/Page)        Application                 Outbound (I/O)
src/application/interface  -> src/application/domain  ->  src/adapters/*
                                ↑
                           src/application/common
                                ↑
                           src/settings
```

## 의존성 규칙 (Do / Don't)
- **허용 방향**: `interface → domain → adapters`
- **공통 사용**: `settings`, `application/common`은 모든 레이어에서 사용 가능
- **금지**
  - `domain`에서 FastAPI 객체(`Request`, `Response`) 직접 사용 금지
  - `interface`에서 DB 모델/Repository 직접 호출 금지(서비스 호출만)
  - `adapters`에서 비즈니스 규칙/정책 결정 금지(순수 I/O)

## 실행/개발 명령
- **의존성 설치**: `uv sync`
- **개발 서버**: `uvicorn src.main:app --reload`
- **테스트**: `pytest`
- **품질 도구**: `black src/ tests/`, `isort src/ tests/`, `mypy src/`

## 코드 추가 위치 가이드
- **새 REST API**: `src/application/interface/api/*_router.py` + `src/main.py`에 `include_router`
- **새 페이지(대시보드)**: `src/application/interface/page/*_page_router.py` + `page/__init__.py`의 `page_routers`에 등록
- **새 유즈케이스/서비스**: `src/application/domain/<domain>/service.py` (DTO는 `dto.py`)
- **새 외부 연동(KIS 외 API 등)**: `src/adapters/external/<provider>/...`
- **새 DB 엔티티/Repository**: `src/adapters/database/models`, `src/adapters/database/repositories`
- **환경 변수/설정 추가**: `src/settings/config.py` (+ `.env.example`는 템플릿만)

## 보안/운영 주의
- **절대 커밋 금지**: `.env`, 실전 키/시크릿/계좌번호, 토큰 캐시 파일류
- 로그에 인증정보를 남기지 말 것(특히 URL credential, 토큰)

## 레이어별 상세 문서
- `docs/base/CLAUDE.md` (문서 레이어 운영 규칙)
- `src/CLAUDE.md` (서버 엔트리포인트/라우터/라이프사이클)
- `src/application/CLAUDE.md` (application 하위 레이어 개요)
- `src/application/common/CLAUDE.md` (DTO/DI/데코레이터/태스크)
- `src/application/domain/CLAUDE.md` (도메인 서비스/엔진/스케줄러)
- `src/application/domain/news_trading/CLAUDE.md` (뉴스 트레이딩 서브도메인)
- `src/application/interface/CLAUDE.md` (API/WS/Page 라우팅 규칙)
- `src/adapters/CLAUDE.md` (DB/Redis/KIS/Naver/Telegram/WS 인프라)
- `src/settings/CLAUDE.md` (설정 규칙/환경 변수)

