# -*- coding: utf-8 -*-
"""Add naver_industry_codes table

Revision ID: 20260221_add_naver_industry_codes
Revises: 20260114_access_logs
Create Date: 2026-02-21

주의:
- 운영 DB에 이미 테이블이 수동 생성되어 있을 수 있어, upgrade 시 존재 여부를 체크하고 생성합니다.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260221_add_naver_industry_codes"
down_revision: Union[str, Sequence[str], None] = "20260114_access_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "naver_industry_codes" in inspector.get_table_names():
        return

    op.create_table(
        "naver_industry_codes",
        sa.Column(
            "industry_code",
            sa.String(length=20),
            primary_key=True,
            nullable=False,
            comment="네이버 업종 코드",
        ),
        sa.Column(
            "industry_name",
            sa.String(length=200),
            nullable=False,
            comment="업종명",
        ),
        sa.Column(
            "source_url",
            sa.Text(),
            nullable=True,
            comment="업종명 수집 원본 URL",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "naver_industry_codes" not in inspector.get_table_names():
        return

    op.drop_table("naver_industry_codes")
