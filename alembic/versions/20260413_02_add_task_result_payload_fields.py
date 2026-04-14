"""add task result payload fields

Revision ID: 20260413_02
Revises: 20260412_01
Create Date: 2026-04-13

"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260413_02"
down_revision: str | None = "20260412_01"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("task_records", sa.Column("execution_plan", sa.JSON(), nullable=True))
    op.add_column("task_records", sa.Column("result_payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("task_records", "result_payload")
    op.drop_column("task_records", "execution_plan")
