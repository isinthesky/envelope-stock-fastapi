# -*- coding: utf-8 -*-
"""
Recommendation Domain DTO

가치주 스크리너 + 골든크로스 스캔 결과를 합성한 추천 후보 DTO 정의.
AI/실주문과 무관하며, readiness_label은 규칙 기반으로만 산출된다.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import Field

from src.application.common.dto import BaseDTO


class ReadinessLabel(str, Enum):
    """
    추천 후보 준비도 라벨

    Phase 1(규칙 기반, AI 없음)에서는 WATCH/RESEARCH/BLOCKED만 산출된다.
    CANDIDATE/DECISION_READY/AVOID는 AI evidence pack(Phase 3)과
    리스크 게이트(Phase 2)가 붙어야 도달 가능하다.
    """

    WATCH = "WATCH"
    RESEARCH = "RESEARCH"
    CANDIDATE = "CANDIDATE"
    DECISION_READY = "DECISION_READY"
    AVOID = "AVOID"
    BLOCKED = "BLOCKED"


class RecommendationScorecardDTO(BaseDTO):
    """
    추천 후보 점수표

    Attributes:
        technical_score: 골든크로스 상태 기반 기술 점수 (0~100)
        fundamental_score: 가치주 스크리너 통과 여부 기반 재무 점수 (0~100), 미평가 시 None
        quant_score: 정량(기술) 점수. Phase 1에서는 technical_score와 동일
        final_score: 최종 합성 점수
    """

    technical_score: float = Field(description="기술 점수 (gc_state 기반, 0~100)")
    fundamental_score: float | None = Field(
        default=None, description="재무 점수 (가치주 스크리너 통과 시 100, 미평가 시 None)"
    )
    quant_score: float = Field(description="정량 점수 (Phase 1: technical_score와 동일)")
    final_score: float = Field(description="최종 합성 점수")


class RecommendationCandidateDTO(BaseDTO):
    """
    추천 후보

    Attributes:
        symbol: 종목코드
        name: 종목명
        market: 시장 구분
        current_price: 현재가
        technical_state: 골든크로스 상태 (gc_state)
        has_fundamental_evidence: 가치주 스크리너 결과 존재 여부
        scorecard: 점수표
        readiness_label: 준비도 라벨
        missing_evidence: 부족한 증거 목록
        blocked_actions: 차단된 액션 목록 (Phase 1은 항상 auto_order 포함)
    """

    symbol: str = Field(description="종목코드")
    name: str = Field(description="종목명")
    market: str = Field(description="시장 구분")
    current_price: Decimal = Field(description="현재가")
    technical_state: str = Field(description="골든크로스 상태 (gc_state)")
    has_fundamental_evidence: bool = Field(description="가치주 스크리너 결과 존재 여부")
    scorecard: RecommendationScorecardDTO = Field(description="점수표")
    readiness_label: ReadinessLabel = Field(description="준비도 라벨")
    missing_evidence: list[str] = Field(default_factory=list, description="부족한 증거 목록")
    blocked_actions: list[str] = Field(default_factory=list, description="차단된 액션 목록")


class RecommendationCandidateListDTO(BaseDTO):
    """
    추천 후보 목록

    Attributes:
        candidates: 추천 후보 목록
        total_scanned: 골든크로스 스캔 대상 종목 수
        candidate_count: 추천 후보 수
        generated_at: 생성 시각
        errors: 골든크로스 스캔 중 발생한 오류 메시지 (스캔 저하 여부 판단용)
    """

    candidates: list[RecommendationCandidateDTO] = Field(description="추천 후보 목록")
    total_scanned: int = Field(description="골든크로스 스캔 대상 종목 수")
    candidate_count: int = Field(description="추천 후보 수")
    generated_at: datetime = Field(description="생성 시각")
    errors: list[str] = Field(default_factory=list, description="스캔 중 발생한 오류 메시지")
