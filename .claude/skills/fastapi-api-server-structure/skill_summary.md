# FastAPI API Server Structure — Rules/Structure Summary (~600L)

> 원문: `skill.md`  
> 목적: 레이어/규칙/체크리스트/패턴을 “규칙 구조 중심”으로 재정리한 요약본  
> 대상: FastAPI 기반 리팩토링/신규 기능 추가 시 일관된 계약(contract) 강제

---

## 0) 문서 사용 규칙 (읽는 법)

- **SSOT(단일 진실 원천)**을 항상 먼저 결정한다.
  - 응답/예외/세션/토큰/권한/DI provider는 “한 곳”이 원칙
- 규칙 강도:
  - **MUST**: 위반 시 설계 붕괴/운영 리스크가 큰 규칙
  - **SHOULD**: 유지보수성/일관성을 위한 권장 규칙
  - **MAY**: 팀/프로젝트 상황에 따라 선택

---

## 1) 전체 아키텍처 (5 Layer)

```
src/
├── main.py
├── settings/
├── adapters/
└── application/
    ├── interface/
    ├── domain/
    └── common/
```

### 1.1 Layer 의존성 방향 (MUST)

- **Interface → Domain → Adapters → Settings**
- 금지:
  - Domain이 FastAPI/Request/Depends를 import
  - Adapter가 Interface를 import
  - Settings가 Application 코드에 종속되는 구조

### 1.2 Layer별 책임 (핵심만)

- **Interface**
  - HTTP 파라미터/바디 검증, DI 조립(팩토리), 응답 래핑
  - 권한/인증 의존성 연결(토큰 추출 등)
- **Domain**
  - 비즈니스 규칙/정책, 도메인 DTO, 서비스 오케스트레이션
  - Repository/Adapter를 조합하여 “유스케이스” 구현
- **Adapters**
  - DB/스토리지/외부 API 등 IO만 담당(비즈니스 금지)
- **Common**
  - 공통 응답 모델, 예외 핸들러/로깅 유틸, 공유 도구
- **Settings**
  - 환경/보안/예외정의/ErrorCodes/dispatch(등록)

---

## 2) Interface Layer 규칙

### 2.1 API Router (`application/interface/api/...`) (MUST)

- **입력은 Pydantic Schema**, **출력은 ResponseBase 계열**로 표준화
- Router는 다음만 담당:
  - 입력 검증
  - `Depends()`로 서비스 주입
  - 서비스 호출 + 결과를 Response로 래핑
- Router에서 금지:
  - DB session 직접 생성/관리
  - 트랜잭션/커밋 직접 수행
  - 비즈니스 규칙/정책 로직 구현

### 2.2 Pages Router (`application/interface/pages/...`) (SHOULD)

- GET only, template 반환만 담당
- CUD는 API를 통해 수행(페이지 라우터에서 DB 변경 금지)

### 2.3 의존성(Dependencies) 구성 (MUST)

- Provider는 **단일 위치**에서 관리(SSOT)
  - settings/provider
  - adapters/provider
  - repositories/provider
  - services/provider
- Provider는 “조립”만 담당하고 비즈니스/IO 금지

---

## 3) Domain Layer 규칙 (3단 구조)

도메인 모듈은 아래 3단을 유지한다:

1) **Entities/DTO**
2) **Repository**
3) **Service**

### 3.1 DTO/Entity 규칙 (MUST)

- 외부 계약(응답)은 DTO로 고정: ORM/dict 노출 최소화
- DTO는 변환 메서드 제공:
  - `of()`, `from_entity()`, `to_dict()` 등 (프로젝트 표준에 맞춤)
- 시간/타임존/nullable 처리 규칙을 일관되게

DTO 예시:

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class EntityDTO:
    id: str
    status: str
    created_at: datetime

    @classmethod
    def of(cls, data: dict) -> "EntityDTO":
        return cls(
            id=data["id"],
            status=data.get("status", "pending"),
            created_at=data["created_at"],
        )
