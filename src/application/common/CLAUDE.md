# CLAUDE.md - `application/common/` 가이드

> 전 레이어에서 재사용하는 **계약(DTO)**, **의존성 주입(DI)**, **횡단 관심사(트랜잭션/재시도/캐시)**, **지표/성과 계산 유틸**을 제공합니다.

## 구성(현재 파일 기준)

```text
common/
  dto.py                 # BaseDTO, ResponseDTO, Pagination DTO
  dependencies.py        # FastAPI DI: DB/KIS/Redis/Settings/일부 서비스
  decorators.py          # @transaction, @retry, @cache, @log_execution, @validate_input
  exceptions.py          # 공통 예외(도메인에서 래핑/변환에 사용)
  validators.py          # 입력 검증 유틸
  formatters.py          # 포맷팅 유틸
  indicators.py          # 기술적 지표 계산
  performance_metrics.py # 성과 지표 계산
  background_tasks.py    # 토큰 자동 갱신 등 백그라운드 태스크
```

## 사용 규칙 (중요)
- **역의존 금지**: common은 `interface/*`, `domain/*`을 import 하지 않습니다.
- **Response 계약**
  - REST API 기본 응답: `ResponseDTO.success_response(...)` / `ResponseDTO.error_response(...)`
  - 예외적으로 “raw DTO 반환”이 필요한 경우(예: Backtest)에는 interface 문서에 명시합니다.
- **DI 사용**
  - DB 세션: `DatabaseSession`(= `Annotated[AsyncSession, Depends(get_session)]`) 사용을 우선
  - KIS/Redis/WebSocket: `KISClientDep`, `RedisDep`, `KISWebSocketDep` 등 Alias 활용
- **@transaction**
  - Service의 “외부 호출되는 public 메서드”에만 적용(내부 헬퍼에는 적용 금지)
  - 현재 구현은 `AsyncSessionLocal()`로 세션을 생성해 commit/rollback을 수행합니다.
  - 권장 시그니처(패턴):
    - `async def foo(self, session: AsyncSession, ...)` (첫 인자로 session을 받도록)
- **@cache**
  - Redis에 저장 가능한 타입(직렬화 가능한 dict/str/int/float/list 등)만 반환하도록 설계
  - Pydantic 모델은 `model_dump()` 후 캐시하는 방식 권장

## 변경 시 체크리스트
- DTO 변경 시: 응답 스키마(라우터 response_model)와 템플릿/Page 화면 영향 확인
- dependencies 확장 시: 순환 import(특히 domain ↔ common) 발생 여부 점검
- cache/transaction 도입 시: 세션/캐시 경계가 도메인 정책과 일치하는지 점검

## 관련 문서
- `src/application/CLAUDE.md`
- `src/application/interface/CLAUDE.md`
- `src/application/domain/CLAUDE.md`
- `src/adapters/CLAUDE.md`

