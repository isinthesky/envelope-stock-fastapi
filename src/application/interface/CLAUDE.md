# CLAUDE.md - interface 레이어 가이드

> 인바운드 어댑터 계층: HTTP/WS 진입점과 관리자 페이지 라우터를 제공

## ✅ 역할
- REST API와 WebSocket 엔드포인트 정의
- 도메인 서비스 호출만 수행하는 얇은 라우터 유지
- 관리자 페이지(Jinja2 템플릿) 라우팅 제공

---

## 📂 구조
```
interface/
├── api/            # REST/WS 라우터
└── page/           # 대시보드 라우터(Jinja2)
```

---

## 🌐 API 라우터 맵
| 파일 | prefix | 역할 | 비고 |
| --- | --- | --- | --- |
| `api/auth_router.py` | `/api/v1/auth` | 토큰 발급/갱신/승인키 | `AuthService` 사용 |
| `api/market_data_router.py` | `/api/v1/market` | 현재가/호가/차트 | `MarketDataService` 사용 |
| `api/account_router.py` | `/api/v1/accounts` | 잔고/포지션 | `AccountService` 사용 |
| `api/order_router.py` | `/api/v1/orders` | 주문 생성/취소/조회/정정 | `OrderService` 사용 |
| `api/strategy_router.py` | `/api/v1/strategies` | 전략/유니버스/시그널/스케줄러 | `StrategyService` 사용 |
| `api/backtest_router.py` | **내부 prefix 포함** | 백테스트 실행/검증 | `APIRouter(prefix="/api/v1/backtest")` |
| `api/websocket_router.py` | `/ws` | 실시간 WebSocket | `websocket_manager` 사용 |

> `backtest_router`는 내부에서 prefix를 선언하므로 `main.py`에서 추가 prefix를 주지 않습니다.

---

## 🖥️ Page 라우터
| 파일 | prefix | 템플릿 | 설명 |
| --- | --- | --- | --- |
| `main_page_router.py` | `/page` | `page/index.html` | 대시보드 허브 |
| `auth_page_router.py` | `/page/auth` | `page/auth.html` | 인증 상태/토큰 |
| `account_page_router.py` | `/page/account` | `page/account.html` | 계좌 조회 |
| `market_data_page_router.py` | `/page/market-data` | `page/market_data.html` | 시세 조회 |
| `order_page_router.py` | `/page/order` | `page/order.html` | 주문 관리 |
| `strategy_page_router.py` | `/page/strategy` | `page/strategy.html` | 매수 전략 |
| `sell_strategy_page_router.py` | `/page/sell-strategy` | `page/sell_strategy.html` | 매도 분석 |
| `backtest_page_router.py` | `/page/backtest` | `page/backtest.html` | 백테스트 |
| `websocket_page_router.py` | `/page/websocket` | `page/websocket.html` | WebSocket 테스트 |

---

## ✅ 구현 규칙
- **응답 포맷**: 기본적으로 `ResponseDTO.success_response` 사용
  - `backtest_router`는 레거시 경로로 DTO를 직접 반환
- **의존성 주입**: `application.common.dependencies`의 Alias를 우선 사용
- **비즈니스 로직 금지**: 라우터는 서비스 호출만 수행
- **라우팅 순서**: `strategy_router`는 정적 경로를 동적 경로보다 먼저 정의
- **WebSocket 정리**: 연결 종료 시 반드시 `disconnect` 및 구독 해제

---

## 🔗 관련 문서
- `src/application/CLAUDE.md`
- `src/application/domain/CLAUDE.md`
