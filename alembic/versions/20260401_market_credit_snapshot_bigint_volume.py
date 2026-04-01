# -*- coding: utf-8 -*-
"""expand market credit trading_volume to bigint"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260401_market_credit_snapshot_volume_bigint"
down_revision: Union[str, Sequence[str], None] = "20260401_market_credit_snapshot_ts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "market_credit_snapshots",
        "trading_volume",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "market_credit_snapshots",
        "trading_volume",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
