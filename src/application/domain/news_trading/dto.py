# -*- coding: utf-8 -*-
"""
News-based Day Trading DTO - 뉴스 기반 단타 데이터 전송 객체

Phase 1-4 계획 문서 기반 설계:
- 뉴스 분석 및 종목 매핑
- 복합 조건 필터링 (거래량, 상승률, 수급, 호가)
- 분할 익절 + 모멘텀 기반 동적 청산
- 리스크 관리 (SafetyGuard)
"""

from datetime import datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from src.application.common.dto import BaseDTO


# ==================== Enums ====================


class NewsEventType(str, Enum):
    """뉴스 이벤트 유형 (Phase 1 - process_improvement_and_checklist.md 1.2 기반)"""

    POLICY_REGULATION = "policy_regulation"  # 정책/규제: 규제 완화·강화, 정부 지원, 세제 변경
    EARNINGS = "earnings"  # 실적: 어닝 서프라이즈/쇼크, 가이던스 상향/하향
    CORPORATE_ACTION = "corporate_action"  # 기업 액션: M&A, 대규모 수주, 자사주 매입, IPO
    SECTOR_THEME = "sector_theme"  # 산업/테마: 전기차, 2차전지, AI 등 섹터 관련 이슈
    GLOBAL_MACRO = "global_macro"  # 글로벌 매크로: 금리, 환율, 국제 정세
    POLITICAL = "political"  # 정치적 이벤트


class MomentumSignal(str, Enum):
    """모멘텀 약화 신호 (Phase 2 기반)"""

    PRICE_DECEL = "PRICE_DECEL"  # 가격 가속도 감소 (가중치: 2)
    TICK_SLOWDOWN = "TICK_SLOWDOWN"  # 체결 속도 감소 (가중치: 1)
    ORDER_IMBALANCE = "ORDER_IMBALANCE"  # 호가 불균형 (가중치: 2)
    VOLUME_DROP = "VOLUME_DROP"  # 거래량 감소 (가중치: 1)


class ExitReason(str, Enum):
    """청산 사유"""

    FIRST_PROFIT_TAKING = "first_profit_taking"  # 1차 익절 (+5%)
    SECOND_PROFIT_TAKING = "second_profit_taking"  # 2차 익절 (+8%)
    MOMENTUM_EXIT = "momentum_exit"  # 모멘텀 약화 익절
    TIME_EXIT = "time_exit"  # 시간 청산 (10:40)
    STOP_LOSS = "stop_loss"  # 손절 (-7%)
    DAILY_LOSS_LIMIT = "daily_loss_limit"  # 일일 손실 한도
    MANUAL = "manual"  # 수동 청산


class TradingStatus(str, Enum):
    """거래 상태"""

    WAITING = "waiting"  # 대기 중 (09:00~09:10)
    MONITORING = "monitoring"  # 모니터링 중
    POSITION_OPEN = "position_open"  # 포지션 보유 중
    PARTIALLY_CLOSED = "partially_closed"  # 부분 청산됨 (1차 익절 후)
    CLOSED = "closed"  # 완전 청산됨
    STOPPED = "stopped"  # 중단됨 (한도 도달 등)


# ==================== News Analysis DTOs ====================


class NewsItemDTO(BaseDTO):
    """개별 뉴스 아이템"""

    title: str = Field(description="뉴스 제목")
    content: str | None = Field(default=None, description="뉴스 본문")
    source: str = Field(description="뉴스 출처 (네이버, 다음, 증권사 등)")
    published_at: datetime = Field(description="발행 시각")
    url: str | None = Field(default=None, description="뉴스 URL")
    event_type: NewsEventType | None = Field(default=None, description="이벤트 유형")
    keywords: list[str] = Field(default_factory=list, description="추출된 키워드")
    related_symbols: list[str] = Field(default_factory=list, description="관련 종목코드")