```

### 3.2 Service 규칙 (MUST)

- 서비스는 유스케이스 오케스트레이션 담당:
  - 정책(만료/상태전이/권한) 적용
  - 여러 Repository/Adapter 조합 가능
- 서비스 반환은 DTO 중심
- 서비스 내부에서 HTTPException 직접 발생 대신 도메인 예외 사용(프로젝트 정책에 따라)

### 3.3 Repository 규칙 (MUST)

- Repository는 데이터 접근 규약(쿼리/CRUD)만 제공
- Repository 내부에서 커밋/트랜잭션 경계 관리 금지(상위에서 통제)
- **세션 계약**은 아래 “트랜잭션/세션 계약” 섹션을 따른다

---

## 4) 트랜잭션/세션 계약 (Contract)

### 4.1 목표

- 세션 생성/commit/rollback 책임을 단일화
- Router/Service/Repository가 동일한 계약을 따르도록 정렬

### 4.2 핵심 규칙 (MUST)

- **Repository는 생성자에서 session을 받지 않는다.**
- **Repository 메서드는 `session`을 명시적 파라미터로 받는다.**
- **Service 메서드는 `@transaction`으로 세션 주입을 받는다.**
- **Service는 여러 Repository를 주입받을 수 있다.**

> (2026-01-14) 프로젝트 반영 규칙: “다중 Repository 주입 + session 전달”

### 4.3 Repository 예시

```python
from sqlalchemy.ext.asyncio import AsyncSession

class PermissionRepository:
    def __init__(self):
        pass

    async def list_by_user_id(self, session: AsyncSession, user_id: str):
        ...
```

### 4.4 Service 예시 (@transaction + 다중 repo)

```python
from sqlalchemy.ext.asyncio import AsyncSession

class UserService:
    def __init__(self, user_repo, perm_repo):
        self.user_repo = user_repo
        self.perm_repo = perm_repo

    @transaction
    async def get_user_with_permissions_for_auth(self, user_id: str, session: AsyncSession):
        user = await self.user_repo.get_by_id(session, user_id)
        perms = await self.perm_repo.list_by_user_id(session, user_id)
        return {"user": user, "permissions": perms}
```

### 4.5 DI 예시 (Service Factory에서 repo 다중 주입)

```python
from fastapi import Depends

async def get_user_service(
    user_repository = Depends(get_user_repository),
    permission_repository = Depends(get_permission_repository),
):
    return UserService(
        user_repo=user_repository,
        perm_repo=permission_repository,
    )
```

### 4.6 금지 패턴 (MUST)

- Router/Dependency에서 `async_session_maker()`로 세션 직접 생성
- Repository가 생성자에서 세션을 저장하고 재사용
- Repository가 내부에서 `commit()`/`rollback()` 수행

---

## 5) Common Layer 규칙

### 5.1 표준 응답(ResponseBase) (MUST)

- 모든 HTTP 응답은 아래 envelope를 따른다:
  - `success`, `message`, `timestamp`
  - 데이터는 `ResponseData[T]` / `ResponseListData[T]`
  - 오류는 `ErrorResponse`

요약 스키마:

```python
class ResponseBase(BaseModel):
    success: bool = True
    message: str = "성공적으로 처리되었습니다."
    timestamp: datetime = Field(default_factory=datetime.now)
    error_code: Optional[str] = None

class ResponseData(ResponseBase, Generic[T]):
    data: Optional[T] = None

class ResponseListData(ResponseBase, Generic[T]):
    data: List[T] = []
    total_count: int = 0
    page: int = 0
    limit: int = 0

class ErrorResponse(ResponseBase):
    success: bool = False
    error_details: Optional[Dict[str, Any]] = None
