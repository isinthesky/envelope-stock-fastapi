# -*- coding: utf-8 -*-
"""Add OHLCV cache table

Revision ID: 20260108_ohlcv_cache
Revises: 20251229_golden_cross
Create Date: 2026-01-08

Tables:
- ohlcv_cache: OHLCV 캔들 데이터 캐시
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260108_ohlcv_cache'
down_revision: Union[str, Sequence[str], None] = '20251229_golden_cross'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'ohlcv_cache',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('symbol', sa.String(length=20), nullable=False, comment='종목코드'),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False, comment='캔들 시각'),
        sa.Column('interval', sa.String(length=10), nullable=False, server_default='1d', comment='시간 간격 (1d, 1w, 1m)'),
        sa.Column('open', sa.Numeric(precision=18, scale=2), nullable=False, comment='시가'),
        sa.Column('high', sa.Numeric(precision=18, scale=2), nullable=False, comment='고가'),
        sa.Column('low', sa.Numeric(precision=18, scale=2), nullable=False, comment='저가'),
        sa.Column('close', sa.Numeric(precision=18, scale=2), nullable=False, comment='종가'),
        sa.Column('volume', sa.BigInteger(), nullable=False, comment='거래량'),
        sa.Column('adjusted', sa.Boolean(), nullable=False, server_default='false', comment='수정주가 여부'),
        sa.Column('source', sa.String(length=20), nullable=False, server_default='kis', comment='데이터 출처 (kis, yfinance 등)'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', 'timestamp', 'interval', name='uq_ohlcv_symbol_timestamp_interval'),
    )

    # 인덱스 생성
    op.create_index('ix_ohlcv_cache_symbol', 'ohlcv_cache', ['symbol'], unique=False)
    op.create_index('ix_ohlcv_cache_timestamp', 'ohlcv_cache', ['timestamp'], unique=False)
    op.create_index('ix_ohlcv_symbol_timestamp', 'ohlcv_cache', ['symbol', 'timestamp'], unique=False)
    op.create_index('ix_ohlcv_symbol_interval_timestamp', 'ohlcv_cache', ['symbol', 'interval', 'timestamp'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_ohlcv_symbol_interval_timestamp', table_name='ohlcv_cache')
    op.drop_index('ix_ohlcv_symbol_timestamp', table_name='ohlcv_cache')
    op.drop_index('ix_ohlcv_cache_timestamp', table_name='ohlcv_cache')
    op.drop_index('ix_ohlcv_cache_symbol', table_name='ohlcv_cache')
    op.drop_table('ohlcv_cache')
