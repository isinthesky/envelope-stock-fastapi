# 증권 자동매매 API 서버 서비스 구현 가이드

> **증권 자동매매 서비스**의 도메인별 구현 규칙 및 개발 가이드

## 📋 프로젝트 개요

### 서비스 정보
- **서비스명**: KIS Trading API Service
- **포트**: 8000 (개발), 8080 (운영)
- **역할**: 한국투자증권 Open API 기반 자동매매 서비스
- **기술스택**: FastAPI, PostgreSQL, SQLAlchemy(async), Redis, WebSocket, UV

### 주요 기능
- ✅ **다중 상품 거래** - 국내/해외 주식, 선물옵션, 채권, ETF 등
- ✅ **실시간 시세** - WebSocket 기반 실시간 호가/체결 정보
- ✅ **자동매매 전략** - 조건 기반 자동 주문 실행
- ✅ **계좌 관리** - 잔고, 포지션, 손익 분석
- ✅ **리스크 관리** - 손실 제한, 포지션 관리
- ✅ **대시보드** - 실시간 모니터링 및 관리

---

## 🏛️ 아키텍처 개요

### 헥사고날 아키텍처 + 현대적 패턴

```
📁 src/
├── 🔌 adapters/           # 외부 시스템 연동
│   ├── database/          # Repository + Models
│   ├── external/          # KIS API + WebSocket
│   └── cache/             # Redis 캐시
├── 🏢 application/        # 애플리케이션 로직
│   ├── common/            # 공통 유틸리티와 패턴
│   │   ├── base_repository.py    # BaseRepository 패턴
│   │   ├── dependencies.py       # 통합 의존성 관리
│   │   └── context.py            # @transaction 등
│   ├── domain/            # 도메인별 서비스 + DTO
│   │   ├── auth/          # 인증 관리
│   │   ├── order/         # 주문 처리
│   │   ├── account/       # 계좌 관리
│   │   ├── market_data/   # 시세 관리
│   │   ├── strategy/      # 전략 실행
│   │   └── websocket/     # 실시간 데이터
│   └── interface/         # API + WebSocket 라우터
└── ⚙️  settings/           # 환경 설정

📁 templates/              # Jinja2 템플릿 (대시보드)
📁 static/                 # 정적 파일 (CSS/JS)
```

### 핵심 아키텍처 패턴
- **BaseRepository Pattern**: Mixin 기반 중복 제거 (40% 코드 감소)
- **통합 Service Pattern**: 복잡한 비즈니스 로직을 Service에서 통합 처리
- **@transaction 데코레이터**: 외부 호출 메서드만 적용, 내부 헬퍼는 분리
- **Session 관리 단순화**: Service layer만 session 관리
- **KIS API Client 분리**: 인증/API/WebSocket 계층 분리
- **Event-Driven**: 시세 변동, 체결 알림 등 이벤트 기반 처리
- **Async/Await**: 비동기 처리로 동시성 향상
- **Connection Pooling**: HTTP/WebSocket 연결 재사용

---

## 🎯 도메인별 구현 가이드

### 1. Auth Domain (인증 관리)

#### 핵심 기능
- OAuth2 기반 토큰 발급 및 갱신
- 실전/모의 환경 전환
- 토큰 자동 갱신 (24시간 유효)

#### Service 구현 패턴
```python
from adapters.external.kis_api import KISAPIClient
from application.common.decorators import transaction

class AuthService:
    def __init__(self, kis_client: KISAPIClient):
        self.kis_client = kis_client

    @transaction
    async def get_access_token(self, app_key: str, app_secret: str) -> str:
        """접근 토큰 발급"""
        token = await self.kis_client.get_token(app_key, app_secret)
        # Redis에 토큰 캐싱 (24시간)
        await self.cache_token(token)
        return token

    async def auto_refresh_token(self):
        """토큰 자동 갱신 (백그라운드 작업)"""
        # 만료 1시간 전 자동 갱신
        pass
```