class NewsScoreDTO(BaseDTO):
    """
    뉴스 스코어 DTO (process_improvement_and_checklist.md 1.3 기반)

    news_score = 영향도(0~5) + 신선도(0~3) + 확산도(0~2) = 총 0~10점
    전략 대상: news_score >= 6
    """

    impact_score: float = Field(
        default=0.0,
        description="영향도 점수 (0~5): 헤드라인 키워드, 본문 길이, 주요 매체 여부",
        ge=0.0,
        le=5.0,
    )
    freshness_score: float = Field(
        default=0.0,
        description="신선도 점수 (0~3): 발생 시점 가중치 (전일 18~22시 최고)",
        ge=0.0,
        le=3.0,
    )
    spread_score: float = Field(
        default=0.0,
        description="확산도 점수 (0~2): 동일 이벤트 기사 수, 매체 다양성",
        ge=0.0,
        le=2.0,
    )

    @property
    def total_score(self) -> float:
        """총 뉴스 스코어 (0~10)"""
        return self.impact_score + self.freshness_score + self.spread_score


class NewsAnalysisRequestDTO(BaseDTO):
    """뉴스 분석 요청 DTO"""

    target_date: datetime = Field(description="분석 대상 날짜")
    news_items: list[NewsItemDTO] = Field(default_factory=list, description="분석할 뉴스 목록")
    min_news_score: float = Field(
        default=6.0, description="최소 뉴스 스코어 임계값", ge=0.0, le=10.0
    )


class NewsAnalysisResultDTO(BaseDTO):
    """뉴스 분석 결과 DTO"""

    analysis_date: datetime = Field(description="분석 일자")
    total_news_count: int = Field(description="분석된 뉴스 총 수")
    filtered_news_count: int = Field(description="필터링 후 뉴스 수")
    candidate_symbols: list[str] = Field(description="후보 종목 리스트")
    symbol_scores: dict[str, float] = Field(
        default_factory=dict, description="종목별 뉴스 스코어"
    )
    event_type_distribution: dict[str, int] = Field(
        default_factory=dict, description="이벤트 유형별 분포"
    )


# ==================== Stock Selection DTOs ====================


class StockCandidateDTO(BaseDTO):
    """
    종목 후보 DTO

    09:00~09:10 복합 조건 필터링 결과
    """

    symbol: str = Field(description="종목코드")
    name: str = Field(description="종목명")
    current_price: Decimal = Field(description="현재가")
    open_price: Decimal = Field(description="시가")
    prev_close: Decimal = Field(description="전일 종가")

    # 복합 조건 데이터 (Phase 3 - morphological_analysis.md 기반)
    volume_ratio: float = Field(description="전일 대비 거래량 배수", ge=0.0)
    price_change_rate: float = Field(description="시가 대비 상승률 (%)")
    foreign_net_buy: int = Field(default=0, description="외인 순매수 금액 (백만원)")
    institution_net_buy: int = Field(default=0, description="기관 순매수 금액 (백만원)")
    bid_ask_ratio: float = Field(description="매수잔량/매도잔량 비율", ge=0.0)
    market_cap: Decimal = Field(description="시가총액 (억원)")
    spread_rate: float = Field(description="호가 스프레드 (%)", ge=0.0)

    # 뉴스 관련
    news_score: float = Field(default=0.0, description="뉴스 스코어", ge=0.0, le=10.0)
    event_types: list[NewsEventType] = Field(default_factory=list, description="관련 이벤트 유형")

    # 필터링 결과
    passes_volume_filter: bool = Field(default=False, description="거래량 조건 통과")
    passes_price_filter: bool = Field(default=False, description="상승률 조건 통과")
    passes_supply_filter: bool = Field(default=False, description="수급 조건 통과")
    passes_orderbook_filter: bool = Field(default=False, description="호가 조건 통과")
    passes_all_filters: bool = Field(default=False, description="모든 조건 통과")


