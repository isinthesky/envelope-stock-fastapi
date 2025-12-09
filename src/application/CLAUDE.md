# CLAUDE.md - application 디렉토리 가이드

> **Application 계층**: 비즈니스 로직과 API 인터페이스를 담당하는 핵심 계층

## 📁 디렉토리 역할

`application/` 디렉토리는 **헥사고날 아키텍처의 Application 계층**을 구현합니다. Interface(API), Domain(비즈니스 로직), Common(공통 유틸리티)으로 구성됩니다.

---

## 📂 디렉토리 구조

```
application/
├── __init__.py
│
├── interface/              # 🌐 API Router (Presentation Layer)
│   ├── __init__.py
│   ├── auth_router.py      # 인증 API
│   ├── market_data_router.py  # 시세 API
│   ├── account_router.py   # 계좌 API
│   ├── order_router.py     # 주문 API
│   ├── strategy_router.py  # 전략 API
│   ├── backtest_router.py  # 백테스팅 API
│   └── websocket_router.py # WebSocket API
│
├── domain/                 # 💼 도메인 서비스 (Business Logic)
│   ├── __init__.py
│   ├── auth/               # 인증 도메인
│   ├── market_data/        # 시세 데이터 도메인
│   ├── account/            # 계좌 도메인
│   ├── order/              # 주문 도메인
│   ├── strategy/           # 전략 도메인
│   ├── backtest/           # 백테스팅 도메인
│   └── websocket_domain/   # WebSocket 도메인
│
└── common/                 # 🔧 공통 유틸리티
    ├── __init__.py
    ├── dto.py              # 공통 DTO 클래스
    ├── decorators.py       # @transaction, @cache 등
    ├── dependencies.py     # FastAPI 의존성 주입
    ├── validators.py       # 공통 검증 함수
    ├── formatters.py       # 데이터 포맷터
    ├── exceptions.py       # 커스텀 예외 정의
    ├── indicators.py       # 기술적 지표 계산
    ├── performance_metrics.py  # 성과 지표 계산
    └── background_tasks.py # 백그라운드 태스크
```

---

## 🌐 interface/ - API Router

### Router 구조

각 Router는 다음 패턴을 따릅니다:

```python
# application/interface/{domain}_router.py

from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/api/v1/{domain}", tags=["{Domain}"])

# 의존성 주입
def get_{domain}_service(...) -> {Domain}Service:
    return {Domain}Service(...)

# 엔드포인트
@router.get("/")
async def get_items(service = Depends(get_{domain}_service)):
    return await service.get_items()

@router.post("/")
async def create_item(request: RequestDTO, service = Depends(get_{domain}_service)):
    return await service.create(request)
```

### 구현된 Router

| Router | 경로 | 주요 엔드포인트 |
|--------|------|----------------|
| `auth_router` | `/api/v1/auth` | 토큰 발급, 갱신 |
| `market_data_router` | `/api/v1/market` | 현재가, 호가, 차트 |
| `account_router` | `/api/v1/account` | 잔고, 포지션 |
| `order_router` | `/api/v1/order` | 주문 생성/조회/취소 |
| `strategy_router` | `/api/v1/strategy` | 전략 CRUD |
| `backtest_router` | `/api/v1/backtest` | 백테스팅 실행 |
| `websocket_router` | `/ws` | 실시간 시세 |

---

## 💼 domain/ - 비즈니스 로직

### 도메인 구조

각 도메인은 다음 파일로 구성됩니다:

```
domain/{domain_name}/
├── __init__.py
├── dto.py          # Request/Response DTO
└── service.py      # 비즈니스 로직
```

### 구현된 도메인

#### 1. market_data/ - 시세 데이터

```python
class MarketDataService:
    """시세 데이터 서비스"""
    
    async def get_current_price(symbol: str) -> PriceResponseDTO
    async def get_orderbook(symbol: str) -> OrderbookResponseDTO
    async def get_chart_data(symbol, interval, start_date, end_date) -> ChartResponseDTO
```

#### 2. backtest/ - 백테스팅

```python
# 파일 구조
backtest/
├── dto.py              # BacktestRequestDTO, BacktestResultDTO
├── service.py          # BacktestService
├── engine.py           # BacktestEngine (시뮬레이션 엔진)
├── data_loader.py      # BacktestDataLoader (데이터 로드)
├── position_manager.py # 포지션 관리
└── order_manager.py    # 주문 관리

class BacktestService:
    async def run_backtest(request: BacktestRequestDTO) -> BacktestResultDTO
    async def run_multi_symbol_backtest(request) -> MultiSymbolBacktestResultDTO
    async def validate_data_quality(symbol, start_date, end_date) -> dict
```

#### 3. strategy/ - 전략

```python
# 파일 구조
strategy/
├── dto.py        # StrategyDTO, StrategyConfigDTO
├── service.py    # StrategyService
└── engine.py     # StrategyEngine (전략 실행 엔진)
```