#### API 엔드포인트
- `POST /api/v1/auth/token` - 토큰 발급
- `POST /api/v1/auth/refresh` - 토큰 갱신
- `PUT /api/v1/auth/environment` - 환경 전환 (실전/모의)

---

### 2. Order Domain (주문 처리)

#### 핵심 기능
- 매수/매도 주문 생성
- 주문 정정/취소
- 체결 상태 추적
- 주문 내역 조회

#### Service 구현 패턴
```python
class OrderService:
    def __init__(
        self,
        order_repo: OrderRepository,
        account_repo: AccountRepository,
        kis_client: KISAPIClient
    ):
        self.order_repo = order_repo
        self.account_repo = account_repo
        self.kis_client = kis_client

    @transaction
    async def create_order(
        self,
        account_id: str,
        symbol: str,
        order_type: str,  # "buy" or "sell"
        quantity: int,
        price: Optional[int] = None  # None = 시장가
    ) -> Order:
        """주문 생성 및 KIS API 전송"""
        # 1. 계좌 잔고 확인
        account = await self.account_repo.get_by_id(account_id)

        # 2. 주문 가능 여부 검증
        await self._validate_order(account, symbol, quantity, price)

        # 3. KIS API 주문 전송
        kis_order_result = await self.kis_client.place_order(
            account_no=account.account_no,
            symbol=symbol,
            order_type=order_type,
            quantity=quantity,
            price=price
        )

        # 4. DB에 주문 저장
        order = Order(
            account_id=account_id,
            symbol=symbol,
            order_type=order_type,
            quantity=quantity,
            price=price,
            order_no=kis_order_result["order_no"],
            status="pending"
        )
        await self.order_repo.create(order)

        return order

    async def _validate_order(self, account, symbol, quantity, price):
        """주문 가능 여부 검증"""
        # 매수력, 리스크 제한 등 검증
        pass
```

#### API 엔드포인트
- `POST /api/v1/orders` - 주문 생성
- `PUT /api/v1/orders/{id}/modify` - 주문 정정
- `DELETE /api/v1/orders/{id}/cancel` - 주문 취소
- `GET /api/v1/orders/{id}` - 주문 조회
- `GET /api/v1/orders` - 주문 목록 조회

---

### 3. Account Domain (계좌 관리)

#### 핵심 기능
- 계좌 잔고 조회
- 보유 포지션 관리
- 손익 분석
- 거래 내역 조회

#### Service 구현 패턴
```python
class AccountService:
    def __init__(
        self,
        account_repo: AccountRepository,
        position_repo: PositionRepository,
        kis_client: KISAPIClient,
        cache: RedisCache
    ):
        self.account_repo = account_repo
        self.position_repo = position_repo
        self.kis_client = kis_client
        self.cache = cache

    @transaction
    async def get_balance(self, account_id: str) -> AccountBalance:
        """계좌 잔고 조회 (캐싱)"""
        # 1. Redis 캐시 확인
        cached = await self.cache.get(f"balance:{account_id}")
        if cached:
            return AccountBalance(**cached)

        # 2. KIS API 조회
        account = await self.account_repo.get_by_id(account_id)
        kis_balance = await self.kis_client.get_balance(account.account_no)

        # 3. Redis에 캐싱 (30초 TTL)
        await self.cache.set(
            f"balance:{account_id}",
            kis_balance,
            ttl=30
        )

        return AccountBalance(**kis_balance)

    @transaction
    async def get_positions(self, account_id: str) -> List[Position]:
        """보유 포지션 조회"""
        positions = await self.position_repo.get_by_account(account_id)

        # 현재가 조회 및 평가손익 계산
        for position in positions:
            current_price = await self._get_current_price(position.symbol)
            position.calculate_pnl(current_price)

        return positions
```

#### API 엔드포인트
- `GET /api/v1/accounts/{id}/balance` - 잔고 조회
- `GET /api/v1/accounts/{id}/positions` - 포지션 조회
- `GET /api/v1/accounts/{id}/pnl` - 손익 분석
- `GET /api/v1/accounts/{id}/transactions` - 거래 내역