class StockRankingDTO(BaseDTO):
    """
    종목 랭킹 DTO (process_improvement_and_checklist.md 2.2 기반)

    rank_score = w1×news_score + w2×volume_ratio + w3×price_change + w4×bid_ask_ratio + w5×liquidity
    """

    symbol: str = Field(description="종목코드")
    name: str = Field(description="종목명")
    rank: int = Field(description="순위", ge=1)
    rank_score: float = Field(description="랭킹 스코어")

    # 점수 구성요소
    news_score_weighted: float = Field(description="뉴스 스코어 (가중치 적용)")
    volume_score_weighted: float = Field(description="거래량 스코어 (가중치 적용)")
    price_score_weighted: float = Field(description="상승률 스코어 (가중치 적용)")
    orderbook_score_weighted: float = Field(description="호가 비율 스코어 (가중치 적용)")
    liquidity_score_weighted: float = Field(description="유동성 스코어 (가중치 적용)")

    # 원본 데이터 참조
    candidate: StockCandidateDTO = Field(description="후보 종목 정보")


class StockSelectionConfigDTO(BaseDTO):
    """
    종목 선별 설정 DTO (parameter_tuning_and_checklist.md 2.1 기반)

    튜닝 대상: 거래량 배수, 시가 대비 상승률 (각 2~3개 값만)
    고정 권장: 수급 조건, 호가 비율, 시가총액, 스프레드
    """

    # 핵심 튜닝 파라미터
    min_volume_ratio: float = Field(
        default=3.0, description="최소 거래량 배수 (튜닝 대상: 3, 5)", ge=1.0, le=20.0
    )
    min_price_change_rate: float = Field(
        default=2.0, description="최소 시가 대비 상승률 % (튜닝 대상: +2%, +3%)", ge=0.0, le=10.0
    )

    # 고정 권장 파라미터
    require_foreign_net_buy: bool = Field(
        default=True, description="외인 순매수 필수 여부"
    )
    min_bid_ask_ratio: float = Field(
        default=1.2, description="최소 매수/매도 잔량 비율", ge=1.0, le=3.0
    )
    min_market_cap: Decimal = Field(
        default=Decimal("3000"), description="최소 시가총액 (억원)", ge=Decimal("100")
    )
    max_spread_rate: float = Field(
        default=1.0, description="최대 호가 스프레드 (%)", ge=0.0, le=5.0
    )

    # 랭킹 가중치 (process_improvement_and_checklist.md 2.2)
    news_weight: float = Field(default=2.0, description="뉴스 스코어 가중치", ge=0.0, le=5.0)
    volume_weight: float = Field(default=1.0, description="거래량 가중치", ge=0.0, le=5.0)
    price_weight: float = Field(default=1.0, description="상승률 가중치", ge=0.0, le=5.0)
    orderbook_weight: float = Field(default=1.0, description="호가 비율 가중치", ge=0.0, le=5.0)
    liquidity_weight: float = Field(default=1.0, description="유동성 가중치", ge=0.0, le=5.0)

    # No-trade day 규칙 (process_improvement_and_checklist.md 2.3)
    min_top_rank_score: float = Field(
        default=6.0, description="상위 종목 최소 랭킹 스코어 (미달 시 매매 중단)", ge=0.0
    )
    min_top_news_score: float = Field(
        default=6.0, description="상위 종목 최소 뉴스 스코어 (미달 시 매매 중단)", ge=0.0
    )
    max_candidates: int = Field(
        default=3, description="최대 진입 대상 종목 수 (Phase 4)", ge=1, le=10
    )


class StockSelectionResultDTO(BaseDTO):
    """종목 선별 결과 DTO"""

    selection_time: datetime = Field(description="선별 시각")
    total_candidates: int = Field(description="전체 후보 종목 수")
    filtered_candidates: int = Field(description="필터링 후 종목 수")
    ranked_stocks: list[StockRankingDTO] = Field(description="랭킹 정렬된 종목 목록")
    selected_symbols: list[str] = Field(description="최종 선정 종목 (상위 N개)")
    is_no_trade_day: bool = Field(
        default=False, description="No-trade day 여부 (조건 미달)"
    )
    no_trade_reason: str | None = Field(
        default=None, description="No-trade day 사유"
    )


# ==================== Entry/Exit Condition DTOs ====================


