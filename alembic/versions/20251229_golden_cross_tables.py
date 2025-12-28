# -*- coding: utf-8 -*-
"""Add Golden Cross strategy tables

Revision ID: 20251229_golden_cross
Revises: 784e41ff1288
Create Date: 2025-12-29

Tables:
- strategy_symbol_states: 종목별 전략 상태 머신
- strategy_signals: 매수/매도 시그널 이력
- stock_universe: 종목 유니버스
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20251229_golden_cross'
down_revision: Union[str, Sequence[str], None] = '784e41ff1288'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### strategy_symbol_states ###
    op.create_table(
        'strategy_symbol_states',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('strategy_id', sa.BigInteger(), nullable=False, comment='전략 ID'),
        sa.Column('symbol', sa.String(length=20), nullable=False, comment='종목코드'),
        sa.Column('state', sa.String(length=30), nullable=False, server_default='WAITING_FOR_GC', comment='현재 상태'),
        sa.Column('gc_date', sa.DateTime(timezone=True), nullable=True, comment='골든크로스 발생일'),
        sa.Column('pullback_date', sa.DateTime(timezone=True), nullable=True, comment='풀백 발생일'),
        sa.Column('entry_date', sa.DateTime(timezone=True), nullable=True, comment='진입일'),
        sa.Column('entry_price', sa.Numeric(precision=15, scale=2), nullable=True, comment='진입가'),
        sa.Column('quantity', sa.BigInteger(), nullable=True, comment='보유 수량'),
        sa.Column('last_ma_short', sa.Numeric(precision=15, scale=2), nullable=True, comment='최근 단기 MA'),
        sa.Column('last_ma_long', sa.Numeric(precision=15, scale=2), nullable=True, comment='최근 장기 MA'),
        sa.Column('last_stoch_k', sa.Numeric(precision=8, scale=2), nullable=True, comment='최근 Stochastic K'),
        sa.Column('last_stoch_d', sa.Numeric(precision=8, scale=2), nullable=True, comment='최근 Stochastic D'),
        sa.Column('last_close', sa.Numeric(precision=15, scale=2), nullable=True, comment='최근 종가'),
        sa.Column('metadata_json', sa.Text(), nullable=True, comment='추가 메타데이터 (JSON)'),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True, comment='마지막 체크 시각'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('strategy_id', 'symbol', name='uq_strategy_symbol'),
    )
    op.create_index('ix_strategy_symbol_states_strategy_id', 'strategy_symbol_states', ['strategy_id'], unique=False)
    op.create_index('ix_strategy_symbol_states_symbol', 'strategy_symbol_states', ['symbol'], unique=False)
    op.create_index('ix_strategy_symbol_states_state', 'strategy_symbol_states', ['state'], unique=False)

    # ### strategy_signals ###
    op.create_table(
        'strategy_signals',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('strategy_id', sa.BigInteger(), nullable=False, comment='전략 ID'),
        sa.Column('symbol', sa.String(length=20), nullable=False, comment='종목코드'),
        sa.Column('signal_type', sa.String(length=10), nullable=False, comment='시그널 유형 (buy/sell/hold)'),
        sa.Column('signal_status', sa.String(length=20), nullable=False, server_default='pending', comment='시그널 상태'),
        sa.Column('signal_price', sa.Numeric(precision=15, scale=2), nullable=False, comment='시그널 발생 시점 가격'),
        sa.Column('target_quantity', sa.BigInteger(), nullable=True, comment='목표 수량'),
        sa.Column('executed_price', sa.Numeric(precision=15, scale=2), nullable=True, comment='체결 가격'),
        sa.Column('executed_quantity', sa.BigInteger(), nullable=True, comment='체결 수량'),
        sa.Column('exit_reason', sa.String(length=30), nullable=True, comment='청산 사유'),
        sa.Column('realized_pnl', sa.Numeric(precision=15, scale=2), nullable=True, comment='실현 손익'),
        sa.Column('realized_pnl_ratio', sa.Numeric(precision=8, scale=4), nullable=True, comment='실현 수익률'),
        sa.Column('ma_short', sa.Numeric(precision=15, scale=2), nullable=True, comment='단기 MA'),
        sa.Column('ma_long', sa.Numeric(precision=15, scale=2), nullable=True, comment='장기 MA'),
        sa.Column('stoch_k', sa.Numeric(precision=8, scale=2), nullable=True, comment='Stochastic K'),
        sa.Column('stoch_d', sa.Numeric(precision=8, scale=2), nullable=True, comment='Stochastic D'),
        sa.Column('prev_state', sa.String(length=30), nullable=True, comment='이전 상태'),
        sa.Column('new_state', sa.String(length=30), nullable=True, comment='새 상태'),
        sa.Column('order_id', sa.BigInteger(), nullable=True, comment='연동된 주문 ID'),
        sa.Column('order_no', sa.String(length=50), nullable=True, comment='주문번호'),
        sa.Column('note', sa.Text(), nullable=True, comment='비고'),
        sa.Column('metadata_json', sa.Text(), nullable=True, comment='추가 메타데이터 (JSON)'),
        sa.Column('signal_at', sa.DateTime(timezone=True), nullable=False, comment='시그널 발생 시각'),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True, comment='체결 시각'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_strategy_signals_strategy_id', 'strategy_signals', ['strategy_id'], unique=False)
    op.create_index('ix_strategy_signals_symbol', 'strategy_signals', ['symbol'], unique=False)
    op.create_index('ix_strategy_signals_signal_type', 'strategy_signals', ['signal_type'], unique=False)
    op.create_index('ix_strategy_signals_signal_at', 'strategy_signals', ['signal_at'], unique=False)
    op.create_index('ix_strategy_signals_strategy_symbol', 'strategy_signals', ['strategy_id', 'symbol'], unique=False)

    # ### stock_universe ###
    op.create_table(
        'stock_universe',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('symbol', sa.String(length=20), nullable=False, comment='종목코드'),
        sa.Column('name', sa.String(length=100), nullable=False, comment='종목명'),
        sa.Column('market', sa.String(length=20), nullable=False, comment='시장 구분 (KOSPI/KOSDAQ)'),
        sa.Column('sector', sa.String(length=100), nullable=True, comment='섹터'),
        sa.Column('industry', sa.String(length=100), nullable=True, comment='산업'),
        sa.Column('market_cap', sa.Numeric(precision=20, scale=0), nullable=True, comment='시가총액 (원)'),
        sa.Column('avg_volume_20d', sa.Numeric(precision=15, scale=0), nullable=True, comment='20일 평균 거래량'),
        sa.Column('avg_turnover_20d', sa.Numeric(precision=20, scale=0), nullable=True, comment='20일 평균 거래대금'),
        sa.Column('current_price', sa.Numeric(precision=15, scale=2), nullable=True, comment='현재가'),
        sa.Column('price_change_ratio', sa.Numeric(precision=8, scale=4), nullable=True, comment='등락률'),
        sa.Column('week_52_high', sa.Numeric(precision=15, scale=2), nullable=True, comment='52주 최고가'),
        sa.Column('week_52_low', sa.Numeric(precision=15, scale=2), nullable=True, comment='52주 최저가'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true'), comment='활성 여부'),
        sa.Column('is_tradable', sa.Boolean(), nullable=False, server_default=sa.text('true'), comment='거래 가능 여부'),
        sa.Column('is_excluded', sa.Boolean(), nullable=False, server_default=sa.text('false'), comment='제외 여부 (수동)'),
        sa.Column('exclude_reason', sa.String(length=200), nullable=True, comment='제외 사유'),
        sa.Column('passed_market_cap', sa.Boolean(), nullable=True, comment='시가총액 조건 통과'),
        sa.Column('passed_volume', sa.Boolean(), nullable=True, comment='거래량 조건 통과'),
        sa.Column('passed_price_range', sa.Boolean(), nullable=True, comment='가격대 조건 통과'),
        sa.Column('screening_score', sa.Numeric(precision=8, scale=2), nullable=True, comment='스크리닝 점수'),
        sa.Column('metadata_json', sa.Text(), nullable=True, comment='추가 메타데이터 (JSON)'),
        sa.Column('data_updated_at', sa.DateTime(timezone=True), nullable=True, comment='데이터 갱신 시각'),
        sa.Column('screened_at', sa.DateTime(timezone=True), nullable=True, comment='스크리닝 시각'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', name='uq_stock_universe_symbol'),
    )
    op.create_index('ix_stock_universe_symbol', 'stock_universe', ['symbol'], unique=True)
    op.create_index('ix_stock_universe_market', 'stock_universe', ['market'], unique=False)
    op.create_index('ix_stock_universe_market_cap', 'stock_universe', ['market_cap'], unique=False)
    op.create_index('ix_stock_universe_is_active', 'stock_universe', ['is_active'], unique=False)
    op.create_index('ix_stock_universe_screening', 'stock_universe', ['is_active', 'is_tradable', 'is_excluded'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop stock_universe
    op.drop_index('ix_stock_universe_screening', table_name='stock_universe')
    op.drop_index('ix_stock_universe_is_active', table_name='stock_universe')
    op.drop_index('ix_stock_universe_market_cap', table_name='stock_universe')
    op.drop_index('ix_stock_universe_market', table_name='stock_universe')
    op.drop_index('ix_stock_universe_symbol', table_name='stock_universe')
    op.drop_table('stock_universe')

    # Drop strategy_signals
    op.drop_index('ix_strategy_signals_strategy_symbol', table_name='strategy_signals')
    op.drop_index('ix_strategy_signals_signal_at', table_name='strategy_signals')
    op.drop_index('ix_strategy_signals_signal_type', table_name='strategy_signals')
    op.drop_index('ix_strategy_signals_symbol', table_name='strategy_signals')
    op.drop_index('ix_strategy_signals_strategy_id', table_name='strategy_signals')
    op.drop_table('strategy_signals')

    # Drop strategy_symbol_states
    op.drop_index('ix_strategy_symbol_states_state', table_name='strategy_symbol_states')
    op.drop_index('ix_strategy_symbol_states_symbol', table_name='strategy_symbol_states')
    op.drop_index('ix_strategy_symbol_states_strategy_id', table_name='strategy_symbol_states')
    op.drop_table('strategy_symbol_states')
