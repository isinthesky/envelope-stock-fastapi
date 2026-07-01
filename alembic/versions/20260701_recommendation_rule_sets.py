# -*- coding: utf-8 -*-
"""add recommendation rule sets and walk-forward validation tables"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260701_recommendation_rule_sets"
down_revision: Union[str, Sequence[str], None] = "20260401_personal_flow_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recommendation_rule_sets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("candidates_json", sa.Text(), nullable=False),
        sa.Column("frozen_hash", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recommendation_rule_sets_name_version",
        "recommendation_rule_sets",
        ["name", "version"],
        unique=False,
    )
    op.create_index(
        "ix_recommendation_rule_sets_status",
        "recommendation_rule_sets",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_recommendation_rule_sets_name",
        "recommendation_rule_sets",
        ["name"],
        unique=False,
    )

    op.create_table(
        "recommendation_rule_validations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("rule_set_id", sa.BigInteger(), nullable=False),
        sa.Column("benchmark", sa.String(length=20), nullable=False),
        sa.Column("selection_metric", sa.String(length=20), nullable=False),
        sa.Column("train_start", sa.Date(), nullable=False),
        sa.Column("train_end", sa.Date(), nullable=False),
        sa.Column("test_start", sa.Date(), nullable=False),
        sa.Column("test_end", sa.Date(), nullable=False),
        sa.Column("selected_candidate_id", sa.String(length=100), nullable=False),
        sa.Column("selected_candidate_hash", sa.String(length=32), nullable=False),
        sa.Column("data_snooping_warning", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("train_metrics_json", sa.Text(), nullable=False),
        sa.Column("test_metrics_json", sa.Text(), nullable=False),
        sa.Column("report_markdown", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["rule_set_id"], ["recommendation_rule_sets.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_recommendation_rule_validations_rule_set_id",
        "recommendation_rule_validations",
        ["rule_set_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recommendation_rule_validations_rule_set_id",
        table_name="recommendation_rule_validations",
    )
    op.drop_table("recommendation_rule_validations")
    op.drop_index("ix_recommendation_rule_sets_name", table_name="recommendation_rule_sets")
    op.drop_index("ix_recommendation_rule_sets_status", table_name="recommendation_rule_sets")
    op.drop_index("ix_recommendation_rule_sets_name_version", table_name="recommendation_rule_sets")
    op.drop_table("recommendation_rule_sets")
