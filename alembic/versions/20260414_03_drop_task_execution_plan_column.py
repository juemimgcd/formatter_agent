"""drop task execution_plan column

Revision ID: 20260414_03
Revises: 20260413_02
Create Date: 2026-04-14

"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260414_03"
down_revision: str | None = "20260413_02"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("task_records", "execution_plan")


def downgrade() -> None:
    op.add_column(
        "task_records",
        sa.Column("execution_plan", sa.JSON(), nullable=True),
    )
