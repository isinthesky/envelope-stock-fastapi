---
name: fastapi-api-server-structure
description: FastAPI 애플리케이션의 5계층 아키텍처, 세션/트랜잭션 계약, SSOT 원칙 기반 리팩토링 가이드. 다중 Repository 주입 패턴과 @transaction 데코레이터를 통한 세션 관리를 준수합니다.
---

# FastAPI API Server Structure

FastAPI 애플리케이션 리팩토링 시 준수해야 할 계층 분리, 세션 계약, SSOT 원칙을 정의합니다.

> **관련 스킬**: `fastapi-page-architecture` (Page Router), `layer-optimize` (의존성 분석), `refactor-suggest` (코드 개선)

---

## 1. 아키텍처 개요

### 1.1 5계층 구조

```
src/
├── main.py                      # FastAPI 앱, 미들웨어, 라우터 등록
├── settings/                    # 환경/보안/예외 설정
├── adapters/                    # 인프라 IO (DB/Storage/External)
└── application/
    ├── common/                  # 공통 유틸, 응답/예외 핸들러
    ├── domain/                  # 비즈니스 서비스/Repository/DTO
    └── interface/               # API/페이지 라우터 + 스키마
```

### 1.2 의존성 방향 (MUST)

```
Interface → Domain → Adapters → Settings
```

**금지 패턴**:
- Domain이 FastAPI/Request/Depends를 import
- Adapter가 Interface를 import
- Settings가 Application에 종속

---

## 2. SSOT (Single Source of Truth) 원칙

### 2.1 중앙화 대상

| 대상 | SSOT 위치 | 비고 |
|-----|----------|------|
| Repository DI | `dependencies/service.py` | `get_*_repository()` |
| Service DI | `dependencies/service.py` | `get_*_service()` |
| OAuth 제공자 | `common/constants.py` | `SUPPORTED_OAUTH_PROVIDERS` |
| 에러 코드 | `settings/exceptions.py` | `ErrorCodes` |
| 세션 관리 | `common/context.py` | `@transaction`, `get_db_context()` |
| 응답 모델 | `common/response.py` | `ResponseData`, `ResponseListData` |

### 2.2 중복 정의 금지 (MUST)

```python
# ❌ 금지: 여러 파일에서 동일 함수 정의
# router_a.py
def get_permission_repository(): return PermissionRepository()
# router_b.py
def get_permission_repository(): return PermissionRepository()

# ✅ 권장: SSOT에서 정의, 다른 곳에서 import
# dependencies/service.py (SSOT)
async def get_permission_repository() -> PermissionRepository:
    return PermissionRepository()

# router_a.py, router_b.py
from src.application.interface.api.dependencies.service import get_permission_repository
```

---

## 3. 계층별 책임

### 3.1 Interface Layer

**책임**: HTTP 요청/응답 처리, DTO 검증, DI 조립

```python
# interface/api/v1/routers/{resource}_router.py
@router.post("/", response_model=ResponseData[EntityDTO])
async def create_entity(
    request: CreateRequest,
    service: EntityService = Depends(get_entity_service),
):
    dto = await service.create(request.name)
    return ResponseData(data=dto, message="생성 성공")
```

**규칙**:
- 입력은 Pydantic Schema, 출력은 `ResponseBase` 계열
- 비즈니스 로직 구현 금지 (서비스에 위임)
- DB 세션 직접 생성/커밋 금지

### 3.2 Domain Layer (3단 구조)

각 도메인 모듈은 **DTO → Repository → Service** 구조 유지:

```
domain/{feature}/
├── {feature}_dto.py        # DTO/Entity 정의
├── {feature}_repository.py # 데이터 접근
└── {feature}_service.py    # 비즈니스 로직
```

**DTO 규칙**:
```python
@dataclass
class EntityDTO:
    id: str
    name: str

    @classmethod
    def from_entity(cls, entity) -> "EntityDTO":
        return cls(id=str(entity.id), name=entity.name)
```

### 3.3 Common Layer

**핵심 모듈**:

| 모듈 | 책임 |
|------|------|
| `response.py` | `ResponseBase`, `ResponseData[T]`, `ResponseListData[T]` |
| `context.py` | `@transaction`, `get_db_context()` |
| `exception_handlers.py` | 예외 핸들러 |
| `constants.py` | 공통 상수 (역할, OAuth 제공자 등) |

### 3.4 Adapter Layer

**책임**: DB/스토리지/외부 API IO만 담당 (비즈니스 금지)

### 3.5 Settings Layer

**책임**: 환경 변수, 예외 정의, 디스패처

---

## 4. 세션/트랜잭션 계약 (핵심)

### 4.1 핵심 규칙 (MUST)

1. **Repository는 생성자에서 session을 받지 않는다**
2. **Repository 메서드는 session을 파라미터로 받는다**
3. **Service 메서드는 `@transaction`으로 session을 주입받는다**
4. **Service는 여러 Repository를 주입받을 수 있다**

### 4.2 Repository 패턴

