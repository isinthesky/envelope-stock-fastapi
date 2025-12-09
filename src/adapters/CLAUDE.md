# CLAUDE.md - adapters 디렉토리 가이드

> **Adapter 계층 (Infrastructure)**: 외부 시스템과의 연동을 담당하는 인프라스트럭처 계층

## 📁 디렉토리 역할

`adapters/` 디렉토리는 **헥사고날 아키텍처의 Adapter 계층**을 구현합니다. Database, Cache, 외부 API 등 모든 외부 시스템과의 연동을 담당합니다.

---

## 📂 디렉토리 구조

```
adapters/
├── __init__.py
│
├── database/               # 🗄️ PostgreSQL + SQLAlchemy
│   ├── __init__.py
│   ├── connection.py       # DB 연결 및 세션 관리
│   ├── models/             # SQLAlchemy ORM 모델
│   │   ├── __init__.py
│   │   ├── base.py         # BaseModel, Mixin 클래스
│   │   ├── account.py      # 계좌 모델
│   │   ├── order.py        # 주문 모델
│   │   ├── position.py     # 포지션 모델
│   │   ├── strategy.py     # 전략 모델
│   │   └── ohlcv.py        # OHLCV 캔들 캐시 모델
│   └── repositories/       # Repository 패턴 구현
│       ├── __init__.py
│       ├── base_repository.py    # BaseRepository + Mixin
│       ├── order_repository.py   # 주문 Repository
│       ├── strategy_repository.py # 전략 Repository
│       └── ohlcv_repository.py   # OHLCV 캐시 Repository
│
├── cache/                  # 🔴 Redis 캐시
│   ├── __init__.py
│   └── redis_client.py     # Redis 클라이언트
│
└── external/               # 🌐 외부 API 연동
    ├── __init__.py
    ├── kis_api/            # KIS Open API 클라이언트
    │   ├── __init__.py
    │   ├── auth.py         # 토큰 인증 관리
    │   ├── client.py       # REST API 클라이언트
    │   └── exceptions.py   # KIS API 예외 정의
    └── websocket/          # WebSocket 연결 관리
        ├── __init__.py
        ├── kis_websocket.py      # KIS WebSocket 클라이언트
        └── websocket_manager.py  # 연결 풀 관리
```

---

## 🗄️ database/ - 데이터베이스 연동

### connection.py - DB 연결 관리

```python
# 핵심 구성요소
Base                    # SQLAlchemy DeclarativeBase
engine                  # AsyncEngine 인스턴스
AsyncSessionLocal       # 세션 팩토리

# 사용 예시
async with AsyncSessionLocal() as session:
    # DB 작업 수행
    pass
```

### models/base.py - 공통 모델 Mixin

| Mixin | 역할 | 제공 필드 |
|-------|------|----------|
| `TimestampMixin` | 생성/수정 시각 | `created_at`, `updated_at` |
| `SoftDeleteMixin` | 소프트 삭제 | `deleted_at`, `is_deleted` |
| `BaseModel` | 기본 모델 클래스 | `to_dict()`, `__repr__()` |

### models/ohlcv.py - OHLCV 캐시 모델

```python
class OHLCVModel(Base, BaseModel):
    """OHLCV 캔들 데이터 캐시 모델"""
    __tablename__ = "ohlcv_cache"
    
    id: Mapped[int]           # PK
    symbol: Mapped[str]       # 종목코드
    timestamp: Mapped[datetime]  # 캔들 시각
    interval: Mapped[str]     # 시간 간격 (1d, 1w, 1m)
    open: Mapped[Decimal]     # 시가
    high: Mapped[Decimal]     # 고가
    low: Mapped[Decimal]      # 저가
    close: Mapped[Decimal]    # 종가
    volume: Mapped[int]       # 거래량
    
    # Properties
    @property
    def is_bullish(self) -> bool   # 상승 캔들 여부
    @property
    def is_bearish(self) -> bool   # 하락 캔들 여부
```

### repositories/base_repository.py - 기본 Repository

```python
class BaseRepository(Generic[ModelType]):
    """모든 Repository의 기본 CRUD 기능 제공"""
    
    # Create
    async def create(**kwargs) -> ModelType
    async def create_many(items: list[dict]) -> list[ModelType]
    
    # Read
    async def get_by_id(id: int) -> ModelType | None
    async def get_one(**filters) -> ModelType | None
    async def get_many(limit, offset, **filters) -> Sequence[ModelType]
    
    # Update
    async def update_by_id(id: int, **kwargs) -> ModelType | None
    async def update_many(filters, **kwargs) -> int
    
    # Delete
    async def delete_by_id(id: int) -> bool
    async def delete_many(**filters) -> int
    
    # Utils
    async def count(**filters) -> int
    async def exists(**filters) -> bool
```