class EntryConditionConfigDTO(BaseDTO):
    """
    진입 조건 설정 DTO (Phase 1 기반)

    - 진입 시간: 09:10 고정
    - 관찰 시간: 09:00~09:10 (10분)
    """

    observation_start_time: time = Field(
        default=time(9, 0), description="관찰 시작 시간"
    )
    entry_time: time = Field(
        default=time(9, 10), description="진입 시간 (고정)"
    )
    use_market_order: bool = Field(
        default=True, description="시장가 주문 사용 여부 (유동성 좋은 종목 한정)"
    )
    entry_split_count: int = Field(
        default=1, description="진입 분할 횟수 (v1에서는 1=일괄 진입)", ge=1, le=3
    )


class StagedProfitTakingConfig(BaseDTO):
    """
    분할 익절 설정 DTO (Phase 2 - cross_pollination.md 기반)

    1차 익절: +5% → 50% 물량
    2차 익절: +8% → 잔여 전량
    """

    first_take_profit_rate: float = Field(
        default=0.05, description="1차 익절 수익률 (튜닝 대상: +4%, +5%)", ge=0.01, le=0.15
    )
    first_take_profit_ratio: float = Field(
        default=0.5, description="1차 익절 물량 비율 (고정: 50%)", ge=0.1, le=0.9
    )
    second_take_profit_rate: float = Field(
        default=0.08, description="2차 익절 수익률 (고정: +8%)", ge=0.02, le=0.2
    )


class MomentumExitConfigDTO(BaseDTO):
    """
    모멘텀 기반 동적 익절 설정 DTO (Phase 2 기반)

    신호 가중치:
    - PRICE_DECEL: 2 (가격 가속도 감소)
    - TICK_SLOWDOWN: 1 (체결 속도 감소)
    - ORDER_IMBALANCE: 2 (호가 불균형)
    - VOLUME_DROP: 1 (거래량 감소)

    가중치 합 >= 3 이면 모멘텀 약화 판정
    """

    # 모멘텀 감지 임계값 (parameter_tuning_and_checklist.md 2.4)
    price_decel_consecutive: int = Field(
        default=2, description="가격 가속도 하락 연속 횟수 기준", ge=1, le=5
    )
    tick_slowdown_threshold: float = Field(
        default=0.5, description="체결 속도 감소 임계 (이전 대비 비율)", ge=0.1, le=0.9
    )
    order_imbalance_threshold: float = Field(
        default=1.2, description="매도/매수 잔량 비율 임계", ge=1.0, le=3.0
    )
    volume_drop_threshold: float = Field(
        default=0.3, description="거래량 감소 임계 (이전 대비 비율)", ge=0.1, le=0.9
    )

    # 신호 가중치
    price_decel_weight: int = Field(default=2, description="가격 가속도 신호 가중치", ge=1, le=5)
    tick_slowdown_weight: int = Field(default=1, description="체결 속도 신호 가중치", ge=1, le=5)
    order_imbalance_weight: int = Field(default=2, description="호가 불균형 신호 가중치", ge=1, le=5)
    volume_drop_weight: int = Field(default=1, description="거래량 감소 신호 가중치", ge=1, le=5)

    # 익절 트리거
    momentum_weakness_threshold: int = Field(
        default=3, description="모멘텀 약화 판정 임계 (가중치 합)", ge=1, le=10
    )
    require_first_profit: bool = Field(
        default=True, description="1차 익절 후에만 모멘텀 익절 적용"
    )


class ExitConditionConfigDTO(BaseDTO):
    """
    청산 조건 설정 DTO (Phase 2, 4 통합)
    """

    # 분할 익절
    staged_profit_taking: StagedProfitTakingConfig = Field(
        default_factory=StagedProfitTakingConfig
    )

    # 모멘텀 기반 익절
    momentum_exit: MomentumExitConfigDTO = Field(
        default_factory=MomentumExitConfigDTO
    )

    # 손절 (Phase 1)
    stop_loss_rate: float = Field(
        default=-0.07, description="손절 수익률 (튜닝 대상: -5%, -7%)", ge=-0.2, le=0.0
    )

    # 시간 청산 (Phase 1)
    force_exit_time: time = Field(
        default=time(10, 40), description="강제 청산 시간 (고정: 10:40)"
    )


