"""assignment scheduling fields + grade completion timestamps

Revision ID: 0003_assignment_schedule
Revises: 0002_dictation_lexemes
Create Date: 2026-04-28

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_assignment_schedule"
down_revision: Union[str, None] = "0002_dictation_lexemes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # When the assignment becomes visible / may be started (optional scheduling window start).
    op.add_column(
        "assignments",
        sa.Column("available_from", sa.DateTime(timezone=True), nullable=True),
        schema="core",
    )
    # due_at already exists; index for "what is due soon" queries.
    op.create_index(
        "ix_core_assignments_due_at",
        "assignments",
        ["due_at"],
        schema="core",
    )
    op.create_index(
        "ix_core_assignments_available_from",
        "assignments",
        ["available_from"],
        schema="core",
    )

    # completed_at: learner finished the work; graded_at: score recorded (often same as POST time).
    op.add_column(
        "grades",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        schema="core",
    )
    op.add_column(
        "grades",
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
        schema="core",
    )


def downgrade() -> None:
    op.drop_index("ix_core_assignments_available_from", table_name="assignments", schema="core")
    op.drop_index("ix_core_assignments_due_at", table_name="assignments", schema="core")
    op.drop_column("assignments", "available_from", schema="core")

    op.drop_column("grades", "graded_at", schema="core")
    op.drop_column("grades", "completed_at", schema="core")