### Mixin 클래스

| Mixin | 메서드 | 설명 |
|-------|--------|------|
| `SearchableMixin` | `search(query_stmt)` | 커스텀 쿼리 실행 |
| `PaginationMixin` | `paginate(page, page_size)` | 페이지네이션 |
| `StatsMixin` | `aggregate(column, func_name)` | 집계 함수 |

---

## 🔴 cache/ - Redis 캐시

### redis_client.py - Redis 클라이언트

```python
class RedisClient:
    """Redis 비동기 클라이언트"""
    
    # 연결 관리
    async def connect() -> None
    async def disconnect() -> None
    async def ping() -> bool
    
    # 기본 CRUD
    async def set(key, value, ttl=None) -> bool
    async def get(key) -> Any | None
    async def delete(key) -> bool
    async def exists(key) -> bool
    
    # TTL 관리
    async def expire(key, ttl) -> bool
    async def ttl(key) -> int
    
    # 패턴 검색
    async def keys(pattern) -> list[str]
    async def delete_pattern(pattern) -> int
    
    # Hash 연산
    async def hset(name, key, value) -> bool
    async def hget(name, key) -> Any | None
    async def hgetall(name) -> dict
    
    # 도메인별 헬퍼
    async def cache_market_data(symbol, data) -> bool  # TTL: 5초
    async def get_market_data(symbol) -> dict | None
    async def cache_account_data(account_no, data) -> bool  # TTL: 30초
    async def get_account_data(account_no) -> dict | None
```

---

## 🌐 external/ - 외부 API 연동

### kis_api/client.py - KIS REST API 클라이언트

```python
class KISAPIClient:
    """KIS Open API REST 클라이언트"""
    
    # HTTP 메서드 (자동 재시도, Rate Limiting 적용)
    async def get(path, params=None, headers=None) -> dict
    async def post(path, json=None, headers=None) -> dict
    
    # 주문용 Hash Key 발급
    async def get_hashkey(json_data) -> str
    
    # 특징
    # - @retry 데코레이터로 자동 재시도 (최대 3회)
    # - Semaphore로 Rate Limiting (분당 20회)
    # - KIS API 응답 코드 자동 검증
```

### kis_api/auth.py - 토큰 인증 관리

```python
class KISAuth:
    """KIS API 토큰 인증 관리"""
    
    async def get_access_token() -> str
    async def get_auth_headers() -> dict[str, str]
    async def refresh_token() -> str
    
    # 토큰 자동 갱신
    # - 24시간 유효
    # - 만료 1시간 전 자동 갱신
```

### kis_api/exceptions.py - 예외 정의

| 예외 클래스 | 설명 |
|-------------|------|
| `KISAPIError` | 기본 API 에러 |
| `KISAuthError` | 인증 실패 (401) |
| `KISRateLimitError` | Rate Limit 초과 (429) |

---

## 🔗 계층 간 의존성

```
┌─────────────────────────────────────────────────┐
│              Domain Layer (Service)              │
│         - BacktestService                        │
│         - MarketDataService                      │
└─────────────────────┬───────────────────────────┘
                      │ 사용
                      ▼
┌─────────────────────────────────────────────────┐
│              Adapter Layer                       │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────┐ │
│  │  Repository  │ │ RedisClient  │ │ KISClient│ │
│  │  (Database)  │ │   (Cache)    │ │(External)│ │
│  └──────────────┘ └──────────────┘ └──────────┘ │
└─────────────────────────────────────────────────┘
```

---

## 🛠️ 개발 가이드

### 새 Repository 추가

```python
# adapters/database/repositories/my_repository.py

from src.adapters.database.repositories.base_repository import (
    BaseRepository,
    PaginationMixin,
)
from src.adapters.database.models.my_model import MyModel

class MyRepository(BaseRepository[MyModel], PaginationMixin):
    """My Repository"""
    
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(MyModel, session)
    
    # 커스텀 메서드 추가
    async def find_by_custom_field(self, value: str) -> MyModel | None:
        return await self.get_one(custom_field=value)
```

### 새 외부 API 클라이언트 추가

```python
# adapters/external/my_api/client.py

class MyAPIClient:
    def __init__(self):
        self.base_url = settings.my_api_url
    
    async def get_data(self, param: str) -> dict:
        # API 호출 로직
        pass
```

---

## 🔗 관련 문서

- [아키텍처 문서](../../docs/base/ARCHITECTURE.md)
- [서비스 구현 가이드](../../docs/base/SERVICE.md)
- [설정 가이드](../settings/CLAUDE.md)

---

**💡 핵심**: Adapter 계층은 **외부 시스템과의 연동만** 담당하며, 비즈니스 로직은 포함하지 않습니다.
