# CLAUDE.md - common 디렉토리 가이드

> **공통 계층**: Interface/Domain/Adapter 어디서든 재사용하는 공통 DTO, 데코레이터, 의존성, 검증·지표 유틸 모음

## 역할
- DTO, 예외, 검증, 포맷터 등 **계약과 공통 규칙**을 제공해 도메인 코드 중복을 제거
- DB 세션, KIS 클라이언트, Redis 등 **의존성 주입 진입점**을 단일화
- 트랜잭션/재시도/캐시 같은 **횡단 관심사**를 데코레이터로 캡슐화
- 기술적 지표·성과 지표 계산을 표준화해 백테스트·전략 로직이 동일 수식을 공유

---

## 구조
```
common/
├── dto.py                 # BaseDTO, Response/Pagination DTO
├── decorators.py          # @transaction, @retry 등 횡단 관심사
├── dependencies.py        # DB/KIS/Redis DI 팩토리
├── validators.py          # 숫자·문자열 범용 검증 함수
├── formatters.py          # 금액/날짜 등 공통 포맷터
├── exceptions.py          # 애플리케이션 전역 커스텀 예외
├── indicators.py          # 기술적 지표 계산
├── performance_metrics.py # 성과 지표 계산
└── background_tasks.py    # 백그라운드 작업 유틸
```

---

## 파일별 요약
- `dto.py`: `BaseDTO`(Pydantic), `ResponseDTO`, `PaginationDTO`, `PaginatedResponseDTO` 등 **계약용 DTO** 정의.
- `decorators.py`: `@transaction`(AsyncSession 자동 관리), `@retry` 등 **서비스 단 레진** 기능 제공.
- `dependencies.py`: DB 세션, OrderRepository, KIS Auth/Client/WebSocket, Redis, Settings **DI 팩토리와 Type Alias** 정의.
- `validators.py`: 수치/문자열 범위·패턴 검증 함수. 도메인 DTO의 `field_validator`와 함께 사용.
- `formatters.py`: 금액/백분율/타임스탬프 등의 문자열 변환 헬퍼.
- `exceptions.py`: `ApplicationError` 베이스와 검증·리소스·인증 등 세분화 예외. 서비스에서 Adapter 예외를 래핑할 때 사용.
- `indicators.py`: SMA/EMA/RSI/MACD/Bollinger 등 **기술적 지표** 계산기.
- `performance_metrics.py`: MDD, 샤프/소르티노, CAGR, 승률, Profit Factor 등 **성과 지표** 계산기.
- `background_tasks.py`: FastAPI BackgroundTasks 연동, 주기적 작업 실행 헬퍼.

---

## 사용 규칙
- **계층 독립성**: Common은 도메인 지식이 없어야 하며 상위 계층(Interface/Domain/Adapter) 의존 금지.
- **의존성 주입**: Router/Service에서는 `dependencies.py`의 팩토리를 통해 DB/KIS/Redis를 주입한다.
- **예외 변환**: 외부/인프라 예외는 `exceptions.py`로 변환해 Interface 계층에서 일관 응답을 반환한다.
- **데코레이터 범위**: `@transaction`은 Service public 메서드에만 적용, Repository 내부 호출에는 사용하지 않는다.
- **수치 정밀도**: 금액/비율은 `Decimal`을 우선 사용하고, 포맷팅은 `formatters.py`를 통해 수행한다.
- **지표/성과 표준화**: 전략·백테스트에서 동일 결과를 보장하기 위해 지표/성과 계산은 common 모듈을 사용한다.

---

## 참고
- 상위 계층 개요: `src/application/CLAUDE.md`
- 도메인 가이드: `src/application/domain/CLAUDE.md`
- 어댑터/설정 가이드: `src/adapters/CLAUDE.md`, `src/settings/CLAUDE.md`
