# CLAUDE.md - `src/settings/` (환경 설정) 가이드

> `pydantic-settings` 기반의 타입 안전 설정 레이어입니다. 애플리케이션 전역 설정은 `settings` 싱글톤으로 접근합니다.

## 구성

```text
settings/
  config.py   # Settings(BaseSettings), validators, computed properties
```

## `config.py` 핵심(현재 코드 기준)
- **Settings 모델**
  - 앱/서버: `app_name`, `app_version`, `env`, `debug`, `host`, `port(기본 8000)`
  - DB/Redis: `database_url`(asyncpg 강제 보정), `redis_url`, `redis_max_connections`
  - 캐시 TTL/보관: `cache_ttl_*`, `cache_retention_*`
  - KIS: 실전/모의 키/시크릿/계좌, base URL/WS URL, rate limit/backoff, 주문 간격 제한
  - 리스크: 노출/리스크/동시 포지션/일 손실 한도 등
  - CORS/로깅/대시보드/WS/uvicorn/Telegram
- **Computed properties**
  - `is_production`, `is_development`, `is_paper_trading`
  - `kis_base_url`, `kis_ws_url`
  - `current_kis_app_key`, `current_kis_app_secret`, `current_kis_account_no`
- **Validators**
  - 계좌번호 길이(8자리)
  - 상품 코드 유효성
  - `database_url` 드라이버를 `postgresql+asyncpg://`로 강제(그린렛 컨텍스트 오류 예방)

## 사용 규칙
- 설정 추가/변경은 **`config.py`에서만** 수행합니다.
- 코드에서는 `from src.settings.config import settings`로 읽기 전용 참조합니다.
- 민감정보는 저장소에 커밋하지 않습니다.
  - 템플릿은 `.env.example`에만(실제 값은 로컬/CI secret로 관리)

## 관련 문서
- `CLAUDE.md` (프로젝트 전체)
- `src/CLAUDE.md` (엔트리포인트/라이프사이클)
- `src/adapters/CLAUDE.md`

