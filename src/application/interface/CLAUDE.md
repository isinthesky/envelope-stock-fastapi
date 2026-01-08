# CLAUDE.md - interface 레이어 가이드

> **인바운드 어댑터 계층**: HTTP/WS 진입점과 관리자 페이지 라우터를 제공

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
| `api/order_router.py` | `/api/v1/orders` | 주문 생성/취소/조회 | `OrderService` 사용 |
| `api/strategy_router.py` | `/api/v1/strategies` | 전략 CRUD/스캔 | `StrategyService` 사용 |
| `api/backtest_router.py` | **내부 prefix 포함** | 백테스트 실행/검증 | `APIRouter(prefix="/api/v1/backtest")` |
| `api/websocket_router.py` | `/ws` | 실시간 WebSocket | `websocket_manager` 사용 |

> `backtest_router`는 내부에서 prefix를 선언하므로 `main.py`에서 추가 prefix를 주지 않습니다.

---

## 🖥️ Page 라우터
- `page/*_page_router.py`는 `/page` 이하 대시보드 라우팅을 담당합니다.
- 모두 `include_in_schema=False`로 OpenAPI에 노출하지 않습니다.
- 템플릿은 `templates/page/*.html`를 사용합니다.

---

## ✅ 구현 규칙
- **응답 포맷**: 기본적으로 `ResponseDTO.success_response` 사용
  - `backtest_router`는 레거시 경로로 DTO를 직접 반환
- **의존성 주입**: `application.common.dependencies`의 Alias만 사용
- **비즈니스 로직 금지**: 라우터는 서비스 호출만 수행
- **WebSocket 정리**: 연결 종료 시 반드시 `disconnect` 및 구독 해제

---

## 🔗 관련 문서
- `src/application/CLAUDE.md`
- `src/application/domain/CLAUDE.md`
