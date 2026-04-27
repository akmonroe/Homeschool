"""dictation lexemes + assignments + attempts in core schema

Revision ID: 0002_dictation_lexemes
Revises: 0001_core
Create Date: 2026-04-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_dictation_lexemes"
down_revision: Union[str, None] = "0001_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lexemes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("locale_code", sa.String(16), nullable=False, server_default="en"),
        sa.Column("canonical_word", sa.String(255), nullable=False),
        sa.Column("display_word", sa.String(255), nullable=True),
        sa.Column("difficulty_level", sa.Integer(), nullable=True),
        sa.Column("definition", sa.Text(), nullable=True),
        sa.Column(
            "extensions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="core",
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_core_lexemes_locale_canonical_lower "
        "ON core.lexemes (locale_code, lower(canonical_word))"
    )
    op.create_index("ix_core_lexemes_locale", "lexemes", ["locale_code"], schema="core")

    op.create_table(
        "dictation_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("dictation_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "lexeme_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("core.lexemes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("interval", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_review_date", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="core",
    )
    op.create_index(
        "ix_core_dictation_assign_user",
        "dictation_assignments",
        ["dictation_user_id"],
        schema="core",
    )
    op.create_index(
        "uq_core_dictation_assign_user_lexeme",
        "dictation_assignments",
        ["dictation_user_id", "lexeme_id"],
        unique=True,
        schema="core",
    )

    op.create_table(
        "dictation_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("dictation_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "lexeme_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("core.lexemes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("attempt_date", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="core",
    )
    op.create_index(
        "ix_core_dictation_attempts_user_date",
        "dictation_attempts",
        ["dictation_user_id", "attempt_date"],
        schema="core",
    )


def downgrade() -> None:
    op.drop_table("dictation_attempts", schema="core")
    op.drop_table("dictation_assignments", schema="core")
    op.drop_index("ix_core_lexemes_locale", table_name="lexemes", schema="core")
    op.execute("DROP INDEX IF EXISTS core.ix_core_lexemes_locale_canonical_lower")
    op.drop_table("lexemes", schema="core")