# ==================== Risk Management DTOs ====================


class PositionSizingConfigDTO(BaseDTO):
    """
    포지션 사이징 설정 DTO (Phase 4 - failure_analysis.md 기반)

    - 종목당 최대 비중: 8%
    - 동시 보유 최대: 3종목
    - 일일 최대 투자금: 50%
    """

    max_position_ratio: float = Field(
        default=0.08, description="종목당 최대 비중 (8%)", ge=0.05, le=0.5
    )
    max_concurrent_positions: int = Field(
        default=3, description="동시 보유 최대 종목 수", ge=1, le=10
    )
    max_daily_investment_ratio: float = Field(
        default=0.5, description="일일 최대 투자 비중 (50%)", ge=0.1, le=1.0
    )

    # 변동성 기반 사이징 (process_improvement_and_checklist.md 2.4)
    use_volatility_sizing: bool = Field(
        default=False, description="변동성 기반 포지션 사이징 사용"
    )
    per_trade_risk_ratio: float = Field(
        default=0.02, description="거래당 계좌 리스크 비율 (2%)", ge=0.005, le=0.05
    )


class RiskLimitConfigDTO(BaseDTO):
    """
    리스크 한도 설정 DTO (Phase 4 - failure_analysis.md Part 3 기반)
    """

    # 손실 한도
    daily_loss_limit_ratio: float = Field(
        default=-0.04, description="일일 손실 한도 (-4%)", ge=-0.1, le=0.0
    )
    weekly_loss_limit_ratio: float = Field(
        default=-0.07, description="주간 손실 한도 (-7%)", ge=-0.2, le=0.0
    )
    monthly_loss_limit_ratio: float = Field(
        default=-0.15, description="월간 손실 한도 (-15%)", ge=-0.3, le=0.0
    )

    # 거래 제한
    max_daily_trades: int = Field(
        default=3, description="일일 최대 거래 횟수", ge=1, le=10
    )
    max_consecutive_losses: int = Field(
        default=3, description="연속 손실 허용 횟수 (초과 시 당일 매매 중단)", ge=1, le=10
    )
    cooldown_after_loss_minutes: int = Field(
        default=30, description="손절 후 쿨다운 시간 (분)", ge=0, le=120
    )

    # 시장 상황 제한
    market_crash_threshold: float = Field(
        default=-0.02, description="시장 급락 임계 (코스피 -2%)", ge=-0.1, le=0.0
    )


class SafetyGuardConfigDTO(BaseDTO):
    """
    안전장치 설정 DTO (Phase 4 - failure_analysis.md Part 4 기반)

    can_trade() 체크 조건:
    1. 일일 손실 한도
    2. 거래 횟수 한도
    3. 연속 손실 횟수
    4. 시장 상황 (코스피 급락)
    """

    position_sizing: PositionSizingConfigDTO = Field(
        default_factory=PositionSizingConfigDTO
    )
    risk_limits: RiskLimitConfigDTO = Field(default_factory=RiskLimitConfigDTO)

    # 안전장치 활성화 옵션
    enable_daily_loss_guard: bool = Field(default=True, description="일일 손실 한도 가드 활성화")
    enable_trade_count_guard: bool = Field(default=True, description="거래 횟수 가드 활성화")
    enable_consecutive_loss_guard: bool = Field(
        default=True, description="연속 손실 가드 활성화"
    )
    enable_market_crash_guard: bool = Field(default=True, description="시장 급락 가드 활성화")


# ==================== Trading Session DTOs ====================


