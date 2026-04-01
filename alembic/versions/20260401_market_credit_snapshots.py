# -*- coding: utf-8 -*-
"""add market credit snapshots table"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260401_market_credit_snapshots"
down_revision: Union[str, Sequence[str], None] = "20260329_fix_analysis_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_credit_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("market_label", sa.String(length=20), nullable=False),
        sa.Column("biz_date", sa.String(length=8), nullable=False),
        sa.Column("trading_volume", sa.Integer(), nullable=True),
        sa.Column("balance_million", sa.BigInteger(), nullable=True),
        sa.Column("short_balance_million", sa.BigInteger(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "market_label", "biz_date", name="uq_market_credit_snapshot"),
    )
    op.create_index("ix_market_credit_market_date", "market_credit_snapshots", ["market_label", "biz_date"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_market_credit_market_date", table_name="market_credit_snapshots")
    op.drop_table("market_credit_snapshots")
