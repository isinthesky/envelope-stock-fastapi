# CLAUDE.md - settings 디렉토리 가이드

> 환경 설정 계층: Pydantic Settings 기반 타입 안전 환경 변수 관리 및 앱 수준 설정

## ✅ 역할
- `.env`/환경 변수 값을 타입 안전하게 로드
- 거래 환경(prod/vps)에 따라 KIS 설정을 자동 스위칭
- 애플리케이션 전역 설정을 단일 인스턴스로 제공
- 예외 핸들러 등 앱 수준 횡단 관심사 설정

---

## 📂 구조
```
settings/
├── __init__.py
├── config.py               # Settings 정의 (Pydantic BaseSettings)
├── logging_config.py       # setup_logging(): dictConfig 로 log_* 설정을 실제 logging 에 연결
├── sell_score_settings.py  # SellScoreSettings(매도 점수 가중치/임계값) + PeakRuleThresholds
└── exception_handlers.py   # 전역 예외 핸들러 등록
```

---

## 📋 config.py 구성 요약
- `Settings(BaseSettings)` + `SettingsConfigDict`
- `get_settings()` + `settings` 전역 인스턴스

### 주요 설정 그룹
- 앱/서버 (`app_name`, `app_version`, `env`, `host`, `port`)
- DB/Redis (`database_url`, `redis_url`, `redis_max_connections`)
- 캐시 TTL (`cache_ttl_*`, `cache_retention_*`)
- KIS 인증/URL/Rate Limit (`kis_*`, `kis_api_*`, `order_*`)
- 거래 환경/리스크 (`trading_environment`, `risk_*`)
- CORS/로깅 (`cors_*`, `log_level`, `log_to_file`, `log_file`, `log_max_bytes`, `log_backup_count`)
  - 실제 적용은 `logging_config.setup_logging()` 이 하며 `src/main.py` 최상단에서 호출된다(라우터/서비스 import 보다 앞).
  - 콘솔(stdout) 핸들러는 항상 유지, 파일 핸들러는 `log_to_file=true` 일 때만 추가된다(컨테이너는 별도 볼륨 마운트 필요).
  - `httpx`/`httpcore`/`urllib3` 는 WARNING 으로 고정한다(INFO 시 URL 전체가 남아 Telegram bot token, DART `crtfc_key` 가 유출된다). 이 셋은 표준 logging 경로라 레벨 pin 이 실제로 유효하다.
  - `sqlalchemy.engine` 도 같은 pin 을 걸지만 **기본 경로만 막을 뿐 `DATABASE_ECHO=true` 는 이 설정을 우회한다.** SQLAlchemy 는 `create_async_engine(echo=True)` 일 때 `InstanceLogger.log()` 가 로거 레벨 검사를 건너뛰고 `logger._log()` 를 직접 호출하며 자체 stdout 핸들러까지 붙이므로, SQL 전문과 바인드 파라미터(주문 수량/가격, 계좌번호)가 그대로 출력된다. 실계좌(`TRADING_ENVIRONMENT=prod`) 환경에서는 `DATABASE_ECHO` 를 켜지 않는다.
  - ⚠️ JWT 설정(`jwt_*`)은 구현된 적 없는 예정 기능이었고 2026-09-08에 `config.py`와 `.env.example`에서 제거됐다. `extra="ignore"` 때문에 `.env` 에 `JWT_*` 가 남아 있어도 무해하다.
- 관리자 접근 제어/프록시 신뢰 (`admin_allowed_ips`, `trusted_proxy_ips`, `enable_admin_strategy_routes`)
  - `trusted_proxy_ips` 기본값은 `["127.0.0.0/8", "::1/128"]` 이며 `application/common/client_ip.py` 가 단일 출처로 소비한다.
