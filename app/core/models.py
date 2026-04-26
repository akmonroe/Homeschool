"""SQLAlchemy models for the `core` schema — shared across Homeschool apps."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


SCHEMA = "core"


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

    projects: Mapped[list[Project]] = relationship(back_populates="student", cascade="all, delete-orphan")
    assignments: Mapped[list[Assignment]] = relationship(back_populates="student", cascade="all, delete-orphan")
    grades: Mapped[list[Grade]] = relationship(back_populates="student", cascade="all, delete-orphan")
    skill_observations: Mapped[list[SkillObservation]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )


class Project(Base):
    """Cross-app grouping: unit study, portfolio, or AI-generated learning path."""

    __tablename__ = "projects"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.students.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active")
    originating_app: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    student: Mapped[Student] = relationship(back_populates="projects")
    assignments: Mapped[list[Assignment]] = relationship(back_populates="project")


class Assignment(Base):
    """Work assigned to a student; AI agents can draft rows using rubric_json / metadata."""

    __tablename__ = "assignments"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.students.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.projects.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    app_slug: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="draft")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    rubric_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    student: Mapped[Student] = relationship(back_populates="assignments")
    project: Mapped[Project | None] = relationship(back_populates="assignments")
    items: Mapped[list[AssignmentItem]] = relationship(back_populates="assignment", cascade="all, delete-orphan")


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
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.projects.id", ondelete="SET NULL"), nullable=True
    )
    scored_by: Mapped[str] = mapped_column(String(32), nullable=False, server_default="human")
    score_numeric: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    score_max: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    letter: Mapped[str | None] = mapped_column(String(8), nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    rubric_scores_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    evidence_refs_json: Mapped[list[Any] | dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped[Student] = relationship(back_populates="grades")


class SkillObservation(Base):
    """Time-series skill signals; agents or apps append rows (e.g. spelling.level)."""

    __tablename__ = "skill_observations"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.students.id", ondelete="CASCADE"), nullable=False
    )
    skill_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scale_min: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    scale_max: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    value_numeric: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="system")
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    context_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.assignments.id", ondelete="SET NULL"), nullable=True
    )
    observed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped[Student] = relationship(back_populates="skill_observations")
