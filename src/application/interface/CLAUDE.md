# Interface Layer Guide (Stock API Server)

`src/application/interface`는 한국투자증권 Open API 기반 자동매매 서버의 HTTP/WS 인바운드 어댑터 계층입니다. REST 라우터와 실시간 WebSocket 진입점을 제공하며, 도메인 서비스/클라이언트에 대한 최소한의 얇은 래퍼로 유지합니다.

## 상위 구성
| 경로 | 역할 | 규칙 |
| --- | --- | --- |
| `__init__.py` | 패키지 메타/주석 위치 | 라우터 모듈명을 재노출하려면 `__all__`에 추가합니다. |
| `api/` | FastAPI 기반 REST/WS 라우터 | 버전 프리픽스는 **`main.py`에서 부여**하고, 라우터 파일 안에서는 경로만 정의합니다. |
| `page/` | Jinja 페이지 라우터 | `admin_page.py`는 도메인 API 호출을 보조하는 대시보드를 제공하며, GET 전용으로 유지합니다. |

## API 라우터 맵
| 파일 | 기본 프리픽스 (main.py) | 역할 | 핵심 규칙 |
| --- | --- | --- | --- |
| `api/auth_router.py` | `/api/v1/auth` | KIS 토큰 발급/갱신, WebSocket 승인 키, 거래 환경 조회 | `AuthService`만 호출, `KISAuthDep` 주입, `ResponseDTO.success_response` 사용 |
| `api/market_data_router.py` | `/api/v1/market` | 현재가/호가/차트 조회 | `MarketDataService` 사용, `use_cache`로 Redis 캐시 토글, 엔드포인트에 비즈니스 로직 추가 금지 |
| `api/account_router.py` | `/api/v1/accounts` | 계좌 잔고/포지션 조회 | `AccountService` 사용, 캐시 TTL(30s) 정책은 서비스에 위임 |
| `api/order_router.py` | `/api/v1/orders` | 주문 생성/조회/정정/취소/상태 갱신 | `OrderService`만 호출, `DatabaseSession`/`KISClientDep` 주입, path `order_id`를 요청 DTO에 반영해 일관성 유지 |
| `api/strategy_router.py` | `/api/v1/strategies` | 전략 CRUD 및 start/pause/stop | `StrategyService`만 호출, 세션 커밋/롤백은 서비스/데코레이터에 위임 |
| `api/backtest_router.py` | ⚠️ 파일 내부에 `prefix="/api/v1/backtest"` 선언 | 단일/다중 종목 백테스트, 데이터 검증 | 이 라우터는 자체 프리픽스를 포함하므로 **`main.py`에서 중복 프리픽스를 추가하지 않도록 주의**. 결과 DTO를 직접 반환하며 `ResponseDTO`를 래핑하지 않습니다. |
| `api/websocket_router.py` | `/ws` | 실시간 시세 WebSocket | `websocket_manager` 사용, 메시지 포맷을 유지(`action`, `tr_id`, `tr_key`), 연결 종료 시 구독/연결 해제 호출 필수 |

## 공통 구현 규칙
- **응답 포맷**: REST 엔드포인트는 `application.common.dto.ResponseDTO.success_response`를 사용하고, 직접 dict를 반환하지 않습니다. (예외: `backtest_router`는 DTO를 그대로 반환하는 레거시 경로, 신규 기능은 ResponseDTO로 통일 권장)
- **예외 처리**: 도메인 서비스에서 발생한 예외를 가로채지 말고 전파하세요. FastAPI/글로벌 핸들러가 표준화된 응답으로 변환합니다.
- **의존성 주입**: `application.common.dependencies`에서 제공하는 `KISAuthDep`, `KISClientDep`, `DatabaseSession`, `RedisDep`만 사용하고, 라우터에서 세션/클라이언트를 수동 생성하거나 커밋하지 않습니다.
- **로깅/보안**: 계좌번호, 주문번호 등 PII는 로그에 직접 남기지 말고 필요 시 마스킹하세요. 액세스/승인 키는 응답 DTO 외부로 노출하지 않습니다.
- **WebSocket**: 연결 종료나 예외 발생 시 `websocket_manager.disconnect()` 및 필요한 `unsubscribe` 처리를 `finally` 또는 예외 블록에서 보장해 누수를 방지합니다.
- **프리픽스 일관성**: 라우터 파일에는 가능한 한 프리픽스를 두지 말고, `main.py`에서 일괄 부여합니다. 기존에 프리픽스가 박힌 모듈을 수정할 때는 main 등록을 중복 적용하지 않는지 확인하세요.

## 구현 체크리스트
1. 새 라우터 추가 시 `src/main.py`에 `app.include_router`를 등록하고, 프리픽스/태그를 일관되게 지정한다.
2. 라우터 내부에서는 도메인 서비스만 호출하고 Repository/세션 커밋을 직접 수행하지 않는다.
3. 응답 스키마는 `ResponseDTO` 제네릭을 사용해 OpenAPI 스펙을 유지한다. (예외 경로는 주석으로 남길 것)
4. Redis/DB/KIS 클라이언트는 `Depends`/타입별 Dependency Alias로 주입하고, `None` 기본값으로 테스트 용이성을 확보한다.
5. WebSocket 엔드포인트는 연결/구독/해제/에러 흐름을 모두 로그 남기고 클린업을 보장한다.
6. 필요 시 관리자 페이지를 추가하더라도 상태 변경은 API 라우터를 통해 수행하고, 페이지 라우터는 GET 전용으로 둔다.

