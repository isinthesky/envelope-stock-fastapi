# CLAUDE.md - `src/application/` (Application 레이어) 가이드

> Inbound(interface)와 비즈니스(domain), 공통(common)을 묶는 “유즈케이스/계약” 레이어입니다.

## 이 레이어의 역할
- **interface/**: HTTP/WS/Page 진입점(라우팅/파라미터 파싱/응답 포맷)
- **domain/**: 비즈니스 규칙/정책/조합(서비스/엔진/스케줄러)
- **common/**: DTO/DI/횡단관심사(트랜잭션·캐시·재시도)/지표·성과 계산

## 폴더 구조

```text
application/
  interface/
    api/          # REST/WS 라우터
    page/         # Jinja2 페이지 라우터
  domain/         # 서비스/엔진/스케줄러 + 서브도메인 패키지들
  common/         # DTO/DI/데코레이터/유틸
```

## 의존성/규칙
- **허용 방향**: `interface → domain → adapters`
- **common은 아래 규칙을 지켜야 함**
  - interface/domain을 import해서는 안 됨(역의존 금지)
  - “계약/유틸”만 제공(도메인 정책 결정 금지)
- **domain 규칙**
  - FastAPI 객체에 의존하지 말 것
  - 외부 I/O는 adapters를 통해서만 수행
- **interface 규칙**
  - 서비스 호출만 수행(비즈니스 로직/쿼리 조합 금지)
  - 응답 포맷은 기본적으로 `ResponseDTO`로 감싸기(예외는 문서에 명시)

## 관련 문서
- `src/application/interface/CLAUDE.md`
- `src/application/domain/CLAUDE.md`
- `src/application/common/CLAUDE.md`

