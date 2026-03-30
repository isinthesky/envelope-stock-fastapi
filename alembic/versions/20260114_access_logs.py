# -*- coding: utf-8 -*-
"""Add access_logs table

Revision ID: 20260114_access_logs
Revises: 20260108_analysis_history
Create Date: 2026-01-14

Tables:
- access_logs: 외부 페이지 접근 로그
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260114_access_logs'
down_revision: Union[str, Sequence[str], None] = '9c1f1cc170b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'access_logs',
        # Primary Key
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),

        # 요청 정보
        sa.Column('method', sa.String(length=10), nullable=False, comment='HTTP 메서드 (GET, POST 등)'),
        sa.Column('path', sa.String(length=500), nullable=False, comment='요청 경로'),
        sa.Column('query_string', sa.Text(), nullable=True, comment='쿼리 스트링'),

        # 클라이언트 정보
        sa.Column('ip_address', sa.String(length=45), nullable=False, comment='클라이언트 IP (IPv4/IPv6)'),
        sa.Column('user_agent', sa.Text(), nullable=True, comment='User-Agent 헤더'),
        sa.Column('referer', sa.Text(), nullable=True, comment='Referer 헤더'),

        # 응답 정보
        sa.Column('status_code', sa.Integer(), nullable=False, comment='HTTP 상태 코드'),
        sa.Column('response_time_ms', sa.Integer(), nullable=True, comment='응답 시간 (밀리초)'),

        # 메타데이터
        sa.Column('accessed_at', sa.DateTime(timezone=True), nullable=False, comment='접근 시각'),

        # GeoIP 정보 (선택)
        sa.Column('country', sa.String(length=50), nullable=True, comment='접속 국가'),
        sa.Column('city', sa.String(length=100), nullable=True, comment='접속 도시'),

        # 타임스탬프 (BaseModel)
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

        sa.PrimaryKeyConstraint('id'),
    )

    # 인덱스 생성
    op.create_index('ix_access_logs_path', 'access_logs', ['path'], unique=False)
    op.create_index('ix_access_logs_ip_address', 'access_logs', ['ip_address'], unique=False)
    op.create_index('ix_access_logs_status_code', 'access_logs', ['status_code'], unique=False)
    op.create_index('ix_access_logs_accessed_at', 'access_logs', ['accessed_at'], unique=False)
    op.create_index('ix_access_logs_path_accessed', 'access_logs', ['path', 'accessed_at'], unique=False)
    op.create_index('ix_access_logs_ip_accessed', 'access_logs', ['ip_address', 'accessed_at'], unique=False)
    op.create_index('ix_access_logs_accessed_at_desc', 'access_logs', ['accessed_at'], unique=False, postgresql_using='btree')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_access_logs_accessed_at_desc', table_name='access_logs')
    op.drop_index('ix_access_logs_ip_accessed', table_name='access_logs')
    op.drop_index('ix_access_logs_path_accessed', table_name='access_logs')
    op.drop_index('ix_access_logs_accessed_at', table_name='access_logs')
    op.drop_index('ix_access_logs_status_code', table_name='access_logs')
    op.drop_index('ix_access_logs_ip_address', table_name='access_logs')
    op.drop_index('ix_access_logs_path', table_name='access_logs')
    op.drop_table('access_logs')
