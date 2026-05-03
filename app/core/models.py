"""SQLAlchemy models for the `core` schema — shared across Homeschool apps."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


SCHEMA = "core"


class Lexeme(Base):
    """Canonical spelling/dictionary entry; `extensions` JSONB holds pronunciation, hints, tricks."""

    __tablename__ = "lexemes"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    locale_code: Mapped[str] = mapped_column(String(16), nullable=False, server_default="en")
    canonical_word: Mapped[str] = mapped_column(String(255), nullable=False)
    display_word: Mapped[str | None] = mapped_column(String(255), nullable=True)
    difficulty_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    extensions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DictationAssignment(Base):
    """Per-dictation-user word queue (replaces SQLite user_words)."""

    __tablename__ = "dictation_assignments"
    __table_args__ = (
        UniqueConstraint("dictation_user_id", "lexeme_id", name="uq_core_dictation_assign_user_lexeme"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dictation_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    lexeme_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.lexemes.id", ondelete="CASCADE"), nullable=False
    )
    interval: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    correct_streak: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_review_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lexeme: Mapped[Lexeme] = relationship()


class DictationAttempt(Base):
    """Practice history (replaces SQLite history)."""

    __tablename__ = "dictation_attempts"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dictation_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    lexeme_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.lexemes.id", ondelete="CASCADE"), nullable=False
    )
    is_correct: Mapped[bool] = mapped_column(nullable=False)
    attempt_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lexeme: Mapped[Lexeme] = relationship()


class Student(Base):
    __tablename__ = "students"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    assignments: Mapped[list[Assignment]] = relationship(back_populates="student", cascade="all, delete-orphan")
    grades: Mapped[list[Grade]] = relationship(back_populates="student", cascade="all, delete-orphan")
    science_experiment_runs: Mapped[list["ScienceExperimentRun"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )


class ScienceExperimentTemplate(Base):
    """Reusable lab write-up pattern a student can start from (self-chosen) or see via assignment payload."""

    __tablename__ = "science_experiment_templates"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject_tags: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    procedure_outline: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    runs: Mapped[list["ScienceExperimentRun"]] = relationship(back_populates="template")


class ScienceExperimentRun(Base):
    """One student experiment session: from an assignment, or chosen from a template, or ad hoc."""

    __tablename__ = "science_experiment_runs"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.students.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.science_experiment_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assignments.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="self_chosen"
    )  # assigned | self_chosen | ad_hoc
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="draft")
    hypothesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    materials: Mapped[str | None] = mapped_column(Text, nullable=True)
    procedure_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    conclusions: Mapped[str | None] = mapped_column(Text, nullable=True)
    observations_json: Mapped[list[Any]] = mapped_column(
        "observations", JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    student: Mapped[Student] = relationship(back_populates="science_experiment_runs")
    template: Mapped[ScienceExperimentTemplate | None] = relationship(back_populates="runs")
    assignment: Mapped[Assignment | None] = relationship(
        back_populates="science_experiment_runs",
        foreign_keys="ScienceExperimentRun.assignment_id",
    )
    media: Mapped[list["ScienceMedia"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ScienceMedia(Base):
    """Image or video stored on disk; path is relative to SCIENCE_DATA_DIR."""

    __tablename__ = "science_media"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.science_experiment_runs.id", ondelete="CASCADE"), nullable=False
    )
    rel_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # image | video
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[ScienceExperimentRun] = relationship(back_populates="media")


class Assignment(Base):
    """Work assigned to a student (dictation, science, etc.)."""

    __tablename__ = "assignments"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.students.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    app_slug: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="draft")
    available_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    student: Mapped[Student] = relationship(back_populates="assignments")
    items: Mapped[list[AssignmentItem]] = relationship(back_populates="assignment", cascade="all, delete-orphan")
    grades: Mapped[list["Grade"]] = relationship(back_populates="assignment")
    science_experiment_runs: Mapped[list["ScienceExperimentRun"]] = relationship(
        back_populates="assignment", foreign_keys="ScienceExperimentRun.assignment_id"
    )


class AssignmentItem(Base):
    """Tall decomposition of an assignment (steps, prompts, checkpoints) for agents and UIs."""

    __tablename__ = "assignment_items"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assignments.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    item_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    assignment: Mapped[Assignment] = relationship(back_populates="items")


class Grade(Base):
    __tablename__ = "grades"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.students.id", ondelete="CASCADE"), nullable=False
    )
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assignments.id", ondelete="SET NULL"), nullable=True
    )
    scored_by: Mapped[str] = mapped_column(String(32), nullable=False, server_default="human")
    score_numeric: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    score_max: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    letter: Mapped[str | None] = mapped_column(String(8), nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped[Student] = relationship(back_populates="grades")
    assignment: Mapped[Assignment | None] = relationship(back_populates="grades")

