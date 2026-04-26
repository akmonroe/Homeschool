from __future__ import annotations

import uuid
from datetime import date, datetime
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


class ProjectCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    status: str = "active"
    originating_app: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    student_id: uuid.UUID
    title: str
    description: str | None
    status: str
    originating_app: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_", serialization_alias="metadata")
    created_at: datetime
    updated_at: datetime


class AssignmentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    project_id: uuid.UUID | None = None
    app_slug: str | None = None
    status: str = "draft"
    due_at: datetime | None = None
    instructions: str | None = None
    rubric_json: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    student_id: uuid.UUID
    project_id: uuid.UUID | None
    title: str
    app_slug: str | None
    status: str
    due_at: datetime | None
    instructions: str | None
    rubric_json: dict[str, Any] | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_", serialization_alias="metadata")
    created_at: datetime
    updated_at: datetime


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


class GradeCreate(BaseModel):
    assignment_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    scored_by: str = "human"
    score_numeric: float | None = None
    score_max: float | None = None
    letter: str | None = None
    feedback: str | None = None
    rubric_scores_json: dict[str, Any] | None = None
    evidence_refs_json: list[Any] | dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    student_id: uuid.UUID
    assignment_id: uuid.UUID | None
    project_id: uuid.UUID | None
    scored_by: str
    score_numeric: float | None
    score_max: float | None
    letter: str | None
    feedback: str | None
    rubric_scores_json: dict[str, Any] | None
    evidence_refs_json: list[Any] | dict[str, Any] | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_", serialization_alias="metadata")
    created_at: datetime


class SkillObservationCreate(BaseModel):
    skill_key: str = Field(..., min_length=1, max_length=128)
    scale_min: float | None = None
    scale_max: float | None = None
    value_numeric: float | None = None
    value_text: str | None = None
    source: str = "system"
    confidence: float | None = Field(None, ge=0, le=1)
    context_assignment_id: uuid.UUID | None = None
    observed_on: date | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DictationSessionDraftRequest(BaseModel):
    target_daily_words: int = Field(10, ge=1, le=50)


class DictationSessionDraftResponse(BaseModel):
    due_count: int
    suggested_words: list[str]
    difficulty: int
    dictation_user_id: int


class DictationSessionCommitRequest(BaseModel):
    words: list[str]


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


class SkillObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    student_id: uuid.UUID
    skill_key: str
    scale_min: float | None
    scale_max: float | None
    value_numeric: float | None
    value_text: str | None
    source: str
    confidence: float | None
    context_assignment_id: uuid.UUID | None
    observed_on: date | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_", serialization_alias="metadata")
    created_at: datetime
