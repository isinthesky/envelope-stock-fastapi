# -*- coding: utf-8 -*-
"""Add analysis_history table

Revision ID: 20260108_analysis_history
Revises: 20260108_ohlcv_cache
Create Date: 2026-01-08

Tables:
- analysis_history: 매수/매도 전략 분석 결과 이력
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260108_analysis_history'
down_revision: Union[str, Sequence[str], None] = '20260108_ohlcv_cache'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'analysis_history',
        # Primary Key
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),

        # 기본 정보
        sa.Column('analysis_type', sa.String(length=20), nullable=False, comment='분석 유형 (buy/sell)'),
        sa.Column('symbol', sa.String(length=20), nullable=False, comment='종목코드'),
        sa.Column('name', sa.String(length=100), nullable=True, comment='종목명'),

        # 가격 정보
        sa.Column('current_price', sa.Numeric(precision=18, scale=2), nullable=False, comment='현재가'),

        # 공통 지표
        sa.Column('ma_short', sa.Numeric(precision=18, scale=2), nullable=True, comment='단기 MA (40일)'),
        sa.Column('ma_long', sa.Numeric(precision=18, scale=2), nullable=True, comment='장기 MA (160일)'),
        sa.Column('ma_gap_ratio', sa.Numeric(precision=8, scale=4), nullable=True, comment='MA 갭 비율 (%)'),
        sa.Column('stoch_k', sa.Numeric(precision=8, scale=4), nullable=True, comment='Stochastic K'),
        sa.Column('stoch_d', sa.Numeric(precision=8, scale=4), nullable=True, comment='Stochastic D'),

        # 매수 분석용 (골든크로스)
        sa.Column('gc_state', sa.String(length=30), nullable=True, comment='골든크로스 상태'),
        sa.Column('is_gc_active', sa.Boolean(), nullable=True, comment='골든크로스 활성 여부'),

        # 매도 분석용
        sa.Column('rsi', sa.Numeric(precision=8, scale=4), nullable=True, comment='RSI (14일)'),
        sa.Column('is_death_cross', sa.Boolean(), nullable=True, comment='데드크로스 여부'),
        sa.Column('is_stoch_overbought', sa.Boolean(), nullable=True, comment='Stochastic 과매수 여부'),
        sa.Column('is_rsi_overbought', sa.Boolean(), nullable=True, comment='RSI 과매수 여부'),
        sa.Column('sell_signal_strength', sa.Integer(), nullable=True, comment='매도 시그널 강도 (0-5)'),
        sa.Column('sell_recommendation', sa.String(length=20), nullable=True, comment='매도 추천'),
        sa.Column('sell_reasons', sa.Text(), nullable=True, comment='매도 근거 (JSON array)'),

        # 메타데이터
        sa.Column('analyzed_at', sa.DateTime(timezone=True), nullable=False, comment='분석 시각'),
        sa.Column('note', sa.Text(), nullable=True, comment='사용자 메모'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true', comment='활성 추적 여부'),
        sa.Column('candle_count', sa.Integer(), nullable=True, comment='분석에 사용된 캔들 수'),

        # 타임스탬프
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

        sa.PrimaryKeyConstraint('id'),
    )

    # 인덱스 생성
    op.create_index('ix_analysis_history_type_symbol', 'analysis_history', ['analysis_type', 'symbol'], unique=False)
    op.create_index('ix_analysis_history_analyzed_at', 'analysis_history', ['analyzed_at'], unique=False)
    op.create_index('ix_analysis_history_is_active', 'analysis_history', ['is_active'], unique=False)
    op.create_index('ix_analysis_history_type_active', 'analysis_history', ['analysis_type', 'is_active'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_analysis_history_type_active', table_name='analysis_history')
    op.drop_index('ix_analysis_history_is_active', table_name='analysis_history')
    op.drop_index('ix_analysis_history_analyzed_at', table_name='analysis_history')
    op.drop_index('ix_analysis_history_type_symbol', table_name='analysis_history')
    op.drop_table('analysis_history')
