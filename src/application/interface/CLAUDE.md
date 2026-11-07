# CLAUDE.md - `application/interface/` (Inbound) 가이드

> HTTP/WS/Page 진입점(라우터) 레이어입니다. **“얇은 라우터” 원칙**: 입력 파싱/검증 → 도메인 서비스 호출 → 응답 포맷만 담당합니다.

## 폴더 구조

```text
interface/
  api/     # REST/WS 라우터
  page/    # Jinja2 관리 페이지(/mypage, /ops) + 공개 포털(/page) 라우터
  admin_session_gate.py  # 전역 로그인 게이트(AdminSessionGateMiddleware)
```

## API 라우터 맵(현재 파일 기준)

| 파일 | prefix | 주요 책임 | 응답 |
|---|---|---|---|
| `api/auth_router.py` | `/api/v1/auth` | KIS 인증/토큰/승인키 | `ResponseDTO` |
| `api/market_data_router.py` | `/api/v1/market` | 현재가/호가/차트 | `ResponseDTO` |
| `api/account_router.py` | `/api/v1/accounts` | 잔고/포지션 | `ResponseDTO` |
| `api/order_router.py` | `/api/v1/orders` | 주문 생성/취소/조회/정정 (**IP 게이트 + 관리자 로그인 세션** — main.py include-level `require_admin_session`) | `ResponseDTO` |
| `api/admin_auth_router.py` | `/api/v1/admin-auth` (내부 prefix) | 관리자 ID/PW 로그인·로그아웃·세션 조회. 세션은 HttpOnly/SameSite=Strict 쿠키 `kis_admin_session` | `ResponseDTO` |
| `api/strategy_router.py` | `/api/v1/strategies` | 전략/유니버스/시그널/스케줄링 (**관리자 전용** — main.py에서 라우터 단위 `verify_admin_access`) | `ResponseDTO` |
| `api/public_strategy_router.py` | `/api/v1/public/strategies` (내부 prefix) | 공개 골든크로스 스캔(제한형)/추천 스냅샷 — IP 쿨다운·전역 락·고정 한도는 `PublicStrategyService`. `GET /scan-capabilities`는 현재 유니버스 모드(ETF-only 여부)에 따른 가용 시장 목록을 인증 없이 조회 | `ResponseDTO` |
| `api/sell_rule_research_router.py` | `/api/v1/strategies` (내부 prefix) | 사전등록 매도 규칙 리서치 | `ResponseDTO` |
| `api/screener_router.py` | `/api/v1/screener` (내부 prefix) | 네이버 기반 가치주 스크리닝 | `ResponseDTO` |
| `api/recommendation_router.py` | `/api/v1/recommendations` (내부 prefix) | 추천 후보/룰셋/walk-forward 검증 | `ResponseDTO` |
| `api/backtest_router.py` | `/api/v1/backtest` (내부 prefix) | 백테스트 실행/검증 | **raw DTO** (`BacktestResultDTO` 등) |
| `api/ops_router.py` | `/api/v1/ops` (내부 prefix) | 운영 요약/알림 스케줄러 상태 (`AdminAccessDep` 보호) | `ResponseDTO` |
| `api/access_log_router.py` | `/api/v1/access-logs` (내부 prefix) | 접근 로그 조회/통계/고유 IP/정리 (관리자 IP 전용 `AdminAccessDep`) | `ResponseDTO[AccessLog*DTO]` |
| `api/websocket_router.py` | `/ws` | 실시간 WebSocket(`/ws/realtime`) + 연결 정보(`GET /ws/info`) | WS 메시지 / dict |

## 전역 로그인 게이트
- `admin_session_gate.py`의 `AdminSessionGateMiddleware`가 공개 경로 화이트리스트(`PUBLIC_EXACT_PATHS`/`PUBLIC_PATH_PREFIXES`) 외 모든 요청에 로그인 세션을 요구합니다(기본 거부). 새 **공개** 라우트를 만들면 이 목록에 넣어야 하며, 관리자 라우트는 아무것도 하지 않아도 보호됩니다.