---

## 🔧 common/ - 공통 유틸리티

### dto.py - 공통 DTO

```python
class BaseDTO(BaseModel):
    """모든 DTO의 기본 클래스"""
    model_config = ConfigDict(from_attributes=True)

class ResponseDTO(BaseDTO, Generic[T]):
    """API 응답 DTO"""
    success: bool
    message: str | None
    data: T | None
    error: dict | None

class PaginationDTO(BaseDTO):
    """페이지네이션 요청"""
    page: int = 1
    page_size: int = 20

class PaginatedResponseDTO(BaseDTO, Generic[T]):
    """페이지네이션 응답"""
    items: list[T]
    total: int
    page: int
    total_pages: int
```

### decorators.py - 데코레이터

```python
@transaction
async def service_method(self, session, ...):
    """트랜잭션 자동 관리 (commit/rollback)"""
    pass

@cache(ttl=300, key_prefix="market")
async def get_data(symbol: str):
    """Redis 캐시 자동 적용"""
    pass

@retry(max_attempts=3, delay=1.0)
async def call_api():
    """자동 재시도"""
    pass

@log_execution
async def complex_task():
    """실행 시간 로깅"""
    pass
```

### dependencies.py - 의존성 주입

```python
# FastAPI Depends에서 사용
async def get_db_session() -> AsyncGenerator[AsyncSession, None]
async def get_redis_client() -> RedisClient
def get_kis_client() -> KISAPIClient
def get_current_user(token: str) -> User
```

### exceptions.py - 커스텀 예외

```python
class BacktestError(Exception):
    """백테스팅 실행 오류"""

class BacktestDataError(BacktestError):
    """백테스팅 데이터 오류"""

class KISAPIServiceError(Exception):
    """KIS API 서비스 오류"""
```

### indicators.py - 기술적 지표

```python
def calculate_sma(data: pd.DataFrame, period: int) -> pd.Series
def calculate_ema(data: pd.DataFrame, period: int) -> pd.Series
def calculate_rsi(data: pd.DataFrame, period: int) -> pd.Series
def calculate_macd(data: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]
def calculate_bollinger_bands(data: pd.DataFrame, period: int) -> tuple
```

### performance_metrics.py - 성과 지표

```python
def calculate_total_return(equity_curve: list) -> float
def calculate_mdd(equity_curve: list) -> float
def calculate_sharpe_ratio(returns: list, risk_free_rate: float) -> float
def calculate_sortino_ratio(returns: list) -> float
def calculate_cagr(start_value, end_value, years: float) -> float
def calculate_win_rate(trades: list) -> float
def calculate_profit_factor(trades: list) -> float
```

---

## 🔗 계층 간 의존성

```
┌─────────────────────────────────────────────────┐
│                Interface Layer                   │
│            (*_router.py)                         │
│         - HTTP 요청/응답 처리                     │
│         - 인증/권한 검사                          │
└─────────────────────┬───────────────────────────┘
                      │ 호출
                      ▼
┌─────────────────────────────────────────────────┐
│                Domain Layer                      │
│            (*/service.py)                        │
│         - 비즈니스 로직                           │
│         - 트랜잭션 관리                           │
│         - 도메인 규칙 적용                        │
└─────────────────────┬───────────────────────────┘
                      │ 사용
                      ▼
┌─────────────────────────────────────────────────┐
│            Common + Adapters                     │
│    - DTO, Decorators, Dependencies              │
│    - Repository, Cache, External API            │
└─────────────────────────────────────────────────┘
```

---

## 🛠️ 개발 가이드

### 새 도메인 추가

1. **DTO 정의** (`domain/{name}/dto.py`)
```python
class MyRequestDTO(BaseDTO):
    field1: str
    field2: int

class MyResponseDTO(BaseDTO):
    result: str
```

2. **Service 구현** (`domain/{name}/service.py`)
```python
class MyService:
    def __init__(self, repository: MyRepository, cache: RedisClient):
        self.repository = repository
        self.cache = cache
    
    async def process(self, request: MyRequestDTO) -> MyResponseDTO:
        # 비즈니스 로직
        pass
```

3. **Router 생성** (`interface/{name}_router.py`)
```python
router = APIRouter(prefix="/api/v1/my", tags=["My"])

@router.post("/process")
async def process(request: MyRequestDTO, service = Depends(get_my_service)):
    return await service.process(request)
```

4. **main.py에 등록**
```python
app.include_router(my_router)
```

---

## 🔗 관련 문서

- [아키텍처 문서](../../docs/base/ARCHITECTURE.md)
- [서비스 구현 가이드](../../docs/base/SERVICE.md)
- [Adapter 계층](../adapters/CLAUDE.md)

---

**💡 핵심**: Application 계층은 **비즈니스 로직의 중심**이며, Interface와 Adapter 사이의 중재자 역할을 합니다.
