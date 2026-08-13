# -*- coding: utf-8 -*-
"""
Public Strategy DTO - 공개 전략 포털(/page/) 전용 데이터 전송 객체

내부 DTO(GoldenCrossScanListDTO/GoldenCrossRecommendationDTO)를 그대로 노출하지 않고
공개 허용 필드만 담은 별도 계약을 정의한다.
내부 DTO에 필드가 추가되어도 여기 projection을 거치지 않으면 외부로 노출되지 않는다.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, overload

from pydantic import Field

from src.application.common.dto import BaseDTO
from src.application.domain.strategy.dto import (
    GoldenCrossRecommendationDTO,
    GoldenCrossScanListDTO,
)

# 공개 스캔에서 허용하는 시장 값 (wire 값의 정적 타입).
# 현재 운영에서 실제 허용되는 값(가용성)은 PublicStrategyService/capability가 결정한다.
PublicMarket = Literal["KOSPI", "KOSDAQ", "ETF"]

# 운영 유니버스 모드 (ETF_UNIVERSE_ENABLED 설정에서 파생)
PublicUniverseMode = Literal["ETF_ONLY", "STOCKS"]

# 공개 스캔 결과 요약 상태
PublicScanOutcome = Literal["MATCHES_FOUND", "NO_MATCHES"]

# 내부 스캔은 전체 집계를 유지하되 공개 페이지에는 추천 우선순위 상위 N개만 전달한다.
# BuyStrategyService가 canonical 신호 등급 + screening_score 순으로 정렬한 결과를 보존한다.
PUBLIC_SCAN_MAX_RESULTS = 20


@overload
def _ensure_aware(dt: datetime) -> datetime: ...


@overload
def _ensure_aware(dt: None) -> None: ...


def _ensure_aware(dt: datetime | None) -> datetime | None:
    """naive datetime을 UTC로 간주해 tz-aware로 정규화.

    scan_time은 내부에서 datetime.now()(컨테이너 TZ=UTC)로 생성된 naive 값이라
    오프셋 없이 내려보내면 브라우저가 로컬 시각으로 오해한다. 오프셋을 붙여
    절대 시각을 명확히 한다. 이미 tz-aware면 그대로 둔다.
    """
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ==================== Request DTOs ====================


class PublicGoldenCrossScanRequestDTO(BaseDTO):
    """공개 골든크로스 스캔 요청 (시장 선택만 허용)"""

    market: PublicMarket | None = Field(
        default=None, description="시장 구분 (KOSPI/KOSDAQ/ETF, None=전체)"
    )


# ==================== Scan Capabilities DTOs ====================


class PublicScanMarketOptionDTO(BaseDTO):
    """공개 스캔에서 실제 선택 가능한 시장 옵션"""

    value: PublicMarket = Field(description="시장 코드")
    label: str = Field(description="화면 표시용 라벨")
    active_count: int = Field(description="실제 스캔 가능(활성) 종목 수")


class PublicScanCapabilitiesDTO(BaseDTO):
    """공개 스캔 가용성 (설정상 허용 시장 ∩ 실제 활성 유니버스)"""

    scan_enabled: bool = Field(description="스캔 실행 가능 여부 (가용 시장 1개 이상)")
    universe_mode: PublicUniverseMode = Field(description="현재 유니버스 운영 모드")
    allow_all: bool = Field(description="복수 시장 통합('전체') 스캔 허용 여부")
    default_market: PublicMarket | None = Field(
        default=None, description="기본 선택 시장 (allow_all이면 None)"
    )
    markets: list[PublicScanMarketOptionDTO] = Field(
        default_factory=list, description="선택 가능한 시장 목록 (KOSPI, KOSDAQ, ETF 순)"
    )
    notice: str | None = Field(default=None, description="상태 안내 문구")


# ==================== Scan Response DTOs ====================


class PublicScanStockDTO(BaseDTO):
    """공개 스캔 결과 종목 (공개 허용 필드만)"""

    symbol: str = Field(description="종목코드")
    name: str = Field(description="종목명")
    market: str = Field(description="시장 구분")
    current_price: Decimal = Field(description="현재가")
    ma_gap_ratio: float = Field(description="MA 갭 비율 (%)")
    stoch_k: float = Field(description="Stochastic %K")
    stoch_d: float = Field(description="Stochastic %D")
    gc_state: str = Field(description="골든크로스 신호 상태")


class PublicGoldenCrossScanDTO(BaseDTO):
    """공개 골든크로스 스캔 결과 (집계 + 종목 목록 + 스캔 시각)"""

    stocks: list[PublicScanStockDTO] = Field(
        default_factory=list,
        description=f"추천 우선순위 상위 {PUBLIC_SCAN_MAX_RESULTS}개 스캔 결과",
        max_length=PUBLIC_SCAN_MAX_RESULTS,
    )
    total_scanned: int = Field(description="스캔한 전체 종목 수")
    gc_active_count: int = Field(description="골든크로스 활성 종목 수")
    pullback_waiting_count: int = Field(default=0, description="눌림목 대기 종목 수")
    buy_interest_count: int = Field(default=0, description="매수 관심 종목 수")
    ready_to_buy_count: int = Field(default=0, description="매수 준비 종목 수")
    optimal_buy_count: int = Field(default=0, description="매수 적기 종목 수")
    scan_time: datetime = Field(description="스캔 시각")
    error_count: int = Field(default=0, description="스캔 중 오류 종목 수 (일반화된 요약)")
    market: PublicMarket | None = Field(
        default=None,
        description="실제 적용된 시장 범위 (복수 개별주 시장을 함께 스캔한 경우만 None)",
    )
    outcome: PublicScanOutcome = Field(description="스캔 결과 상태")

    @classmethod
    def from_internal(
        cls,
        result: GoldenCrossScanListDTO,
        market: PublicMarket | None,
    ) -> "PublicGoldenCrossScanDTO":
        """내부 스캔 DTO → 공개 projection (허용 필드만 명시적으로 복사)

        Args:
            result: 내부 스캔 결과
            market: 실제 적용된 시장 범위 (서비스가 가용성 검사 후 정규화한 값).
                호출 전에 total_scanned=0 경쟁 조건 검사가 끝났다고 가정하므로,
                outcome은 stocks 유무만으로 판단한다.
        """
        outcome: PublicScanOutcome = "MATCHES_FOUND" if result.stocks else "NO_MATCHES"
        return cls(
            stocks=[
                PublicScanStockDTO(
                    symbol=stock.symbol,
                    name=stock.name,
                    market=stock.market,
                    current_price=stock.current_price,
                    ma_gap_ratio=stock.ma_gap_ratio,
                    stoch_k=stock.stoch_k,
                    stoch_d=stock.stoch_d,
                    gc_state=stock.gc_state,
                )
                for stock in result.stocks[:PUBLIC_SCAN_MAX_RESULTS]
            ],
            total_scanned=result.total_scanned,
            gc_active_count=result.gc_active_count,
            pullback_waiting_count=result.pullback_waiting_count,
            buy_interest_count=result.buy_interest_count,
            ready_to_buy_count=result.ready_to_buy_count,
            optimal_buy_count=result.optimal_buy_count,
            scan_time=_ensure_aware(result.scan_time),
            error_count=len(result.errors),
            market=market,
            outcome=outcome,
        )


# ==================== Recommendation Snapshot DTOs ====================


class PublicRecommendationStockDTO(BaseDTO):
    """공개 추천 Top 종목 (공개 허용 필드만)"""

    symbol: str = Field(description="종목코드")
    name: str = Field(description="종목명")
    market: str = Field(description="시장 구분")
    current_price: Decimal = Field(description="현재가")
    gc_state: str = Field(description="골든크로스 신호 상태")
    recommendation_score: float | None = Field(default=None, description="추천 점수")


class PublicIndustrySummaryDTO(BaseDTO):
    """공개 추천 Top 업종"""

    industry_name: str | None = Field(default=None, description="업종명")
    count: int = Field(description="해당 업종 종목 수")


class PublicRecommendationSnapshotDTO(BaseDTO):
    """공개 추천 스냅샷 (스케줄러가 생성한 캐시 전용)

    캐시가 없거나 만료되면 available=false로 반환한다.
    """

    available: bool = Field(default=False, description="스냅샷 존재 여부")
    generated_at: datetime | None = Field(default=None, description="스냅샷 생성 시각")
    scan_time: datetime | None = Field(default=None, description="기준 스캔 시각")
    buy_candidate_count: int = Field(default=0, description="매수 후보 종목 수")
    top_stocks: list[PublicRecommendationStockDTO] = Field(
        default_factory=list, description="Top 추천 종목"
    )
    top_industries: list[PublicIndustrySummaryDTO] = Field(
        default_factory=list, description="Top 업종"
    )
    selection_criteria: list[str] = Field(default_factory=list, description="추천 선정 기준")

    @classmethod
    def empty(cls) -> "PublicRecommendationSnapshotDTO":
        """캐시 없음/만료 상태"""
        return cls(available=False)

    @classmethod
    def from_internal(
        cls,
        recommendation: GoldenCrossRecommendationDTO,
        generated_at: datetime,
    ) -> "PublicRecommendationSnapshotDTO":
        """내부 추천 DTO → 공개 스냅샷 projection (허용 필드만 명시적으로 복사)

        내부 경고/오류 전문(errors), 재무 필터 상세, 상태별 카운트는 노출하지 않는다.
        """
        return cls(
            available=True,
            generated_at=_ensure_aware(generated_at),
            scan_time=_ensure_aware(recommendation.scan_time),
            buy_candidate_count=recommendation.buy_candidate_count,
            top_stocks=[
                PublicRecommendationStockDTO(
                    symbol=stock.symbol,
                    name=stock.name,
                    market=stock.market,
                    current_price=stock.current_price,
                    gc_state=stock.gc_state,
                    recommendation_score=stock.recommendation_score,
                )
                for stock in recommendation.top_stocks
            ],
            top_industries=[
                PublicIndustrySummaryDTO(
                    industry_name=industry.industry_name,
                    count=industry.count,
                )
                for industry in recommendation.top_industries
            ],
            selection_criteria=list(recommendation.selection_criteria),
        )