```

### 5.2 예외(Exceptions) 규칙 (MUST)

- 비즈니스 로직은 도메인 예외 사용(예: `BaseAPIException` 계열)
- 오류 코드는 `ErrorCodes` 상수로 표준화(하드코딩 금지)
- 예외 핸들러는 우선순위 기반 등록(특화 → 일반 → fallback)
- 민감 정보(토큰/비밀번호) 로그 금지

---

## 6) Settings Layer 규칙

### 6.1 ErrorCodes/Exceptions (MUST)

- 오류코드/예외 정의는 Settings에 중앙화
- 애플리케이션 전역에서 import하여 사용(SSOT)

### 6.2 Dispatch/Registration (SHOULD)

- 라우터 등록, 예외 핸들러 등록을 Settings/dispatch로 모아 “구성”을 중앙화

---

## 7) Adapters Layer 규칙

### 7.1 IO만 담당 (MUST)

- DB/스토리지/외부 API 호출만 구현
- 비즈니스 정책/권한/상태전이 금지
- FastAPI 의존성(Request/Depends) 금지

### 7.2 교체 가능성 (SHOULD)

- 추상 인터페이스(프로토콜/ABC)로 구현체 교체 가능하게 구성
- 환경 설정에 따라 backend 선택

---

## 8) Request Flow 표준

```
HTTP 요청
  → Interface Router (검증 + DI)
    → Domain Service (정책 + 유스케이스)
      → Repository/Adapter (IO)
    ← DTO 반환
  ← ResponseData/ResponseListData 래핑
```

예외 흐름:

```
Exception 발생
  → [1] 도메인 특화 핸들러
  → [2] 공통 핸들러(BaseAPIException/Validation/SQLAlchemy/HTTP)
  → [3] fallback(500)
```

---

## 9) 리팩토링 사전 분석 (필수 체크)

### 9.1 영향 범위 파악 (SHOULD)

- 변경 대상 함수/메서드 검색
- import 의존성 영향(호출자/테스트) 파악
- 응답 모델/DTO/예외 계약이 바뀌는지 점검

### 9.2 기존 패턴 정합성 확인 (MUST)

- 응답 모델(ResponseBase) 준수 여부
- DTO/Entity 반환 여부
- 예외 처리 경로(handlers/dispatch) 준수 여부
- 세션/트랜잭션 계약 준수 여부

---

## 10) 리팩토링 체크리스트 (요약)

### 10.1 구조 개선

- [ ] 레이어 경계 명확화
- [ ] DTO 계약 유지(ORM/dict 직접 반환 제거)
- [ ] 공통 로직은 Common으로 이동
- [ ] 순환 의존성 제거

### 10.2 세션/트랜잭션

- [ ] Router에서 세션 직접 생성 금지
- [ ] Repository 생성자에서 세션 금지
- [ ] Repository 메서드에 session 파라미터 추가
- [ ] Service에 `@transaction` 적용(쓰기/복합 작업)

### 10.3 예외/로깅/보안

- [ ] ErrorCodes 사용
- [ ] 민감정보 로그 제거
- [ ] 특화 핸들러/일반 핸들러 우선순위 점검

### 10.4 테스트

- [ ] 단위 테스트(서비스) + 통합 테스트(라우터)
- [ ] 회귀 테스트 실행
- [ ] edge case 추가

---

## 11) 코드 패턴 레퍼런스 (압축)

### 11.1 Router 패턴

```python
@router.post("/", response_model=ResponseData[EntityDTO])
async def create_entity(
    request: CreateEntityRequest,
    service: EntityService = Depends(get_entity_service),
):
    dto = await service.create(request.name, request.data)
    return ResponseData(data=dto, message="생성 성공")
```

### 11.2 DTO/Entity 패턴

```python
@dataclass
class EntityDTO:
    id: str
    name: str
    created_at: datetime

    @classmethod
    def of(cls, data: dict) -> "EntityDTO":
        return cls(
            id=data["id"],
            name=data["name"],
            created_at=data["created_at"],
        )
```

### 11.3 DI 패턴

```python
@lru_cache
def get_settings():
    return Settings()

@lru_cache
def get_storage():
    settings = get_settings()
    return PostgresStorage(settings) if settings.STORAGE_BACKEND == "postgres" else FilesystemStorage(settings)

