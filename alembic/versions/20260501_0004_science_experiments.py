"""science experiment templates, runs, and media

Revision ID: 0004_science_experiments
Revises: 0003_assignment_schedule
Create Date: 2026-05-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_science_experiments"
down_revision: Union[str, None] = "0003_assignment_schedule"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "science_experiment_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("subject_tags", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("procedure_outline", sa.Text(), nullable=True),
        sa.Column("is_published", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
    )
    op.create_table(
        "science_experiment_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("source", sa.String(32), server_default=sa.text("'self_chosen'"), nullable=False),
        sa.Column("status", sa.String(32), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=True),
        sa.Column("materials", sa.Text(), nullable=True),
        sa.Column("procedure_notes", sa.Text(), nullable=True),
        sa.Column("conclusions", sa.Text(), nullable=True),
        sa.Column("observations", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["assignment_id"], ["core.assignments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["student_id"], ["core.students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_id"], ["core.science_experiment_templates.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
    )
    op.create_index("ix_core_science_runs_student", "science_experiment_runs", ["student_id"], schema="core")
    op.create_index("ix_core_science_runs_assignment", "science_experiment_runs", ["assignment_id"], schema="core")
    op.create_table(
        "science_media",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rel_path", sa.String(1024), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=True),
        sa.Column("content_type", sa.String(255), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["core.science_experiment_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
    )
    op.create_index("ix_core_science_media_run", "science_media", ["run_id"], schema="core")
    # Starter templates for self-serve experiments
    op.execute(
        sa.text(
            """
            INSERT INTO core.science_experiment_templates
                (id, title, summary, subject_tags, procedure_outline, is_published, metadata)
            VALUES
            (
                gen_random_uuid(),
                'Plant growth: light',
                'Compare how plants respond to different light levels.',
                '["biology", "botany"]'::jsonb,
                '1) Set up 3 similar plants. 2) Vary only light. 3) Observe and measure height weekly.',
                true,
                '{}'::jsonb
            ),
            (
                gen_random_uuid(),
                'Chemical reaction: baking soda and vinegar',
                'Observe a gas-forming reaction and measure the mass change (open vs closed if safe).',
                '["chemistry", "safety first"]'::jsonb,
                '1) In a well-ventilated area, combine controlled amounts. 2) Time the fizz. 3) Log observations.',
                true,
                '{}'::jsonb
            );
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_core_science_media_run", table_name="science_media", schema="core")
    op.drop_table("science_media", schema="core")
    op.drop_index("ix_core_science_runs_assignment", table_name="science_experiment_runs", schema="core")
    op.drop_index("ix_core_science_runs_student", table_name="science_experiment_runs", schema="core")
    op.drop_table("science_experiment_runs", schema="core")
    op.drop_table("science_experiment_templates", schema="core")