## Page 라우터(관리 페이지 + 공개 포털)
- `page/__init__.py`의 `mypage_routers`는 `src/main.py`에서 `verify_admin_access`와 함께, `public_page_routers`는 의존성 없이 include 됩니다.
- 각 라우터는 자체 prefix와 템플릿을 가집니다(`templates/page/*.html`).
- **로그인 게이트 페이지**: `/mypage/order`는 `OptionalAdminSessionDep`로 세션을 확인하고 미로그인 시 `/mypage/login/?next=...`로 303 리다이렉트합니다. `next`는 `safe_next_path()`로 `/mypage/` 하위만 허용(오픈 리다이렉트 방지). 로그인 페이지(`admin_login_page_router.py`, `templates/page/admin_login.html`)는 base 레이아웃을 쓰지 않는 단독 페이지라 CSRF 헤더를 직접 붙입니다. 회귀 테스트: `tests/interface/test_admin_login_boundary.py`.
- 신규 추천 관리 화면은 `page/recommendation_page_router.py` → `/mypage/recommendation/` → `templates/page/recommendation.html` → `static/js/pages/recommendation.js` 흐름을 따릅니다.
- **엔진 출처 배지**: 매도 판단 결과를 보여주는 화면은 상단에 `p.engine-note` + `span.engine-badge`로 어느 엔진(E1/E2/E3) 결과인지 고지합니다(스타일: `static/styles/mypage.css`, `static/styles/public_strategy.css`). `/mypage/strategy/dashboard`는 `strategy_live_trading_enabled` 값을 템플릿 컨텍스트로 받아 `실주문 스위치 ON/OFF` 배지를 함께 렌더링합니다. 화면↔엔진 매핑표는 `docs/buy-sell-usage-guide.md` §2, 회귀 테스트는 `tests/interface/test_admin_page_engine_badges.py`.
- 공개 전략 포털: `page/public_strategy_page_router.py` → `/page/`(소개)·`/page/scan/`(신호 등급별 제한형 스캔)·`/page/sell-analysis/`(공개 매도 분석). 기존 `/page/recommendations/`는 스캔 화면으로 영구 리다이렉트합니다. 공개 화면은 `templates/layouts/public_base.html` + `templates/page/public_strategy_*.html` + `static/js/pages/public_strategy_*.js`를 사용하며 관리자 CSRF fetch shim을 넣지 않습니다.

## 구현 규칙
- **비즈니스 로직 금지**: 라우터는 서비스 호출만 수행합니다.
- **클라이언트 IP**: 직접 `request.client.host`나 `X-Forwarded-For`를 읽지 말고 `application.common.client_ip`의 `get_client_ip()`를 사용합니다(관리자 IP 검증·공개 쿨다운·접근 로그·WebSocket 공통 규칙).
- **세션/인프라 주입**
  - DB 세션은 `DatabaseSession`(common DI alias) 사용을 우선합니다.
  - 단, 서비스가 `@transaction`으로 세션을 소유하는 경우(`RecommendationRuleSetService`, `AccessLogService`)는 라우터가 세션을 받지 않는 것이 **정상 패턴**입니다. 이때 라우터는 핸들러 안에서 서비스를 직접 생성합니다(생성자 인자 없음).
  - KIS/Redis/WebSocket은 `application.common.dependencies`의 Alias/Dependency를 우선합니다.
- **응답 포맷**
  - 기본은 `ResponseDTO`로 감쌉니다.
  - 단, `backtest_router`는 현재 raw DTO를 반환하는 레거시/호환 경로입니다(문서/테스트에서 이 차이를 전제).

## 변경 시 체크리스트
- prefix/경로 변경 시: `src/main.py`의 `include_router`와 tag 정합성, 공개 경로라면 `admin_session_gate.py` 화이트리스트 확인(Swagger/OpenAPI는 비활성)
- response_model 변경 시: 프론트 템플릿(Page)과 호출 스크립트 영향 확인

## 관련 문서
- `src/CLAUDE.md`
- `src/application/domain/CLAUDE.md`
- `src/application/common/CLAUDE.md`