---

### 4. MarketData Domain (시세 관리)

#### 핵심 기능
- 현재가 조회
- 호가 정보 조회
- 차트 데이터 조회
- 시세 캐싱

#### Service 구현 패턴
```python
class MarketDataService:
    def __init__(
        self,
        kis_client: KISAPIClient,
        cache: RedisCache
    ):
        self.kis_client = kis_client
        self.cache = cache

    async def get_current_price(self, symbol: str) -> MarketPrice:
        """현재가 조회 (캐싱)"""
        # 1. Redis 캐시 확인 (5초 TTL)
        cached = await self.cache.get(f"price:{symbol}")
        if cached:
            return MarketPrice(**cached)

        # 2. KIS API 조회
        kis_price = await self.kis_client.get_price(symbol)

        # 3. Redis에 캐싱
        await self.cache.set(f"price:{symbol}", kis_price, ttl=5)

        return MarketPrice(**kis_price)

    async def get_orderbook(self, symbol: str) -> OrderBook:
        """호가 정보 조회"""
        kis_orderbook = await self.kis_client.get_orderbook(symbol)
        return OrderBook(**kis_orderbook)
```

#### API 엔드포인트
- `GET /api/v1/market/price/{symbol}` - 현재가 조회
- `GET /api/v1/market/orderbook/{symbol}` - 호가 조회
- `GET /api/v1/market/chart/{symbol}` - 차트 데이터

---

### 5. Strategy Domain (전략 실행)

#### 핵심 기능
- 자동매매 전략 생성
- 조건 검증 및 실행
- 전략 상태 관리
- 리스크 관리

#### Service 구현 패턴
```python
class StrategyService:
    def __init__(
        self,
        strategy_repo: StrategyRepository,
        order_service: OrderService,
        market_data_service: MarketDataService
    ):
        self.strategy_repo = strategy_repo
        self.order_service = order_service
        self.market_data_service = market_data_service

    @transaction
    async def execute_strategy(self, strategy_id: str):
        """전략 실행"""
        strategy = await self.strategy_repo.get_by_id(strategy_id)

        # 1. 조건 검증
        if await self._check_conditions(strategy):
            # 2. 주문 실행
            order = await self.order_service.create_order(
                account_id=strategy.account_id,
                symbol=strategy.symbol,
                order_type=strategy.order_type,
                quantity=strategy.quantity,
                price=strategy.price
            )

            # 3. 전략 상태 업데이트
            strategy.last_executed_at = datetime.now()
            strategy.status = "executed"
            await self.strategy_repo.update(strategy)

    async def _check_conditions(self, strategy: Strategy) -> bool:
        """전략 조건 검증"""
        # 가격 조건, 기술적 지표 등 검증
        current_price = await self.market_data_service.get_current_price(
            strategy.symbol
        )

        # 조건 로직 실행
        return self._evaluate_conditions(strategy, current_price)
```

#### API 엔드포인트
- `POST /api/v1/strategies` - 전략 생성
- `POST /api/v1/strategies/{id}/execute` - 전략 실행
- `GET /api/v1/strategies/{id}` - 전략 조회
- `PUT /api/v1/strategies/{id}` - 전략 수정
- `DELETE /api/v1/strategies/{id}` - 전략 삭제

---

### 6. WebSocket Domain (실시간 데이터)

#### 핵심 기능
- 실시간 시세 수신
- 실시간 체결 알림
- 이벤트 핸들링
- 구독 관리

