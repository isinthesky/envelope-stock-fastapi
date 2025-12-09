# CLAUDE.md - settings 디렉토리 가이드

> **환경 설정 계층**: Pydantic Settings 기반 타입 안전 환경 변수 관리

## 📁 디렉토리 역할

`settings/` 디렉토리는 애플리케이션의 **모든 환경 설정을 중앙 집중 관리**합니다. `.env` 파일과 환경 변수를 Pydantic으로 타입 안전하게 로드합니다.

---

## 📂 파일 구조

```
settings/
├── __init__.py     # settings 패키지 익스포트
└── config.py       # Settings 클래스 정의
```

---

## 📋 핵심 파일: config.py

### Settings 클래스 구조

```python
class Settings(BaseSettings):
    """애플리케이션 환경 설정"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
```

### 설정 카테고리

| 카테고리 | 환경 변수 예시 | 설명 |
|----------|---------------|------|
| **애플리케이션** | `APP_NAME`, `ENV`, `DEBUG` | 앱 기본 정보 |
| **서버** | `HOST`, `PORT` | 서버 바인딩 |
| **Database** | `DATABASE_URL`, `DATABASE_ECHO` | PostgreSQL 연결 |
| **Redis** | `REDIS_URL`, `REDIS_PASSWORD` | Redis 캐시 연결 |
| **KIS API (실전)** | `KIS_APP_KEY`, `KIS_APP_SECRET` | 실전투자 인증 |
| **KIS API (모의)** | `KIS_PAPER_APP_KEY`, `KIS_PAPER_APP_SECRET` | 모의투자 인증 |
| **캐시 TTL** | `CACHE_TTL_MARKET_DATA`, `CACHE_TTL_ACCOUNT` | 캐시 만료 시간 |
| **리스크 관리** | `RISK_DAILY_LOSS_LIMIT`, `RISK_MAX_POSITIONS` | 거래 제한 |
| **JWT** | `JWT_SECRET_KEY`, `JWT_ALGORITHM` | 인증 토큰 |
| **CORS** | `CORS_ORIGINS`, `CORS_ALLOW_METHODS` | 교차 출처 설정 |
| **로깅** | `LOG_LEVEL`, `LOG_FILE` | 로그 설정 |
| **WebSocket** | `WS_MAX_CONNECTIONS`, `WS_PING_INTERVAL` | WS 연결 관리 |

---

## 🔧 주요 설정 항목

### KIS API 설정

```python
# 실전투자
kis_app_key: str           # 앱키
kis_app_secret: str        # 앱시크릿
kis_account_no: str        # 계좌번호 (8자리)
kis_product_code: str      # 상품코드 (01: 종합)

# 모의투자
kis_paper_app_key: str
kis_paper_app_secret: str
kis_paper_account_no: str

# API URL
kis_prod_url: str          # 실전 API URL
kis_vps_url: str           # 모의 API URL
kis_prod_ws_url: str       # 실전 WebSocket URL
kis_vps_ws_url: str        # 모의 WebSocket URL
```

### Computed Properties (자동 계산 속성)

```python
@property
def is_production(self) -> bool:
    """운영 환경 여부"""
    return self.env == "production"

@property
def is_paper_trading(self) -> bool:
    """모의투자 여부"""
    return self.trading_environment == "vps"

@property
def kis_base_url(self) -> str:
    """현재 거래 환경의 KIS API Base URL"""
    return self.kis_vps_url if self.is_paper_trading else self.kis_prod_url

@property
def current_kis_app_key(self) -> str:
    """현재 거래 환경의 앱키"""
    return self.kis_paper_app_key if self.is_paper_trading else self.kis_app_key
```

---

## 🔄 싱글톤 패턴

```python
@lru_cache
def get_settings() -> Settings:
    """설정 싱글톤 인스턴스 반환"""
    return Settings()

# 전역 설정 인스턴스
settings = get_settings()
```

### 사용 방법

```python
# 방법 1: 전역 인스턴스 사용
from src.settings.config import settings
print(settings.database_url)

# 방법 2: 함수 호출
from src.settings.config import get_settings
settings = get_settings()
```

---

## ✅ Validators (검증기)

```python
@field_validator("kis_account_no", "kis_paper_account_no")
@classmethod
def validate_account_no(cls, v: str) -> str:
    """계좌번호 검증 (8자리)"""
    if v and len(v) != 8:
        raise ValueError("계좌번호는 8자리여야 합니다")
    return v

@field_validator("kis_product_code")
@classmethod
def validate_product_code(cls, v: str) -> str:
    """상품코드 검증"""
    valid_codes = ["01", "03", "08", "22", "29"]
    if v not in valid_codes:
        raise ValueError(f"상품코드는 {valid_codes} 중 하나여야 합니다")
    return v
```

---

## 📝 .env 파일 예시

```env
# 애플리케이션
APP_NAME=KIS Trading API Service
ENV=development
DEBUG=true

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

# 거래 환경 (prod: 실전, vps: 모의)
TRADING_ENVIRONMENT=vps

# 리스크 관리
RISK_DAILY_LOSS_LIMIT=1000000
RISK_MAX_POSITIONS=10
```

---

## 🔒 보안 규칙

1. **`.env` 파일은 절대 Git에 커밋하지 않음** (`.gitignore`에 포함)
2. **API 키는 환경 변수로만 관리**
3. **JWT 시크릿 키는 운영 환경에서 반드시 변경**
4. **모의투자로 충분히 테스트 후 실전투자 사용**

---

## 🔗 관련 문서

- [아키텍처 문서](../../docs/base/ARCHITECTURE.md)
- [서비스 구현 가이드](../../docs/base/SERVICE.md)

---

**💡 핵심**: 모든 설정은 **타입 안전**하게 관리되며, 잘못된 값은 애플리케이션 시작 시 즉시 검증 오류를 발생시킵니다.