```python
# domain/{feature}/{feature}_repository.py
class PermissionRepository:
    def __init__(self):
        pass  # session 받지 않음

    async def get_by_id(self, session: AsyncSession, id: str):
        stmt = select(Permission).where(Permission.id == id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, session: AsyncSession, data: dict):
        entity = Permission(**data)
        session.add(entity)
        await session.flush()
        return entity
```

### 4.3 Service 패턴 (다중 Repository 주입)

```python
# domain/{feature}/{feature}_service.py
class UserService:
    def __init__(
        self,
        user_repository: UserRepository,
        permission_repository: Optional[PermissionRepository] = None,
    ):
        self.repo = user_repository
        self.perm_repo = permission_repository

    @transaction
    async def get_user_with_permissions(
        self, user_id: str, session: AsyncSession
    ):
        user = await self.repo.get_by_id(session, user_id)
        if not user:
            raise NotFoundError("사용자를 찾을 수 없습니다")

        permissions = []
        if self.perm_repo:
            permissions = await self.perm_repo.get_by_user_id(session, user_id)

        return UserWithPermissionsDTO.from_entity(user, permissions)
```

### 4.4 DI 패턴 (서비스 팩토리)

```python
# interface/api/dependencies/service.py
async def get_user_repository() -> UserRepository:
    return UserRepository()

async def get_permission_repository() -> PermissionRepository:
    return PermissionRepository()

async def get_user_service(
    user_repo: UserRepository = Depends(get_user_repository),
    perm_repo: PermissionRepository = Depends(get_permission_repository),
) -> UserService:
    return UserService(
        user_repository=user_repo,
        permission_repository=perm_repo,
    )
```

### 4.5 금지 패턴

```python
# ❌ Router에서 세션 직접 생성
@router.get("/{id}")
async def get_user(id: str):
    async with async_session_maker() as session:  # 금지
        user = await session.get(User, id)
        return user

# ❌ Repository 생성자에서 세션 받기
class BadRepository:
    def __init__(self, session: AsyncSession):  # 금지
        self.session = session

# ❌ Repository에서 commit/rollback
class BadRepository:
    async def create(self, session, data):
        session.add(entity)
        await session.commit()  # 금지 - 상위에서 처리
```

---

## 5. 응답/예외 표준

### 5.1 표준 응답 모델

```python
class ResponseBase(BaseModel):
    success: bool = True
    message: str = "성공"
    timestamp: datetime = Field(default_factory=datetime.now)
    error_code: Optional[str] = None

class ResponseData(ResponseBase, Generic[T]):
    data: Optional[T] = None

class ResponseListData(ResponseBase, Generic[T]):
    data: List[T] = []
    total_count: int = 0
    page: int = 0
    limit: int = 0
```

### 5.2 예외 계층

```
BaseAPIException
├── UnauthorizedError (401)
├── ForbiddenError (403)
├── NotFoundError (404)
├── ConflictError (409)
├── ValidationError (400)
├── RateLimitExceededError (429)
└── DatabaseError (500)
```

### 5.3 서비스에서 예외 발생

```python
# domain/services/resource_service.py
async def get_by_id(self, resource_id: str, session: AsyncSession):
    resource = await self.repo.get_by_id(session, resource_id)
    if not resource:
        raise NotFoundError("리소스를 찾을 수 없습니다")
    return ResourceDTO.from_entity(resource)
```

---

## 6. 요청 흐름

```
HTTP 요청
  → Interface (Router)
    - Pydantic 검증
    - Depends()로 서비스 주입
  → Domain (Service)
    - @transaction으로 세션 주입
    - 비즈니스 로직 실행
    - Repository 호출 (session 전달)
  → Repository
    - 데이터 조회/저장
  ← DTO 반환
  ← ResponseData 래핑
```

**예외 흐름**:
```
Exception 발생
  → [1순위] 특화 핸들러 (RateLimitExceeded, Auth 등)
  → [2순위] 일반 핸들러 (BaseAPIException, Validation)
  → [3순위] Fallback (500)
```

---

## 7. 리팩토링 체크리스트

### 7.1 구조

- [ ] 레이어 경계 준수 (Interface → Domain → Adapter)
- [ ] DTO 반환 (ORM/dict 직접 반환 제거)
- [ ] 순환 의존성 제거
- [ ] SSOT 원칙 준수 (중복 정의 제거)

### 7.2 세션/트랜잭션

- [ ] Repository 생성자에서 session 제거
- [ ] Repository 메서드에 session 파라미터 추가
- [ ] Service에 `@transaction` 적용
- [ ] Router에서 세션 직접 생성 제거

### 7.3 예외/보안

- [ ] `ErrorCodes` 상수 사용
- [ ] 민감정보 로그 제거 (토큰, 비밀번호)
- [ ] 예외 핸들러 우선순위 확인

### 7.4 테스트

- [ ] 단위 테스트: 서비스 (mock repository)
- [ ] 통합 테스트: 라우터 (fixture)
- [ ] edge case 커버

---

## 8. 코드 템플릿

### 8.1 Router

