# -*- coding: utf-8 -*-
"""add timestamps to market credit snapshots"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260401_market_credit_snapshot_ts"
down_revision: Union[str, Sequence[str], None] = "20260401_market_credit_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "market_credit_snapshots", "created_at"):
        op.add_column(
            "market_credit_snapshots",
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        )
    if not _has_column(inspector, "market_credit_snapshots", "updated_at"):
        op.add_column(
            "market_credit_snapshots",
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_column(inspector, "market_credit_snapshots", "updated_at"):
        op.drop_column("market_credit_snapshots", "updated_at")
    if _has_column(inspector, "market_credit_snapshots", "created_at"):
        op.drop_column("market_credit_snapshots", "created_at")