def get_feature_service(storage=Depends(get_storage), settings=Depends(get_settings)):
    return FeatureService(storage, settings)
```

### 11.4 예외 응답 생성 패턴

```python
def create_error_response(status_code: int, message: str, error_code: str, error_details: dict | None = None) -> dict:
    return {
        "success": False,
        "message": message,
        "error_code": error_code,
        "error_details": error_details or {},
        "status_code": status_code,
    }
```

---

## 12) 작업 시나리오 플레이북 (요약)

### 12.1 신규 Resource 추가

- domain/entities DTO 추가(계약 확정)
- repository/service 추가(세션 계약 준수)
- router + schemas + dependencies factory 추가
- dispatch/main 라우터 등록
- tests 추가(단위 + 통합)

### 12.2 기존 서비스 메서드 추가

- DTO 변경 여부 판단(계약 변경이면 테스트/클라이언트 영향)
- 서비스 메서드 추가 + 필요한 repo 메서드 추가
- 회귀 테스트 + 신규 테스트

### 12.3 스토리지/백엔드 추가

- adapters 구현체 추가
- backend 선택 로직(설정/DI) 추가
- 통합 테스트(실환경/격리 환경 분리)

---

## 13) (2026-01-14) 프로젝트 적용 메모 (참조)

다중 Repository 주입/세션 계약 변경이 적용된 대표 파일:

- `src/application/domain/permission/permission_repository.py`
- `src/application/domain/permission/permission_service.py`
- `src/application/domain/user/user_service.py`
- `src/application/interface/api/dependencies/service.py`
- `src/application/interface/api/dependencies/auth.py` (세션 생성/주입 정책과 충돌 여부 점검 대상)

---

## 14) Layer별 Do / Don’t (운영 리스크 방지용)

### 14.1 Interface (Router/Dependency)

- **DO**
  - 요청 스키마/파라미터 검증은 Pydantic으로 끝낸다
  - 서비스는 `Depends()` 팩토리로 주입받는다
  - 반환은 `ResponseData[T]`, `ResponseListData[T]`로 래핑한다
  - 인증/권한 검증은 dependency로 분리한다
- **DON’T**
  - 세션 직접 생성(`async_session_maker()`) / commit / rollback
  - 비즈니스 정책 구현(상태 전이, TTL 등)
  - ORM 객체를 그대로 응답에 반환

### 14.2 Domain (Service/DTO/Repository)

- **DO**
  - 유스케이스를 서비스 메서드로 모델링한다
  - 복합 작업/쓰기 경계는 `@transaction`으로 통일한다
  - 여러 Repository 조합이 필요하면 서비스 생성자에서 주입받는다
  - Repository 호출은 항상 `(session, ...)` 형태로 통일한다
- **DON’T**
  - HTTPException 직접 raise(프로젝트 정책상 도메인 예외로 통일)
  - Repository에서 commit/rollback
  - FastAPI 의존성(Request/Depends) import

### 14.3 Adapters

- **DO**
  - IO/외부 연동을 캡슐화한다
  - timeout/재시도/에러 매핑을 일관되게 처리한다
- **DON’T**
  - 비즈니스 규칙/권한 정책을 구현
  - FastAPI 타입 사용

### 14.4 Settings/Common

- **DO**
  - 예외 정의(ErrorCodes + Exception classes)를 중앙화한다
  - 예외 핸들러/응답 envelope를 공통화한다
- **DON’T**
  - 애플리케이션 코드(도메인 로직)에 종속된 설정

---

## 15) 파일 템플릿 (복붙용)

### 15.1 Router 템플릿

```python
from fastapi import APIRouter, Depends
from src.application.common.response import ResponseData

router = APIRouter(prefix="/resources", tags=["resources"])

@router.post("/", response_model=ResponseData[EntityDTO])
async def create_resource(
    request: CreateResourceRequest,
    service: ResourceService = Depends(get_resource_service),
):
    dto = await service.create(request)
    return ResponseData(data=dto, message="생성 성공")
