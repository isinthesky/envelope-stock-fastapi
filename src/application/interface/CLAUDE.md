# CLAUDE.md - `application/interface/` (Inbound) 가이드

> HTTP/WS/Page 진입점(라우터) 레이어입니다. **“얇은 라우터” 원칙**: 입력 파싱/검증 → 도메인 서비스 호출 → 응답 포맷만 담당합니다.

## 폴더 구조

```text
interface/
  api/     # REST/WS 라우터
  page/    # Jinja2 관리 페이지 라우터
```

## API 라우터 맵(현재 파일 기준)

| 파일 | prefix | 주요 책임 | 응답 |
|---|---|---|---|
| `api/auth_router.py` | `/api/v1/auth` | KIS 인증/토큰/승인키 | `ResponseDTO` |
| `api/market_data_router.py` | `/api/v1/market` | 현재가/호가/차트 | `ResponseDTO` |
| `api/account_router.py` | `/api/v1/accounts` | 잔고/포지션 | `ResponseDTO` |
| `api/order_router.py` | `/api/v1/orders` | 주문 생성/취소/조회/정정 | `ResponseDTO` |
| `api/strategy_router.py` | `/api/v1/strategies` | 전략/유니버스/시그널/스케줄링 (**관리자 전용** — main.py에서 라우터 단위 `verify_admin_access`) | `ResponseDTO` |
| `api/public_strategy_router.py` | `/api/v1/public/strategies` (내부 prefix) | 공개 골든크로스 스캔(제한형)/추천 스냅샷 — IP 쿨다운·전역 락·고정 한도는 `PublicStrategyService`. `GET /scan-capabilities`는 현재 유니버스 모드(ETF-only 여부)에 따른 가용 시장 목록을 인증 없이 조회 | `ResponseDTO` |
| `api/sell_rule_research_router.py` | `/api/v1/strategies` (내부 prefix) | 사전등록 매도 규칙 리서치 | `ResponseDTO` |
| `api/ohlcv_router.py` | `/api/v1/ohlcv` | OHLCV 캐시 통계/워밍업/정리/검증 | `ResponseDTO` |
| `api/screener_router.py` | `/api/v1/screener` (내부 prefix) | 네이버 기반 가치주 스크리닝 | `ResponseDTO` |
| `api/recommendation_router.py` | `/api/v1/recommendations` (내부 prefix) | 추천 후보/룰셋/walk-forward 검증 | `ResponseDTO` |
| `api/backtest_router.py` | `/api/v1/backtest` (내부 prefix) | 백테스트 실행/검증 | **raw DTO** (`BacktestResultDTO` 등) |
| `api/websocket_router.py` | `/ws` | 실시간 WebSocket | WS 메시지 |

## Page 라우터(관리 페이지 + 공개 포털)
- `page/__init__.py`의 `mypage_routers`는 `src/main.py`에서 `verify_admin_access`와 함께, `public_page_routers`는 의존성 없이 include 됩니다.
- 각 라우터는 자체 prefix와 템플릿을 가집니다(`templates/page/*.html`).
- 신규 추천 관리 화면은 `page/recommendation_page_router.py` → `/mypage/recommendation/` → `templates/page/recommendation.html` → `static/js/pages/recommendation.js` 흐름을 따릅니다.
- 공개 전략 포털: `page/public_strategy_page_router.py` → `/page/`(소개)·`/page/scan/`(신호 등급별 제한형 스캔). 기존 `/page/recommendations/`는 스캔 화면으로 영구 리다이렉트합니다. 공개 화면은 `templates/layouts/public_base.html` + `templates/page/public_strategy_*.html` + `static/js/pages/public_strategy_*.js`를 사용하며 관리자 CSRF fetch shim을 넣지 않습니다.

## 구현 규칙
- **비즈니스 로직 금지**: 라우터는 서비스 호출만 수행합니다.
- **세션/인프라 주입**
  - DB 세션은 `DatabaseSession`(common DI alias) 사용을 우선합니다.
  - KIS/Redis/WebSocket은 `application.common.dependencies`의 Alias/Dependency를 우선합니다.
- **응답 포맷**
  - 기본은 `ResponseDTO`로 감쌉니다.
  - 단, `backtest_router`는 현재 raw DTO를 반환하는 레거시/호환 경로입니다(문서/테스트에서 이 차이를 전제).

## 변경 시 체크리스트
- prefix/경로 변경 시: `src/main.py`의 `include_router`와 Swagger tag 정합성 확인
- response_model 변경 시: 프론트 템플릿(Page)과 호출 스크립트 영향 확인

## 관련 문서
- `src/CLAUDE.md`
- `src/application/domain/CLAUDE.md`
- `src/application/common/CLAUDE.md`
