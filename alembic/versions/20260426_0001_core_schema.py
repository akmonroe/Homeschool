"""core schema: students, projects, assignments, items, grades, skills

Revision ID: 0001_core
Revises:
Create Date: 2026-04-26

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_core"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS core")

    op.create_table(
        "students",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="core",
    )

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("originating_app", sa.String(64), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="core",
    )
    op.create_index("ix_core_projects_student_id", "projects", ["student_id"], schema="core")

    op.create_table(
        "assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("app_slug", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("rubric_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="core",
    )
    op.create_index("ix_core_assignments_student_id", "assignments", ["student_id"], schema="core")
    op.create_index("ix_core_assignments_project_id", "assignments", ["project_id"], schema="core")

    op.create_table(
        "assignment_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("item_type", sa.String(64), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="core",
    )
    op.create_index("ix_core_assignment_items_assignment_id", "assignment_items", ["assignment_id"], schema="core")

    op.create_table(
        "grades",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.assignments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("scored_by", sa.String(32), nullable=False, server_default="human"),
        sa.Column("score_numeric", sa.Numeric(12, 4), nullable=True),
        sa.Column("score_max", sa.Numeric(12, 4), nullable=True),
        sa.Column("letter", sa.String(8), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("rubric_scores_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("evidence_refs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="core",
    )
    op.create_index("ix_core_grades_student_id", "grades", ["student_id"], schema="core")
    op.create_index("ix_core_grades_assignment_id", "grades", ["assignment_id"], schema="core")

    op.create_table(
        "skill_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_key", sa.String(128), nullable=False),
        sa.Column("scale_min", sa.Numeric(12, 4), nullable=True),
        sa.Column("scale_max", sa.Numeric(12, 4), nullable=True),
        sa.Column("value_numeric", sa.Numeric(12, 4), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="system"),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("context_assignment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.assignments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("observed_on", sa.Date(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="core",
    )
    op.create_index("ix_core_skill_obs_student_id", "skill_observations", ["student_id"], schema="core")
    op.create_index("ix_core_skill_obs_student_skill", "skill_observations", ["student_id", "skill_key"], schema="core")


def downgrade() -> None:
    op.drop_table("skill_observations", schema="core")
    op.drop_table("grades", schema="core")
    op.drop_table("assignment_items", schema="core")
    op.drop_table("assignments", schema="core")
    op.drop_table("projects", schema="core")
    op.drop_table("students", schema="core")
    op.execute("DROP SCHEMA IF EXISTS core CASCADE")