class TradingSessionConfigDTO(BaseDTO):
    """
    거래 세션 설정 DTO (Phase 1~4 통합)

    타임라인:
    - 전일 18:00~19:00: 뉴스 스크래핑 & 종목 리스트 생성
    - 당일 09:00~09:10: 복합 조건 확인
    - 당일 09:10: 매수 진입
    - 당일 09:10~10:40: 보유 (익절/손절 모니터링)
    - 당일 10:40: 강제 청산
    """

    # 뉴스 분석 시간
    news_analysis_start_time: time = Field(
        default=time(18, 0), description="뉴스 분석 시작 시간 (전일)"
    )
    news_analysis_end_time: time = Field(
        default=time(19, 0), description="뉴스 분석 종료 시간 (전일)"
    )

    # 진입 설정
    entry_config: EntryConditionConfigDTO = Field(default_factory=EntryConditionConfigDTO)

    # 청산 설정
    exit_config: ExitConditionConfigDTO = Field(default_factory=ExitConditionConfigDTO)

    # 모니터링 주기 (초)
    monitoring_interval_seconds: int = Field(
        default=5, description="모니터링 주기 (초)", ge=1, le=60
    )


class TradingSignalDTO(BaseDTO):
    """거래 신호 DTO"""

    signal_time: datetime = Field(description="신호 발생 시각")
    symbol: str = Field(description="종목코드")
    signal_type: str = Field(
        description="신호 유형", pattern="^(buy|sell|hold)$"
    )
    reason: str = Field(description="신호 발생 사유")
    price: Decimal = Field(description="신호 발생 가격")
    quantity: int | None = Field(default=None, description="주문 수량")
    exit_reason: ExitReason | None = Field(default=None, description="청산 사유 (sell 시)")

    # 모멘텀 신호 (sell 시)
    momentum_signals: list[MomentumSignal] = Field(
        default_factory=list, description="감지된 모멘텀 신호"
    )
    momentum_weight_sum: int = Field(default=0, description="모멘텀 신호 가중치 합")


class TradingResultDTO(BaseDTO):
    """거래 결과 DTO"""

    trade_id: str = Field(description="거래 ID")
    symbol: str = Field(description="종목코드")
    name: str = Field(description="종목명")

    # 진입 정보
    entry_time: datetime = Field(description="진입 시각")
    entry_price: Decimal = Field(description="진입 가격")
    entry_quantity: int = Field(description="진입 수량")

    # 청산 정보 (1차 익절)
    first_exit_time: datetime | None = Field(default=None, description="1차 청산 시각")
    first_exit_price: Decimal | None = Field(default=None, description="1차 청산 가격")
    first_exit_quantity: int | None = Field(default=None, description="1차 청산 수량")
    first_exit_reason: ExitReason | None = Field(default=None, description="1차 청산 사유")

    # 청산 정보 (최종)
    final_exit_time: datetime | None = Field(default=None, description="최종 청산 시각")
    final_exit_price: Decimal | None = Field(default=None, description="최종 청산 가격")
    final_exit_quantity: int | None = Field(default=None, description="최종 청산 수량")
    final_exit_reason: ExitReason | None = Field(default=None, description="최종 청산 사유")

    # 손익
    realized_profit: Decimal = Field(default=Decimal("0"), description="실현 손익")
    realized_profit_rate: float = Field(default=0.0, description="실현 손익률 (%)")
    commission: Decimal = Field(default=Decimal("0"), description="수수료")
    tax: Decimal = Field(default=Decimal("0"), description="세금")

    # 상태
    status: TradingStatus = Field(description="거래 상태")
    holding_minutes: int = Field(default=0, description="보유 시간 (분)")

    # 뉴스/모멘텀 메타데이터
    news_score: float = Field(default=0.0, description="뉴스 스코어")
    event_types: list[NewsEventType] = Field(default_factory=list, description="관련 이벤트 유형")
    momentum_signals_detected: list[MomentumSignal] = Field(
        default_factory=list, description="감지된 모멘텀 신호"
    )


# ==================== Strategy Config DTO ====================


