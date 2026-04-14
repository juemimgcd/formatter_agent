"""create task_records table

Revision ID: 20260412_01
Revises:
Create Date: 2026-04-12

"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260412_01"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("query", sa.String(length=255), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="pending"
        ),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("excel_path", sa.String(length=255), nullable=True),
        sa.Column("execution_plan", sa.JSON(), nullable=True),
        sa.Column("result_payload", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("task_id"),
    )

    op.create_index(
        op.f("ix_task_records_query"), "task_records", ["query"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_task_records_query"), table_name="task_records")
    op.drop_table("task_records")
