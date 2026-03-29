# -*- coding: utf-8 -*-
"""Fix analysis_history sell columns compatibility

Revision ID: 20260329_fix_analysis_history
Revises: 20260221_add_naver_industry_codes
Create Date: 2026-03-29

문제:
- 코드/DTO/Repository는 analysis_history 에 `sell_phase`, `entry_price` 를 기대함
- 실제 DB는 과거 스키마(`sell_signal_strength`, `sell_recommendation`) 상태로 남아 있어
  매도 이력 조회/갱신 시 ORM select 단계에서 컬럼 불일치 오류가 발생함

해결:
- 누락된 `sell_phase`, `entry_price` 컬럼을 안전하게 추가
- legacy `sell_recommendation` 값이 있으면 `sell_phase` 로 1회 백필
- 기존 legacy 컬럼은 하위 호환을 위해 유지
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260329_fix_analysis_history"
down_revision: Union[str, Sequence[str], None] = "20260221_add_naver_industry_codes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SELL_RECOMMENDATION_TO_PHASE = {
    "STRONG_SELL": "PHASE_5",
    "SELL": "PHASE_4",
    "CONSIDER_SELL": "PHASE_3",
    "WEAK_SELL": "PHASE_2",
    "WATCH": "PHASE_1",
    "HOLD": "NONE",
}


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "analysis_history"):
        return

    if not _has_column(inspector, "analysis_history", "sell_phase"):
        op.add_column(
            "analysis_history",
            sa.Column(
                "sell_phase",
                sa.String(length=20),
                nullable=True,
                comment="매도 Phase (NONE, PHASE_1~5)",
            ),
        )

    if not _has_column(inspector, "analysis_history", "entry_price"):
        op.add_column(
            "analysis_history",
            sa.Column(
                "entry_price",
                sa.Numeric(precision=18, scale=2),
                nullable=True,
                comment="진입가 (수익률 계산용)",
            ),
        )

    # legacy sell_recommendation -> sell_phase 백필
    if _has_column(inspector, "analysis_history", "sell_recommendation"):
        for recommendation, phase in SELL_RECOMMENDATION_TO_PHASE.items():
            op.execute(
                sa.text(
                    """
                    UPDATE analysis_history
                    SET sell_phase = :phase
                    WHERE sell_phase IS NULL
                      AND sell_recommendation = :recommendation
                    """
                ).bindparams(phase=phase, recommendation=recommendation)
            )

    # 분석 타입이 sell 인 데이터 중 아직 값이 없으면 NONE 으로 보정
    op.execute(
        sa.text(
            """
            UPDATE analysis_history
            SET sell_phase = 'NONE'
            WHERE analysis_type = 'sell'
              AND sell_phase IS NULL
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "analysis_history"):
        return

    if _has_column(inspector, "analysis_history", "entry_price"):
        op.drop_column("analysis_history", "entry_price")

    if _has_column(inspector, "analysis_history", "sell_phase"):
        op.drop_column("analysis_history", "sell_phase")
