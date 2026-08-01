# -*- coding: utf-8 -*-
"""
환경 설정 모듈

Pydantic Settings를 사용한 타입 안전 환경 변수 관리
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """애플리케이션 환경 설정"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ==================== 애플리케이션 설정 ====================
    app_name: str = Field(default="KIS Strategy & Alert Server", description="애플리케이션 이름")
    app_version: str = Field(default="0.1.0", description="애플리케이션 버전")
    env: Literal["development", "staging", "production"] = Field(
        default="development", description="실행 환경"
    )
    debug: bool = Field(default=False, description="디버그 모드")

    # ==================== 서버 설정 ====================
    host: str = Field(default="0.0.0.0", description="서버 호스트")
    port: int = Field(default=8000, ge=1, le=65535, description="서버 포트")

    # ==================== Database 설정 ====================
    database_url: str = Field(
        default="postgresql+asyncpg://kis_user:kis_password@localhost:5432/kis_trading",
        description="데이터베이스 연결 URL",
    )
    database_echo: bool = Field(default=False, description="SQLAlchemy 쿼리 로그 출력")

    # ==================== Redis 설정 ====================
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis 연결 URL")
    redis_password: str | None = Field(default=None, description="Redis 비밀번호")
    redis_max_connections: int = Field(default=50, ge=1, le=1000, description="Redis 최대 연결 수")

    # ==================== 캐시 TTL ====================
    cache_ttl_market_data: int = Field(default=5, ge=1, description="시세 데이터 캐시 TTL (초)")
    cache_ttl_orderbook_snapshot: int = Field(
        default=15, ge=1, description="호가 스냅샷 캐시 TTL (초)"
    )
    cache_ttl_daily_candles: int = Field(
        default=86400, ge=1, description="일봉/주봉/월봉 캐시 TTL (초)"
    )
    cache_ttl_intraday_candles: int = Field(default=900, ge=1, description="분봉 캐시 TTL (초)")
    cache_ttl_account: int = Field(default=30, ge=1, description="계좌 정보 캐시 TTL (초)")
    cache_ttl_token: int = Field(default=86400, ge=1, description="토큰 캐시 TTL (초)")
    cache_retention_ticks_days: int = Field(
        default=7, ge=1, description="틱/체결 데이터 보관 기간 (일)"
    )
    cache_retention_orders_days: int = Field(
        default=365, ge=1, description="주문/체결 기록 보관 기간 (일)"
    )

    # ==================== OHLCV 캐시 설정 ====================
    ohlcv_cache_freshness_days: int = Field(
        default=1, ge=1, le=7, description="OHLCV 캐시 신선도 기준 (일)"
    )
    ohlcv_warmup_freshness_days: int = Field(
        default=3, ge=1, le=7, description="OHLCV 워밍업/스케줄러 신선도 기준 (일)"
    )
    ohlcv_retention_days: int = Field(
        default=1400,
        ge=30,
        le=3650,
        description="OHLCV 보존 기간 (일). 3년 백테스트(1095) + 지표 워밍업 버퍼(~300)",
    )
    ohlcv_cleanup_batch_size: int = Field(
        default=1000, ge=100, le=10000, description="OHLCV 정리 배치 크기"
    )
    ohlcv_max_api_days_per_call: int = Field(
        default=100,
        ge=1,
        le=100,
        description="KIS API 단일 호출 최대 조회 기간 (일). KIS 100행 캡 초과 시 과거분 무음 절삭되므로 ≤100",
    )

    # ==================== KIS API 설정 (실전투자) ====================
    kis_app_key: str = Field(default="", description="KIS 실전투자 앱키")
    kis_app_secret: str = Field(default="", description="KIS 실전투자 앱시크릿")
    kis_account_no: str = Field(default="", description="KIS 계좌번호 (8자리)")
    kis_product_code: str = Field(
        default="01", description="KIS 계좌상품코드 (01: 종합계좌, 03: 선물옵션)"
    )
    kis_hts_id: str = Field(default="", description="KIS HTS ID")

    # ==================== KIS API 설정 (모의투자) ====================
    kis_paper_app_key: str = Field(default="", description="KIS 모의투자 앱키")
    kis_paper_app_secret: str = Field(default="", description="KIS 모의투자 앱시크릿")
    kis_paper_account_no: str = Field(default="", description="KIS 모의투자 계좌번호")
    kis_paper_hts_id: str = Field(default="", description="KIS 모의투자 HTS ID")

    # ==================== KIS API URL ====================
    kis_prod_url: str = Field(
        default="https://openapi.koreainvestment.com:9443", description="KIS 실전투자 API URL"
    )
    kis_vps_url: str = Field(
        default="https://openapivts.koreainvestment.com:29443",
        description="KIS 모의투자 API URL",
    )
    kis_prod_ws_url: str = Field(
        default="ws://ops.koreainvestment.com:21000",
        description="KIS 실전투자 WebSocket URL",
    )
    kis_vps_ws_url: str = Field(
        default="ws://ops.koreainvestment.com:31000",
        description="KIS 모의투자 WebSocket URL",
    )

    # ==================== KIS API Rate Limit ====================
    kis_api_rate_limit: int = Field(default=10, ge=1, description="KIS API 초당 호출 제한")
    kis_api_rate_window_seconds: int = Field(default=1, ge=1, description="Rate Limit 윈도우 (초)")
    kis_api_retry_count: int = Field(default=3, ge=0, description="API 호출 실패 시 재시도 횟수")
    kis_api_timeout: int = Field(default=10, ge=1, description="API 호출 타임아웃 (초)")
    kis_api_rate_limit_max_retries: int = Field(
        default=3, ge=0, description="EGW00201(초당 거래건수 초과) 응답 시 지수 백오프 재시도 최대 횟수"
    )
    kis_api_rate_limit_backoff_base_seconds: float = Field(
        default=0.5, gt=0, description="EGW00201 재시도 지수 백오프 기본 대기 시간 (초, 0.5→1.0→2.0)"
    )
    kis_api_rate_min_interval_ms: int = Field(
        default=0,
        ge=0,
        description="KIS REST 연속 호출 간 최소 간격 (ms). 0이면 window/capacity로 자동 산출",
    )
    scan_concurrency_limit: int = Field(
        default=5, ge=1, description="스캔 동시 처리 수 (골든크로스/MA5)"
    )

    # ==================== Universe Refresh (Ops Safety) ====================
    universe_refresh_timeout_seconds: int = Field(
        default=300, ge=30, description="유니버스 갱신 전체 타임아웃 (초)"
    )
    universe_refresh_warn_budget: int = Field(
        default=50, ge=0, description="유니버스 갱신 경고 로그 최대 출력 수 (카테고리별)"
    )
    universe_refresh_error_list_limit: int = Field(
        default=50, ge=0, description="유니버스 갱신 응답 errors 리스트 최대 길이"
    )

    kis_api_backoff_sequence: list[int] = Field(
        default_factory=lambda: [5, 10, 20],
        description="429/5xx 연속 발생 시 대기 시간 시퀀스 (초)",
    )
    kis_api_backoff_trigger_errors: int = Field(
        default=3, ge=1, description="Backoff 발동 전 연속 오류 수"
    )
    kis_api_cooldown_seconds: int = Field(
        default=120, ge=1, description="Backoff 시퀀스 반복 후 쿨다운 시간 (초)"
    )
    kis_api_backoff_cycles_before_cooldown: int = Field(
        default=3, ge=1, description="쿨다운 전 backoff 시퀀스 반복 횟수"
    )
    order_min_interval_ms: int = Field(default=150, ge=0, description="주문 간 최소 간격 (ms)")
    order_same_symbol_interval_ms: int = Field(
        default=300, ge=0, description="동일 종목 연속 주문 최소 간격 (ms)"
    )
    order_response_timeout: float = Field(
        default=2.5, ge=0.5, description="주문/정정/취소 응답 타임아웃 (초)"
    )
    order_retry_delay_seconds: float = Field(
        default=5.0, ge=0.0, description="주문 실패 시 재시도 대기 시간 (초)"
    )
    order_max_amendments_per_order: int = Field(
        default=5, ge=1, description="단일 주문번호당 정정/취소 최대 횟수"
    )
    risk_max_exposure_per_symbol: float = Field(
        default=0.08, ge=0.0, le=1.0, description="종목당 최대 계좌 노출 비율"
    )
    risk_max_risk_per_trade: float = Field(
        default=0.02, ge=0.0, le=1.0, description="단일 트레이드 리스크 한도 (계좌 대비)"
    )
    risk_max_concurrent_positions: int = Field(
        default=3, ge=1, description="동시 보유 최대 종목 수"
    )
    risk_daily_loss_stop: float = Field(
        default=0.04, ge=0.0, le=1.0, description="일일 손실 중단 한도 (계좌 대비)"
    )

    # ==================== 자동매매 설정 ====================
    trading_environment: Literal["prod", "vps"] = Field(
        default="vps", description="거래 환경 (prod: 실전, vps: 모의)"
    )
    auto_reauth: bool = Field(default=True, description="토큰 자동 갱신 여부")
    smart_sleep: float = Field(default=0.1, ge=0.0, description="API 호출 간격 (초)")

    # ==================== 리스크 관리 ====================
    risk_daily_loss_limit: int = Field(
        default=1000000, ge=0, description="일일 최대 손실 한도 (원)"
    )
    risk_max_positions: int = Field(default=10, ge=1, description="최대 보유 종목 수")
    risk_max_order_amount: int = Field(
        default=10000000, ge=0, description="단일 주문 최대 금액 (원)"
    )

    # ==================== JWT 인증 ====================
    jwt_secret_key: str = Field(
        default="your-secret-key-here-change-in-production", description="JWT 시크릿 키"
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT 알고리즘")
    jwt_access_token_expire_minutes: int = Field(
        default=30, ge=1, description="JWT 액세스 토큰 만료 시간 (분)"
    )

    # ==================== CORS 설정 ====================
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8000"],
        description="CORS 허용 오리진",
    )
    cors_allow_credentials: bool = Field(default=True, description="CORS 인증 정보 허용")
    cors_allow_methods: list[str] = Field(
        default=["GET", "POST", "PUT", "DELETE", "OPTIONS"], description="CORS 허용 메서드"
    )
    cors_allow_headers: list[str] = Field(default=["*"], description="CORS 허용 헤더")

    # ==================== 로깅 설정 ====================
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="로그 레벨"
    )
    log_file: str = Field(default="logs/kis_trading.log", description="로그 파일 경로")
    log_max_bytes: int = Field(default=10485760, ge=1, description="로그 파일 최대 크기 (바이트)")
    log_backup_count: int = Field(default=5, ge=0, description="로그 파일 백업 개수")

    # ==================== 대시보드 설정 ====================
    dashboard_enabled: bool = Field(default=True, description="대시보드 활성화")
    dashboard_refresh_interval: int = Field(
        default=5, ge=1, description="대시보드 새로고침 간격 (초)"
    )

    # ==================== 관리자 접근 제어 ====================
    admin_allowed_ips: list[str] = Field(
        default=["127.0.0.1", "::1"],
        description=(
            "관리자 API 허용 IP 목록 (CIDR 표기 지원). 기본값은 localhost만 허용하며, "
            "환경 변수로 더 좁게/넓게 조정할 수 있습니다."
        ),
    )

    trusted_proxy_ips: list[str] = Field(
        default=["127.0.0.0/8", "::1/128"],
        description="X-Forwarded-For/X-Real-IP를 신뢰할 reverse proxy IP/CIDR 목록",
    )

    enable_admin_strategy_routes: bool = Field(
        default=False,
        description="전략 생성/수정/삭제 같은 관리자 전용 라우트를 API에 마운트할지 여부(기본: 비활성).",
    )

    # ==================== WebSocket 설정 ====================
    ws_max_connections: int = Field(default=100, ge=1, description="WebSocket 최대 연결 수")
    ws_ping_interval: int = Field(default=20, ge=1, description="WebSocket Ping 간격 (초)")
    ws_ping_timeout: int = Field(default=5, ge=1, description="WebSocket Pong 대기 시간 (초)")

    # ==================== 개발 도구 ====================
    uvicorn_reload: bool = Field(default=True, description="Uvicorn 자동 리로드")
    uvicorn_workers: int = Field(default=1, ge=1, description="Uvicorn 워커 수")

    # ==================== Telegram 알림 설정 ====================
    telegram_bot_token: str = Field(default="", description="Telegram Bot Token")
    telegram_chat_id: str = Field(default="", description="Telegram Chat ID")
    telegram_enabled: bool = Field(default=False, description="Telegram 알림 활성화")
    buy_notification_enabled: bool = Field(
        default=True, description="매수 추천 알림(11:30/14:30) 활성화"
    )
    sell_notification_enabled: bool = Field(
        default=False, description="매도 신호 알림(09:30/12:30) 활성화"
    )

    # ==================== 매수 전략(Fear Buy / GC) 설정 ====================
    gc_require_rsi_oversold: bool = Field(
        default=False,
        description="[#A] 골든크로스 매수 후보에 RSI 과매도 조건 요구(GC+RSI<=임계). "
        "기본 False=기존 라이브 동작 보존. True로 켜면 두 스캔 경로 모두 GC+RSI<=임계 적용",
    )
    gc_rsi_threshold: float = Field(
        default=40.0, ge=10, le=60, description="[#A] 골든크로스 매수 RSI 과매도 임계값"
    )
    fear_buy_window_enabled: bool = Field(
        default=True, description="[#3] 시장 공포 발생 후 개별 과매도 진입 허용(윈도우) 사용 여부"
    )
    fear_buy_window_days: int = Field(
        default=7, ge=1, le=20, description="[#3] 시장 공포 트리거 후 개별 과매도 진입 허용 거래일 수(N)"
    )
    fear_buy_rsi_threshold: float = Field(
        default=30.0, ge=10, le=45, description="[#3] Fear Buy 개별 과매도 RSI 임계값"
    )
    fear_buy_notify_enabled: bool = Field(
        default=False,
        description="[#2/#3] fear-buy 후보를 추천/Telegram 알림에 포함(opt-in, 기본 OFF). "
        "라이브 외부 알림 변경이므로 백테스트 확인 후 활성화 권장",
    )
    sell_regime_aware_enabled: bool = Field(
        default=False,
        description="[#8 defer] 매도에 시장 레짐 반영(기본 OFF). 하드 손절은 이 값과 무관하게 항상 적용",
    )
    sell_hard_stop_pct: float = Field(
        default=0.15, ge=0.05, le=0.40, description="[#7] 진입가 대비 하드 손절 비율"
    )
    sell_trend_stop_pct: float = Field(
        default=0.15, ge=0.05, le=0.40, description="[#7] 장기추세(MA165) 대비 이탈 손절 비율"
    )

    # ==================== DART API 설정 ====================
    dart_open_api_key: str = Field(default="", description="DART Open API 키")
    dart_api_base_url: str = Field(
        default="https://opendart.fss.or.kr", description="DART API Base URL"
    )
    dart_api_rate_limit: int = Field(default=10000, ge=1, description="DART API 일일 호출 제한")
    dart_api_timeout: int = Field(default=30, ge=1, description="DART API 타임아웃 (초)")

    # ==================== Computed Properties ====================

    @property
    def is_production(self) -> bool:
        """운영 환경 여부"""
        return self.env == "production"

    @property
    def is_development(self) -> bool:
        """개발 환경 여부"""
        return self.env == "development"

    @property
    def is_paper_trading(self) -> bool:
        """모의투자 여부"""
        return self.trading_environment == "vps"

    @property
    def kis_base_url(self) -> str:
        """현재 거래 환경의 KIS API Base URL"""
        return self.kis_vps_url if self.is_paper_trading else self.kis_prod_url

    @property
    def kis_ws_url(self) -> str:
        """현재 거래 환경의 KIS WebSocket URL"""
        return self.kis_vps_ws_url if self.is_paper_trading else self.kis_prod_ws_url

    @property
    def current_kis_app_key(self) -> str:
        """현재 거래 환경의 앱키"""
        return self.kis_paper_app_key if self.is_paper_trading else self.kis_app_key

    @property
    def current_kis_app_secret(self) -> str:
        """현재 거래 환경의 앱시크릿"""
        return self.kis_paper_app_secret if self.is_paper_trading else self.kis_app_secret

    @property
    def current_kis_account_no(self) -> str:
        """현재 거래 환경의 계좌번호"""
        return self.kis_paper_account_no if self.is_paper_trading else self.kis_account_no

    # ==================== Validators ====================

    @model_validator(mode="after")
    def validate_jwt_secret(self) -> "Settings":
        """운영 환경에서 기본 JWT 시크릿 사용 시 차단"""
        if (
            self.env == "production"
            and self.jwt_secret_key == "your-secret-key-here-change-in-production"
        ):
            raise ValueError(
                "JWT_SECRET_KEY가 기본값입니다. 운영 환경에서는 반드시 변경하세요. "
                "환경 변수 JWT_SECRET_KEY를 설정해주세요."
            )
        return self

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

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Async driver 강제 (greenlet 컨텍스트 오류 예방)"""
        if v.startswith("postgresql+asyncpg://"):
            return v
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql+psycopg2://"):
            return v.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql+psycopg://"):
            return v.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        return v


@lru_cache
def get_settings() -> Settings:
    """
    설정 싱글톤 인스턴스 반환

    @lru_cache 데코레이터를 사용하여 싱글톤 패턴 구현
    """
    return Settings()


# 전역 설정 인스턴스
settings = get_settings()
