"""Drop unused core tables and grade/assignment columns (small-household build).

Revision ID: 0005_family_simplify_core
Revises: 0004_science_experiments
Create Date: 2026-05-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_family_simplify_core"
down_revision: Union[str, None] = "0004_science_experiments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("skill_observations", schema="core")

    op.drop_index("ix_core_assignments_project_id", table_name="assignments", schema="core")
    op.drop_constraint("assignments_project_id_fkey", "assignments", schema="core", type_="foreignkey")
    op.drop_column("assignments", "project_id", schema="core")

    op.drop_constraint("grades_project_id_fkey", "grades", schema="core", type_="foreignkey")
    op.drop_column("grades", "project_id", schema="core")
    op.drop_column("grades", "rubric_scores_json", schema="core")
    op.drop_column("grades", "evidence_refs_json", schema="core")

    op.drop_table("projects", schema="core")

    op.drop_column("assignments", "rubric_json", schema="core")


def downgrade() -> None:
    raise NotImplementedError("Downgrade not supported for this simplification migration.")