class NewsTradingStrategyConfigDTO(BaseDTO):
    """
    뉴스 기반 단타 전략 통합 설정 DTO

    Phase 1~4 계획 문서 기반 설정 통합
    - 종목 선별 (복합 조건 필터링)
    - 진입/청산 조건 (분할 익절 + 모멘텀)
    - 리스크 관리 (SafetyGuard)
    """

    # 전략 기본 정보
    name: str = Field(default="뉴스 기반 장 초반 단타", description="전략명")
    description: str | None = Field(default=None, description="전략 설명")
    version: str = Field(default="1.0.0", description="전략 버전")

    # 종목 선별 설정
    stock_selection: StockSelectionConfigDTO = Field(
        default_factory=StockSelectionConfigDTO
    )

    # 거래 세션 설정
    trading_session: TradingSessionConfigDTO = Field(
        default_factory=TradingSessionConfigDTO
    )

    # 안전장치 설정
    safety_guard: SafetyGuardConfigDTO = Field(default_factory=SafetyGuardConfigDTO)

    # 백테스팅 설정
    backtest_commission_rate: float = Field(
        default=0.00015, description="백테스트 수수료율 (0.015%)", ge=0.0, le=0.01
    )
    backtest_tax_rate: float = Field(
        default=0.0023, description="백테스트 세금율 (0.23%)", ge=0.0, le=0.01
    )
    backtest_slippage_rate: float = Field(
        default=0.001, description="백테스트 슬리피지율 (0.1%)", ge=0.0, le=0.01
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Strategy name cannot be empty")
        return v.strip()


# ==================== Backtest Request/Result DTOs ====================


class NewsTradingBacktestRequestDTO(BaseDTO):
    """뉴스 기반 단타 백테스트 요청 DTO"""

    symbols: list[str] = Field(description="대상 종목 리스트", min_length=1)
    start_date: datetime = Field(description="시작일")
    end_date: datetime = Field(description="종료일")
    initial_capital: Decimal = Field(
        default=Decimal("10_000_000"), description="초기 자본", ge=Decimal("1_000_000")
    )
    strategy_config: NewsTradingStrategyConfigDTO = Field(
        default_factory=NewsTradingStrategyConfigDTO
    )

    @field_validator("end_date")
    @classmethod
    def validate_dates(cls, v: datetime, info) -> datetime:
        start_date = info.data.get("start_date")
        if start_date and v <= start_date:
            raise ValueError("end_date must be after start_date")
        return v


class NewsTradingBacktestResultDTO(BaseDTO):
    """뉴스 기반 단타 백테스트 결과 DTO"""

    # 기본 정보
    start_date: datetime = Field(description="시작일")
    end_date: datetime = Field(description="종료일")
    initial_capital: Decimal = Field(description="초기 자본")
    final_capital: Decimal = Field(description="최종 자본")
    strategy_config: NewsTradingStrategyConfigDTO = Field(description="전략 설정")

    # 수익 지표
    total_return: float = Field(description="총 수익률 (%)")
    annualized_return: float = Field(description="연환산 수익률 (%)")
    mdd: float = Field(description="최대 낙폭 (%)")
    sharpe_ratio: float = Field(description="Sharpe Ratio")

    # 거래 통계
    total_trades: int = Field(description="총 거래 횟수")
    winning_trades: int = Field(description="승리 거래 수")
    losing_trades: int = Field(description="패배 거래 수")
    win_rate: float = Field(description="승률 (%)")
    avg_win: float = Field(description="평균 수익 (%)")
    avg_loss: float = Field(description="평균 손실 (%)")
    profit_factor: float = Field(description="Profit Factor")

    # 청산 사유별 통계
    exit_reason_stats: dict[str, int] = Field(
        default_factory=dict, description="청산 사유별 횟수"
    )

    # 뉴스 타입별 성과
    event_type_performance: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="이벤트 타입별 성과"
    )

    # 거래 내역
    trades: list[TradingResultDTO] = Field(default_factory=list, description="거래 내역")

    # No-trade day 통계
    total_trading_days: int = Field(description="전체 거래일 수")
    no_trade_days: int = Field(description="No-trade day 수")
    active_trading_days: int = Field(description="실제 거래일 수")