```python
from fastapi import APIRouter, Depends
from src.application.common.response import ResponseData
from src.application.interface.api.dependencies.service import get_resource_service

router = APIRouter(prefix="/resources", tags=["resources"])

@router.post("/", response_model=ResponseData[ResourceDTO])
async def create(request: CreateRequest, service = Depends(get_resource_service)):
    dto = await service.create(request)
    return ResponseData(data=dto, message="생성 성공")
```

### 8.2 Repository

```python
from sqlalchemy.ext.asyncio import AsyncSession

class ResourceRepository:
    def __init__(self):
        pass

    async def get_by_id(self, session: AsyncSession, id: str):
        return await session.get(Resource, id)

    async def create(self, session: AsyncSession, data: dict):
        entity = Resource(**data)
        session.add(entity)
        await session.flush()
        return entity
```

### 8.3 Service

```python
from src.application.common.context import transaction

class ResourceService:
    def __init__(self, repo: ResourceRepository, audit_repo: AuditRepository = None):
        self.repo = repo
        self.audit_repo = audit_repo

    @transaction
    async def create(self, request: CreateRequest, session: AsyncSession):
        entity = await self.repo.create(session, request.dict())
        if self.audit_repo:
            await self.audit_repo.log(session, action="create", target_id=entity.id)
        return ResourceDTO.from_entity(entity)
```

### 8.4 Dependencies (SSOT)

```python
from fastapi import Depends

async def get_resource_repository() -> ResourceRepository:
    return ResourceRepository()

async def get_audit_repository() -> AuditRepository:
    return AuditRepository()

async def get_resource_service(
    repo = Depends(get_resource_repository),
    audit_repo = Depends(get_audit_repository),
) -> ResourceService:
    return ResourceService(repo=repo, audit_repo=audit_repo)
```

---

## 9. Do / Don't 요약

### Interface (Router)

| DO | DON'T |
|----|-------|
| Pydantic 검증 | 세션 직접 생성 |
| `Depends()` 서비스 주입 | 비즈니스 로직 구현 |
| `ResponseData[T]` 반환 | ORM 직접 반환 |

### Domain (Service/Repository)

| DO | DON'T |
|----|-------|
| `@transaction` 사용 | HTTPException 직접 raise |
| session 파라미터 전달 | Repository에서 commit |
| DTO 반환 | FastAPI 의존성 import |

### Adapters

| DO | DON'T |
|----|-------|
| IO 캡슐화 | 비즈니스 규칙 |
| timeout/재시도 | FastAPI 타입 사용 |

---

## 10. 시나리오별 가이드

### 10.1 새 도메인 추가

1. `domain/{feature}/` 디렉토리 생성
2. `{feature}_dto.py` - DTO 정의
3. `{feature}_repository.py` - Repository (session 파라미터)
4. `{feature}_service.py` - Service (@transaction)
5. `dependencies/service.py` - DI 팩토리 추가
6. `routers/{feature}_router.py` - 라우터
7. `dispatch.py` - 라우터 등록
8. `tests/` - 테스트 작성

### 10.2 기존 서비스 수정

1. 영향 범위 파악 (import 의존성)
2. DTO 계약 변경 여부 확인
3. 기존 테스트 실행 (회귀)
4. 수정 후 테스트 추가

### 10.3 SSOT 중복 제거

1. 중복 정의 위치 파악 (`grep -r "def function_name"`)
2. SSOT 위치 결정
3. 다른 파일에서 import로 대체
4. `__all__` export 확인

---

## 11. 프로젝트 참조 경로

### 세션/트랜잭션 계약 적용 파일

- `src/application/common/context.py` - `@transaction` 정의
- `src/application/domain/permission/permission_repository.py`
- `src/application/domain/permission/permission_service.py`
- `src/application/domain/user/user_service.py`

### SSOT 적용 파일

- `src/application/interface/api/dependencies/service.py` - Repository/Service DI
- `src/application/common/constants.py` - `SUPPORTED_OAUTH_PROVIDERS`
- `src/settings/exceptions.py` - `ErrorCodes`

---

## 12. 커밋 컨벤션

```
<type>(<scope>): <subject>

예시:
refactor(domain): 다중 Repository 주입 및 세션 관리 통일
feat(interface): 새 리소스 API 추가
fix(service): 권한 검증 로직 수정
```

**Type**: `refactor`, `feat`, `fix`, `test`, `docs`, `chore`
**Scope**: `interface`, `domain`, `adapters`, `common`, `settings`

---

## 13. 주의사항

### 금지 사항

| 항목 | 이유 | 해결책 |
|------|------|--------|
| Router 비즈니스 로직 | 테스트 불가 | Service로 이동 |
| Service dict 반환 | 계약 불명확 | DTO 사용 |
| Repository commit | 트랜잭션 분산 | 상위에서 처리 |
| 중복 DI 정의 | SSOT 위반 | 중앙화 |
| 민감정보 로깅 | 보안 위협 | 마스킹/제외 |

### 자주 깨지는 지점

- **중첩 세션**: Service→Service 호출 시 각각 새 세션 생성 → 원자성 깨짐
- **Detached ORM**: commit 후 ORM 접근 시 오류 → DTO 변환 시점 고정
- **flush 의존**: 생성 직후 ID 필요 시 flush 정책 확인
