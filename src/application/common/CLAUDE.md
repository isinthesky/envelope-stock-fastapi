# CLAUDE.md - common 디렉토리 가이드

> **공통 계층**: 전 레이어에서 재사용하는 DTO/의존성/데코레이터/지표 유틸 모음

## ✅ 역할
- 공통 DTO/예외/검증 규칙을 제공
- DB/KIS/Redis DI 팩토리를 단일화
- 트랜잭션/재시도/캐시 같은 횡단 관심사를 캡슐화
- 기술적 지표/성과 지표 계산 로직 표준화

---

## 📂 구조
```
common/
├── dto.py                 # BaseDTO, Response/Pagination DTO
├── decorators.py          # @transaction, @retry, @cache 등
├── dependencies.py        # DB/KIS/Redis DI 팩토리
├── validators.py          # 입력 검증 유틸
├── formatters.py          # 데이터 포맷터
├── exceptions.py          # 커스텀 예외
├── indicators.py          # 기술적 지표 계산
├── performance_metrics.py # 성과 지표 계산
└── background_tasks.py    # KIS 토큰 갱신 백그라운드 태스크
```

---

## ✅ 사용 규칙
- Common은 상위 레이어(Interface/Domain)에 의존하지 않습니다.
- DB/KIS/Redis 주입은 `dependencies.py`의 Alias를 사용합니다.
- `@transaction`은 Service public 메서드에만 적용합니다.
- 캐시/재시도 정책은 Service에서 결정하되 데코레이터로 캡슐화합니다.
- 금액/비율은 Decimal을 우선 사용합니다.

---

## 🔗 관련 문서
- `src/application/CLAUDE.md`
- `src/application/domain/CLAUDE.md`
- `src/adapters/CLAUDE.md`
