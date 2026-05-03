from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StudentCreate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=255)
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudentUpdate(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=255)
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class StudentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    display_name: str
    notes: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_", serialization_alias="metadata")
    created_at: datetime
    updated_at: datetime


class AssignmentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    app_slug: str | None = None
    status: str = "draft"
    available_from: datetime | None = Field(
        None,
        description="When the assignment becomes available (timezone-aware). Null = no start gate.",
    )
    due_at: datetime | None = Field(
        None,
        description="When the assignment is due (timezone-aware). Null = no fixed deadline.",
    )
    instructions: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssignmentUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    app_slug: str | None = None
    status: str | None = None
    available_from: datetime | None = None
    due_at: datetime | None = None
    instructions: str | None = None
    metadata: dict[str, Any] | None = None


class AssignmentItemCreate(BaseModel):
    sequence: int = 0
    item_type: str = Field(..., min_length=1, max_length=64)
    payload_json: dict[str, Any] = Field(default_factory=dict)


class AssignmentItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    assignment_id: uuid.UUID
    sequence: int
    item_type: str
    payload_json: dict[str, Any]
    created_at: datetime


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    student_id: uuid.UUID
    title: str
    app_slug: str | None
    status: str
    available_from: datetime | None
    due_at: datetime | None
    instructions: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_", serialization_alias="metadata")
    created_at: datetime
    updated_at: datetime
    items: list[AssignmentItemOut] = Field(
        default_factory=list,
        description="Tall items (e.g. spelling_word rows with payload word).",
    )


class GradeCreate(BaseModel):
    assignment_id: uuid.UUID | None = None
    scored_by: str = "human"
    score_numeric: float | None = None
    score_max: float | None = None
    letter: str | None = None
    feedback: str | None = None
    completed_at: datetime | None = Field(
        None,
        description="When the learner finished/submitted the work (timezone-aware).",
    )
    graded_at: datetime | None = Field(
        None,
        description="When the grade was recorded; defaults to request time if omitted.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class GradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    student_id: uuid.UUID
    assignment_id: uuid.UUID | None
    scored_by: str
    score_numeric: float | None
    score_max: float | None
    letter: str | None
    feedback: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_", serialization_alias="metadata")
    completed_at: datetime | None
    graded_at: datetime | None
    created_at: datetime


class GradeUpdate(BaseModel):
    assignment_id: uuid.UUID | None = None
    scored_by: str | None = None
    score_numeric: float | None = None
    score_max: float | None = None
    letter: str | None = None
    feedback: str | None = None
    completed_at: datetime | None = None
    graded_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class DictationSessionDraftRequest(BaseModel):
    target_daily_words: int = Field(
        10,
        ge=1,
        le=50,
        description="How many new words the AI should suggest (not reduced by current backlog).",
    )


class DictationSessionDraftResponse(BaseModel):
    due_count: int
    suggested_words: list[str]
    difficulty: int
    dictation_user_id: int
    pool_size: int = Field(
        0,
        description="Count of dictionary words not yet assigned to this student (candidates for suggestions).",
    )


class DictationSessionCommitRequest(BaseModel):
    words: list[str]
    due_at: datetime | None = Field(
        None,
        description="Core assignment deadline (timezone-aware ISO). Defaults to 7 days from commit time.",
    )


class DictationProfileOut(BaseModel):
    student_id: uuid.UUID
    dictation_user_id: int
    display_name: str
    dictation_skill_level: int


class DictationSessionCommitResponse(BaseModel):
    dictation_user_id: int
    assignment_id: uuid.UUID
    assigned_count: int
    message: str
    due_at: datetime | None = None


class DictationQueueSyncRequest(BaseModel):
    due_at: datetime | None = Field(
        None,
        description="Due date for the suite assignment (defaults to 7 days from now).",
    )
    title: str | None = Field(
        None, max_length=500, description="Override assignment title; default: Spelling words (dictation)."
    )


class DictationQueueSyncResponse(BaseModel):
    """Mirrors the dictation practice queue (Postgres) into a suite `core.assignment` + items."""

    dictation_user_id: int
    assignment_id: uuid.UUID
    item_count: int
    message: str
    due_at: datetime | None = None