```

### 15.2 Schema 템플릿

```python
from pydantic import BaseModel, Field

class CreateResourceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
```

### 15.3 Repository 템플릿 (session 인자 계약)

```python
from sqlalchemy.ext.asyncio import AsyncSession

class ResourceRepository:
    def __init__(self):
        pass

    async def get_by_id(self, session: AsyncSession, resource_id: str):
        ...

    async def create(self, session: AsyncSession, data):
        ...
```

### 15.4 Service 템플릿 (@transaction + 다중 repo)

```python
from sqlalchemy.ext.asyncio import AsyncSession

class ResourceService:
    def __init__(self, repo: ResourceRepository, audit_repo: AuditRepository | None = None):
        self.repo = repo
        self.audit_repo = audit_repo

    @transaction
    async def create(self, request: CreateResourceRequest, session: AsyncSession):
        created = await self.repo.create(session, request)
        if self.audit_repo:
            await self.audit_repo.write(session, action="create", target_id=created.id)
        return EntityDTO.of(created)
```

### 15.5 Dependencies 템플릿 (조립만 담당)

```python
from fastapi import Depends

def get_resource_repository() -> ResourceRepository:
    return ResourceRepository()

def get_audit_repository() -> AuditRepository:
    return AuditRepository()

def get_resource_service(
    repo: ResourceRepository = Depends(get_resource_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
) -> ResourceService:
    return ResourceService(repo=repo, audit_repo=audit_repo)
```

---

## 16) 테스트 매트릭스 (서비스/라우터 기준)

### 16.1 서비스 단위 테스트 (SHOULD)

- **Given**: repo/audit_repo를 mock
- **When**: service 메서드 호출
- **Then**: 정책/예외/호출 순서/반환 DTO 검증

예시(개략):

```python
import pytest
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_create_calls_repo_and_returns_dto():
    repo = AsyncMock()
    repo.create.return_value = {"id": "1", "name": "x", "created_at": ...}
    service = ResourceService(repo=repo, audit_repo=None)
    dto = await service.create(CreateResourceRequest(name="x"))  # @transaction은 테스트에서 우회/fixture로 처리
    assert dto.id == "1"
```

### 16.2 라우터 통합 테스트 (SHOULD)

- **DI override**로 service를 교체하여 HTTP 계약만 검증
- Response envelope(`success/message/data`) 정합성 확인

---

## 17) 보안/운영 체크 (토큰/로그/민감정보)

- **로그 금지 항목(MUST)**: access token, refresh token, password, client_secret, authorization header 원문
- **토큰 타입 검증(MUST)**: access/refresh 혼용 금지(의존성에서 강제)
- **오류 응답(MUST)**: 내부 예외 메시지/스택을 클라이언트에 그대로 노출 금지
- **요청 식별자(SHOULD)**: request_id/contextvar로 연관 로그 추적

---

## 18) 트랜잭션/세션 블라인드 스팟 (자주 깨지는 지점)

- **중첩 세션**: 서비스→서비스 호출이 각각 새 세션을 만들면 원자성 깨짐
- **flush 의존**: 생성 직후 ID가 필요한 흐름(응답 DTO/audit target_id)에서 flush 정책 점검
- **detached/expired ORM**: commit 후 ORM 반환 시 접근 시점에 오류 가능 → DTO 변환 시점 고정
- **예외 경계**: IntegrityError 등에서 rollback/재시도 정책을 명시

---

## 19) 용어 매핑 (프로젝트별 치환)

| 일반 용어 | 예시 A | 예시 B |
|----------|--------|--------|
| `{app}` | `qr` | `shop` |
| `{resource}` | `images` | `products` |
| `{resource_type}` | `pixai` | `order` |
| `{resource_id}` | `group_id` | `product_id` |
| `{entity}` | `GroupMetadata` | `Product` |
| `{feature}` | `policy` | `pricing` |

