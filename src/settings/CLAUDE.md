# CLAUDE.md - settings 디렉토리 가이드

> 환경 설정 계층: Pydantic Settings 기반 타입 안전 환경 변수 관리

## ✅ 역할
- `.env`/환경 변수 값을 타입 안전하게 로드
- 거래 환경(prod/vps)에 따라 KIS 설정을 자동 스위칭
- 애플리케이션 전역 설정을 단일 인스턴스로 제공

---

## 📂 구조
```
settings/
├── __init__.py
└── config.py      # Settings 정의
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
- JWT/CORS/로깅 (`jwt_*`, `cors_*`, `log_*`)
- 대시보드/WS/uvicorn/Telegram (`dashboard_*`, `ws_*`, `uvicorn_*`, `telegram_*`)

### Computed Properties
- `is_production`, `is_development`, `is_paper_trading`
- `kis_base_url`, `kis_ws_url`
- `current_kis_app_key`, `current_kis_app_secret`, `current_kis_account_no`

### Validators
- 계좌번호 길이 검증(8자리)
- 상품 코드 유효성 검증
- `DATABASE_URL`을 asyncpg 드라이버로 자동 보정

---

## ✅ 사용 규칙
- 설정 추가는 `config.py`에만 수행합니다.
- `settings` 전역 인스턴스를 사용해 읽기 전용으로 참조합니다.
- 민감한 값은 `.env.example`에만 템플릿으로 기록합니다.

---

## 🔗 관련 문서
- `src/CLAUDE.md`
- `src/adapters/CLAUDE.md`