- 대시보드/WS/uvicorn/Telegram (`dashboard_*`, `ws_*`, `uvicorn_*`, `telegram_*`)
- 전략 실행/유니버스 스케줄 (`strategy_execution_hour/minute`, `strategy_execution_misfire_grace_seconds`(≥1), `universe_refresh_hour/minute`)
- 전략 실행 경로 kill-switch (`strategy_live_trading_enabled`, env `STRATEGY_LIVE_TRADING_ENABLED`, 기본 `False`) — 강제 지점은 `domain/strategy/golden_cross_engine.py:137` 한 곳이다.
  - ⚠️ **서버 전체의 실주문 차단기가 아니다.** 이 스위치가 덮는 범위는 골든크로스 엔진을 타는 경로(15:35 스케줄러 실행, `POST /api/v1/strategies/{id}/execute`)뿐이다.
  - `POST /api/v1/orders`(`interface/api/order_router.py` → `domain/order/service.py`)는 이 검사를 거치지 않고 KIS `order-cash`(`TTTC0802U`/`TTTC0801U`)를 직접 호출하는 **별개의 실주문 경로**이며, 보호 장치는 `AdminAccessDep`(`ADMIN_ALLOWED_IPS` + 쓰기용 `X-Requested-With` 헤더)뿐이다. 스위치를 "마스터"로 서술하지 말 것.
- 알림 스케줄러 (`buy_notification_slots`/`sell_notification_slots`(시/분 범위 validator), `etf_leader_map`, `buy_notification_stoch_threshold`, `buy_notification_top_n`/`top_industries_n`/`scan_limit`)

> 매도 점수 관련 설정(가중치·거래량 구간·개인수급/신용 피크 임계값)은 `sell_score_settings.py`의 `SellScoreSettings`/`PeakRuleThresholds`에 있다.

> `PeakRuleThresholds.personal_strong_gate_ratio`(0.15)와 `SellScoreSettings.personal_buy_ratio_high`(0.20)는 **drift가 아니라 서로 다른 판정기**다.
> 전자는 peak 규칙 성립 여부를 가르는 이진 게이트, 후자는 매도 점수 티어 경계다. 통일하면 라이브 매도 Stage 판정이 바뀐다.
> 2026-09-08에 이름을 `personal_strong_ratio` → `personal_strong_gate_ratio` 로 바꿔 용도를 드러냈고(`gate`), 미해결로 남아 있던 `TODO(refactor)` 주석은 확정 NOTE로 대체했다.
> 근거 핀 테스트: `tests/domain/test_threshold_ssot.py`.

### Computed Properties
- `is_production`, `is_development`, `is_paper_trading`
- `kis_base_url`, `kis_ws_url`
- `current_kis_app_key`, `current_kis_app_secret`, `current_kis_account_no`

### Validators
- 계좌번호 길이 검증(8자리)
- 상품 코드 유효성 검증
- `DATABASE_URL`을 asyncpg 드라이버로 자동 보정

---

## 📋 exception_handlers.py 구성 요약

### 역할
- 도메인 예외(`ApplicationError`)를 HTTP 응답으로 변환
- 모든 예외 타입에 대해 통일된 JSON 응답 포맷 보장
- 로깅 및 모니터링 통합 지점

### 핸들러 종류
| 핸들러 | 예외 타입 | 설명 |
|--------|----------|------|
| `application_error_handler` | `ApplicationError` | 커스텀 도메인 예외 |
| `http_exception_handler` | `HTTPException` | FastAPI 기본 예외 |
| `validation_error_handler` | `RequestValidationError` | Pydantic 검증 에러 |
| `generic_exception_handler` | `Exception` | 예상치 못한 예외 (Fallback) |

### 사용법
```python
# src/main.py
from src.settings.exception_handlers import register_exception_handlers

app = FastAPI(...)
register_exception_handlers(app)
```

---

## ✅ 사용 규칙
- 환경 설정 추가는 `config.py`에만 수행합니다.
- `settings` 전역 인스턴스를 사용해 읽기 전용으로 참조합니다.
- 민감한 값은 `.env.example`에만 템플릿으로 기록합니다.
- 예외 클래스 정의는 `src/application/common/exceptions.py`에서 합니다.

---

## 🔗 관련 문서
- `src/CLAUDE.md`
- `src/adapters/CLAUDE.md`
- `src/application/common/exceptions.py` - 커스텀 예외 클래스 정의
- `.claude/skills/fastapi-exception-handling/skill.md` - 예외 처리 아키텍처 스킬
