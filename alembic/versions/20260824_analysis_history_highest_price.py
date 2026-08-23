# -*- coding: utf-8 -*-
"""analysis_history에 고점 손절과 사후검증용 필드를 추가한다.

Revision ID: 20260824_analysis_history_peak
Revises: 20260701_recommendation_rule_sets
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260824_analysis_history_peak"
down_revision: Union[str, Sequence[str], None] = "20260701_recommendation_rule_sets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analysis_history",
        sa.Column(
            "highest_price",
            sa.Numeric(precision=18, scale=2),
            nullable=True,
            comment="보유 중 최고가 (고점 대비 손절 계산용)",
        ),
    )
    op.add_column(
        "analysis_history",
        sa.Column("sell_stage", sa.String(length=20), nullable=True, comment="최종 매도 Stage"),
    )
    op.add_column(
        "analysis_history",
        sa.Column(
            "sell_ratio_min",
            sa.Numeric(precision=8, scale=4),
            nullable=True,
            comment="최종 최소 권장 매도 비율",
        ),
    )
    op.add_column(
        "analysis_history",
        sa.Column(
            "sell_ratio_max",
            sa.Numeric(precision=8, scale=4),
            nullable=True,
            comment="최종 최대 권장 매도 비율",
        ),
    )
    # 과거 행에는 실제 고점 이력이 없으므로 진입가와 현재가 중 큰 값을 초기값으로 사용한다.
    op.execute(sa.text("""
            UPDATE analysis_history
            SET highest_price = GREATEST(entry_price, current_price)
            WHERE analysis_type = 'sell'
              AND entry_price IS NOT NULL
              AND highest_price IS NULL
            """))


def downgrade() -> None:
    op.drop_column("analysis_history", "sell_ratio_max")
    op.drop_column("analysis_history", "sell_ratio_min")
    op.drop_column("analysis_history", "sell_stage")
    op.drop_column("analysis_history", "highest_price")
