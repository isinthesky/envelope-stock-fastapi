# -*- coding: utf-8 -*-
"""add personal flow snapshots table"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260401_personal_flow_snapshots"
down_revision: Union[str, Sequence[str], None] = "20260401_market_credit_snapshot_volume_bigint"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "personal_flow_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("biz_date", sa.String(length=8), nullable=False),
        sa.Column("individual_net_buy", sa.BigInteger(), nullable=True),
        sa.Column("close_price", sa.BigInteger(), nullable=True),
        sa.Column("trading_volume", sa.BigInteger(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "symbol", "biz_date", name="uq_personal_flow_snapshot"),
    )
    op.create_index("ix_personal_flow_symbol_date", "personal_flow_snapshots", ["symbol", "biz_date"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_personal_flow_symbol_date", table_name="personal_flow_snapshots")
    op.drop_table("personal_flow_snapshots")