#### Service 구현 패턴
```python
class WebSocketService:
    def __init__(self, kis_ws_client: KISWebSocketClient):
        self.kis_ws_client = kis_ws_client
        self.subscribers = {}

    async def connect(self):
        """WebSocket 연결"""
        await self.kis_ws_client.connect()

    async def subscribe_price(self, symbol: str, callback):
        """실시간 시세 구독"""
        if symbol not in self.subscribers:
            self.subscribers[symbol] = []

        self.subscribers[symbol].append(callback)

        # KIS WebSocket 구독 요청
        await self.kis_ws_client.subscribe({
            "tr_id": "H0STCNT0",  # 실시간 체결가
            "tr_key": symbol
        })

    async def handle_message(self, message: dict):
        """수신 메시지 처리"""
        symbol = message.get("tr_key")
        data = message.get("data")

        # 구독자들에게 데이터 전달
        if symbol in self.subscribers:
            for callback in self.subscribers[symbol]:
                await callback(data)
```

#### WebSocket 엔드포인트
- `WS /ws/connect` - WebSocket 연결
- `WS /ws/subscribe` - 종목 구독
- `WS /ws/unsubscribe` - 구독 해제

---

## 🛠️ 개발 환경

### 환경 설정
```bash
# 프로젝트 초기화
uv sync

# 개발 서버 실행
uvicorn src.main:app --reload --port 8000

# 데이터베이스
alembic upgrade head
alembic revision --autogenerate -m "description"

# 테스트 및 코드 품질
pytest
mypy src/
black src/
isort src/
```

### 환경 변수 (.env)
```env
# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/kis_trading

# Redis
REDIS_URL=redis://localhost:6379/0

# KIS API (실전투자)
KIS_APP_KEY=your_app_key
KIS_APP_SECRET=your_app_secret
KIS_ACCOUNT_NO=12345678
KIS_PRODUCT_CODE=01

# KIS API (모의투자)
KIS_PAPER_APP_KEY=your_paper_app_key
KIS_PAPER_APP_SECRET=your_paper_app_secret
KIS_PAPER_ACCOUNT_NO=11111111

# Security
SECRET_KEY=your-secret-key-here
API_KEY_SALT=your-api-key-salt
```

---

## 🔧 핵심 구현 규칙

### 1. Service Layer 규칙

**✅ DO:**
- Service는 비즈니스 로직만 처리
- 여러 Repository를 주입받아 복잡한 로직 통합
- @transaction 데코레이터로 트랜잭션 관리
- 외부 API 호출은 Adapter를 통해서만

**❌ DON'T:**
- Service에서 직접 HTTP 요청 금지
- Service 간 직접 호출 최소화 (의존성 주입 활용)
- 복잡한 비즈니스 로직을 Router에 작성 금지

### 2. Repository Layer 규칙

**BaseRepository 활용:**
```python
class OrderRepository(BaseRepository[Order]):
    async def get_by_status(self, status: str) -> List[Order]:
        """상태별 주문 조회"""
        query = select(Order).where(Order.status == status)
        result = await self.session.execute(query)
        return result.scalars().all()
```

**Mixin 활용:**
```python
class SearchableMixin:
    async def search(self, keyword: str):
        # 검색 로직
        pass

class OrderRepository(BaseRepository[Order], SearchableMixin):
    # 자동으로 search 메서드 상속
    pass
```

### 3. Router Layer 규칙

**의존성 주입 패턴:**
```python
from application.common.dependencies import get_order_service

@router.post("/orders")
async def create_order(
    order_data: OrderCreate,
    order_service: Annotated[OrderService, Depends(get_order_service)]
):
    """주문 생성"""
    order = await order_service.create_order(**order_data.dict())
    return OrderResponse.from_orm(order)
```

### 4. DTO 규칙

**요청/응답 DTO 분리:**
```python
# Request DTO
class OrderCreate(BaseModel):
    account_id: str
    symbol: str
    order_type: Literal["buy", "sell"]
    quantity: int
    price: Optional[int] = None

# Response DTO
class OrderResponse(BaseModel):
    id: str
    account_id: str
    symbol: str
    order_type: str
    quantity: int
    price: Optional[int]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
```

### 5. 에러 처리 규칙

