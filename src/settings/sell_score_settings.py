# -*- coding: utf-8 -*-
"""
Sell score settings - 매도 점수 설정
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SellScoreSettings(BaseSettings):
    """매도 점수 설정"""

    model_config = SettingsConfigDict(env_prefix="SELL_SCORE_")

    # 가중치
    stoch_weight: float = Field(default=30.0, description="Stoch 점수 가중치")
    rsi_weight: float = Field(default=25.0, description="RSI 점수 가중치")
    volume_weight: float = Field(default=20.0, description="거래량 점수 가중치")
    adx_weight: float = Field(default=15.0, description="ADX 점수 가중치")
    ma_weight: float = Field(default=10.0, description="MA 점수 가중치")
    cross_bonus: float = Field(default=10.0, description="Stoch 데드크로스 보너스")
    personal_flow_weight: float = Field(default=12.0, description="개인 수급 과열 점수 가중치")
    market_credit_weight: float = Field(default=8.0, description="시장 신용 과열 점수 가중치")
    risk_combo_weight: float = Field(default=6.0, description="개인수급+시장신용 피크 조합 보너스")

    # 개인 수급 과열 기준
    personal_buy_days_threshold: int = Field(default=4, description="최근 5일 중 개인 순매수 일수 기준")
    personal_buy_ratio_high: float = Field(default=0.20, description="최근 5일 개인 순매수 / 최근 거래량 강한 기준")
    personal_buy_ratio_mid: float = Field(default=0.10, description="최근 5일 개인 순매수 / 최근 거래량 보통 기준")

    # ADX 강세 감점
    adx_penalty_strong_threshold: float = Field(default=30.0, description="ADX 강한 상승 추세 기준")
    adx_penalty_moderate_threshold: float = Field(default=25.0, description="ADX 상승 추세 기준")
    adx_penalty_strong: float = Field(default=-20.0, description="강한 상승 추세 감점")
    adx_penalty_moderate: float = Field(default=-10.0, description="상승 추세 감점")

    # Stage 임계값 (정규화 점수 기준)
    exit_all_threshold: float = Field(default=70.0, description="EXIT_ALL 임계값")
    reduce_2_threshold: float = Field(default=50.0, description="REDUCE_2 임계값")
    reduce_1_threshold: float = Field(default=30.0, description="REDUCE_1 임계값")

    # 거래량 구간 (비율 기준)
    volume_ratio_high: float = Field(default=4.0, description="거래량 폭증 기준 (400%)")
    volume_ratio_mid: float = Field(default=2.5, description="거래량 급증 기준 (250%)")
    volume_ratio_low: float = Field(default=1.5, description="거래량 증가 기준 (150%)")