**계층별 에러 처리:**
```python
# Service Layer
class OrderService:
    async def create_order(self, ...):
        try:
            # KIS API 호출
            result = await self.kis_client.place_order(...)
        except KISAPIError as e:
            # KIS API 에러 → 도메인 에러로 변환
            raise OrderCreationError(f"주문 실패: {e.message}")

# Router Layer
@router.post("/orders")
async def create_order(...):
    try:
        order = await order_service.create_order(...)
        return order
    except OrderCreationError as e:
        # 도메인 에러 → HTTP 에러로 변환
        raise HTTPException(status_code=400, detail=str(e))
```

---

## 📊 성능 최적화 전략

### 1. 캐싱 전략
- **시세 데이터**: Redis 5초 TTL
- **계좌 정보**: Redis 30초 TTL
- **토큰 정보**: Redis 24시간 TTL

### 2. Connection Pooling
- **HTTP**: aiohttp ClientSession 재사용
- **WebSocket**: 연결 풀링 및 재연결 로직
- **Database**: SQLAlchemy async pool (pool_size=20)

### 3. 비동기 처리
- **동시 요청**: asyncio.gather로 병렬 처리
- **백그라운드 작업**: BackgroundTasks 활용
- **스트리밍**: Server-Sent Events (SSE) 활용

---

## 🔒 보안 및 리스크 관리

### 보안 규칙
- API 키는 환경 변수로만 관리
- 토큰은 Redis에 암호화 저장
- WebSocket 연결 시 approval_key 검증
- Rate Limiting 적용 (분당 20회)

### 리스크 관리
- 일일 손실 제한 (계좌별 설정)
- 최대 보유 종목 수 제한
- 주문 금액 한도 설정
- 긴급 정지 기능 (전체 주문 취소)

---

## 📚 테스트 전략

### 단위 테스트
```python
import pytest
from application.domain.order.order_service import OrderService

@pytest.mark.asyncio
async def test_create_order(mock_order_repo, mock_kis_client):
    service = OrderService(mock_order_repo, mock_kis_client)

    order = await service.create_order(
        account_id="test",
        symbol="005930",
        order_type="buy",
        quantity=10,
        price=70000
    )

    assert order.status == "pending"
```

### 통합 테스트
```python
@pytest.mark.asyncio
async def test_order_flow(client):
    # 1. 주문 생성
    response = await client.post("/api/v1/orders", json={...})
    assert response.status_code == 200

    # 2. 주문 조회
    order_id = response.json()["id"]
    response = await client.get(f"/api/v1/orders/{order_id}")
    assert response.status_code == 200
```

---

## 🎯 다음 개발 단계

### 우선순위 높음
- [ ] 기본 아키텍처 구현 (Adapter, Service, Repository)
- [ ] Auth Domain 구현 (토큰 발급/갱신)
- [ ] Order Domain 구현 (주문 생성/조회)
- [ ] Account Domain 구현 (잔고/포지션 조회)
- [ ] MarketData Domain 구현 (시세 조회)

### 우선순위 중간
- [ ] Strategy Domain 구현 (자동매매 전략)
- [ ] WebSocket Domain 구현 (실시간 시세)
- [ ] 대시보드 페이지 구현
- [ ] 리스크 관리 기능

### 우선순위 낮음
- [ ] 백테스팅 기능
- [ ] 알림 시스템 (Telegram, Email)
- [ ] 다중 계좌 지원
- [ ] AI 기반 전략 추천

---

## 📞 참고 문서

- [FastAPI 공식 문서](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0 Async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [한국투자증권 Open API](https://apiportal.koreainvestment.com/)
- [UV Package Manager](https://docs.astral.sh/uv/)

---

**💡 중요**: 이 서비스는 **금융 자동매매**를 위한 시스템으로, **안정성과 정확성**이 최우선입니다. 모든 주문은 **충분한 테스트** 후 실행하며, **리스크 관리** 규칙을 반드시 준수해야 합니다. 실전 투자 전 **모의투자 환경**에서 충분히 검증하시기 바랍니다.
