"""HTTP API for the shared `core` schema (students, projects, assignments, grades, skills)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import core_db_enabled
from app.core.deps import get_core_pg_session
from app.core.models import Assignment, AssignmentItem, Grade, Project, SkillObservation, Student
from app.apps.dictation import session_words as dictation_session
from app.core.schemas import (
    DictationProfileOut,
    AssignmentCreate,
    AssignmentItemCreate,
    AssignmentItemOut,
    AssignmentOut,
    DictationSessionCommitRequest,
    DictationSessionCommitResponse,
    DictationSessionDraftRequest,
    DictationSessionDraftResponse,
    GradeCreate,
    GradeOut,
    ProjectCreate,
    ProjectOut,
    SkillObservationCreate,
    SkillObservationOut,
    StudentCreate,
    StudentOut,
    StudentUpdate,
)

router = APIRouter(prefix="/core", tags=["Core (Postgres)"])

SessionDep = Annotated[AsyncSession, Depends(get_core_pg_session)]


@router.get("/health")
async def core_health():
    return {"core_db_configured": core_db_enabled()}


@router.get("/students", response_model=list[StudentOut])
async def list_students(session: SessionDep, limit: int = Query(100, ge=1, le=500)):
    result = await session.scalars(select(Student).order_by(Student.display_name).limit(limit))
    return list(result)


@router.post("/students", response_model=StudentOut)
async def create_student(session: SessionDep, body: StudentCreate):
    meta = dict(body.metadata or {})
    level = int(meta.get("dictation_skill_level", 5))
    level = max(1, min(10, level))
    row = Student(
        display_name=body.display_name,
        notes=body.notes,
        metadata_=meta,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    try:
        dictation_session.ensure_dictation_user(str(row.id), row.display_name, level)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Student saved in core but dictation profile sync failed: {exc}",
        ) from exc
    return row


@router.get("/students/{student_id}", response_model=StudentOut)
async def get_student(session: SessionDep, student_id: uuid.UUID):
    row = await session.get(Student, student_id)
    if not row:
        raise HTTPException(status_code=404, detail="Student not found")
    return row


@router.patch("/students/{student_id}", response_model=StudentOut)
async def update_student(session: SessionDep, student_id: uuid.UUID, body: StudentUpdate):
    row = await session.get(Student, student_id)
    if not row:
        raise HTTPException(status_code=404, detail="Student not found")
    if body.display_name is not None:
        row.display_name = body.display_name
    if body.notes is not None:
        row.notes = body.notes
    if body.metadata is not None:
        row.metadata_ = body.metadata
    await session.flush()
    await session.refresh(row)
    meta = dict(row.metadata_ or {})
    level = int(meta.get("dictation_skill_level", 5))
    level = max(1, min(10, level))
    try:
        dictation_session.ensure_dictation_user(str(row.id), row.display_name, level)
    except Exception:
        pass
    return row


@router.get("/students/{student_id}/dictation-profile", response_model=DictationProfileOut)
async def get_dictation_profile(session: SessionDep, student_id: uuid.UUID):
    row = await _require_student(session, student_id)
    meta = dict(row.metadata_ or {})
    level = int(meta.get("dictation_skill_level", 5))
    level = max(1, min(10, level))
    try:
        uid = dictation_session.ensure_dictation_user(str(row.id), row.display_name, level)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return DictationProfileOut(
        student_id=row.id,
        dictation_user_id=uid,
        display_name=row.display_name,
        dictation_skill_level=level,
    )


@router.post(
    "/students/{student_id}/dictation-session/draft",
    response_model=DictationSessionDraftResponse,
)
async def draft_dictation_word_session(
    session: SessionDep,
    student_id: uuid.UUID,
    body: DictationSessionDraftRequest,
):
    row = await _require_student(session, student_id)
    meta = dict(row.metadata_ or {})
    level = int(meta.get("dictation_skill_level", 5))
    level = max(1, min(10, level))
    try:
        uid = dictation_session.ensure_dictation_user(str(row.id), row.display_name, level)
        data = await dictation_session.draft_daily_session_dictation(uid, body.target_daily_words)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return DictationSessionDraftResponse(
        due_count=data["due_count"],
        suggested_words=data["suggested_words"],
        difficulty=data["difficulty"],
        dictation_user_id=uid,
    )


@router.post(
    "/students/{student_id}/dictation-session/commit",
    response_model=DictationSessionCommitResponse,
)
async def commit_dictation_word_session(
    session: SessionDep,
    student_id: uuid.UUID,
    body: DictationSessionCommitRequest,
):
    row = await _require_student(session, student_id)
    meta = dict(row.metadata_ or {})
    level = int(meta.get("dictation_skill_level", 5))
    level = max(1, min(10, level))
    words = [w.strip() for w in body.words if w and str(w).strip()]
    if not words:
        raise HTTPException(status_code=400, detail="No words to assign")
    try:
        uid = dictation_session.ensure_dictation_user(str(row.id), row.display_name, level)
        result = await dictation_session.commit_daily_session_dictation(uid, words)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    assign = Assignment(
        student_id=student_id,
        project_id=None,
        title="Spelling words (dictation)",
        app_slug="dictation",
        status="assigned",
        instructions="Words assigned from Homeschool admin for dictation practice.",
        rubric_json=None,
        metadata_={"dictation_user_id": uid, "word_count": len(words)},
    )
    session.add(assign)
    await session.flush()
    for i, w in enumerate(words):
        if not w:
            continue
        session.add(
            AssignmentItem(
                assignment_id=assign.id,
                sequence=i,
                item_type="spelling_word",
                payload_json={"word": w.lower()},
            )
        )
    await session.flush()
    await session.refresh(assign)
    return DictationSessionCommitResponse(
        dictation_user_id=uid,
        assignment_id=assign.id,
        assigned_count=result["assigned_count"],
        message=f"Added {result['assigned_count']} new word assignment(s) in Postgres (already-assigned words skipped).",
    )


@router.get("/students/{student_id}/projects", response_model=list[ProjectOut])
async def list_projects(session: SessionDep, student_id: uuid.UUID):
    await _require_student(session, student_id)
    result = await session.scalars(
        select(Project).where(Project.student_id == student_id).order_by(Project.created_at.desc())
    )
    return list(result)


@router.post("/students/{student_id}/projects", response_model=ProjectOut)
async def create_project(session: SessionDep, student_id: uuid.UUID, body: ProjectCreate):
    await _require_student(session, student_id)
    row = Project(
        student_id=student_id,
        title=body.title,
        description=body.description,
        status=body.status,
        originating_app=body.originating_app,
        metadata_=body.metadata,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


@router.get("/students/{student_id}/assignments", response_model=list[AssignmentOut])
async def list_assignments(session: SessionDep, student_id: uuid.UUID):
    await _require_student(session, student_id)
    result = await session.scalars(
        select(Assignment)
        .where(Assignment.student_id == student_id)
        .options(selectinload(Assignment.items))
        .order_by(Assignment.created_at.desc())
    )
    return list(result)


@router.post("/students/{student_id}/assignments", response_model=AssignmentOut)
async def create_assignment(session: SessionDep, student_id: uuid.UUID, body: AssignmentCreate):
    await _require_student(session, student_id)
    if body.project_id:
        proj = await session.get(Project, body.project_id)
        if not proj or proj.student_id != student_id:
            raise HTTPException(status_code=400, detail="Invalid project_id for this student")
    row = Assignment(
        student_id=student_id,
        project_id=body.project_id,
        title=body.title,
        app_slug=body.app_slug,
        status=body.status,
        due_at=body.due_at,
        instructions=body.instructions,
        rubric_json=body.rubric_json,
        metadata_=body.metadata,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


@router.post(
    "/students/{student_id}/assignments/{assignment_id}/items",
    response_model=AssignmentItemOut,
)
async def add_assignment_item(
    session: SessionDep,
    student_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: AssignmentItemCreate,
):
    a = await _require_assignment(session, student_id, assignment_id)
    row = AssignmentItem(
        assignment_id=a.id,
        sequence=body.sequence,
        item_type=body.item_type,
        payload_json=body.payload_json,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


@router.get("/students/{student_id}/grades", response_model=list[GradeOut])
async def list_grades(session: SessionDep, student_id: uuid.UUID, limit: int = Query(100, ge=1, le=500)):
    await _require_student(session, student_id)
    result = await session.scalars(
        select(Grade).where(Grade.student_id == student_id).order_by(Grade.created_at.desc()).limit(limit)
    )
    return list(result)


@router.post("/students/{student_id}/grades", response_model=GradeOut)
async def create_grade(session: SessionDep, student_id: uuid.UUID, body: GradeCreate):
    await _require_student(session, student_id)
    if body.assignment_id:
        await _require_assignment(session, student_id, body.assignment_id)
    if body.project_id:
        p = await session.get(Project, body.project_id)
        if not p or p.student_id != student_id:
            raise HTTPException(status_code=400, detail="Invalid project_id for this student")
    row = Grade(
        student_id=student_id,
        assignment_id=body.assignment_id,
        project_id=body.project_id,
        scored_by=body.scored_by,
        score_numeric=body.score_numeric,
        score_max=body.score_max,
        letter=body.letter,
        feedback=body.feedback,
        rubric_scores_json=body.rubric_scores_json,
        evidence_refs_json=body.evidence_refs_json,
        metadata_=body.metadata,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


@router.get("/students/{student_id}/skills", response_model=list[SkillObservationOut])
async def list_skills(
    session: SessionDep,
    student_id: uuid.UUID,
    skill_key: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
):
    await _require_student(session, student_id)
    q = select(SkillObservation).where(SkillObservation.student_id == student_id)
    if skill_key:
        q = q.where(SkillObservation.skill_key == skill_key)
    q = q.order_by(SkillObservation.created_at.desc()).limit(limit)
    result = await session.scalars(q)
    return list(result)


@router.post("/students/{student_id}/skills", response_model=SkillObservationOut)
async def create_skill_observation(session: SessionDep, student_id: uuid.UUID, body: SkillObservationCreate):
    await _require_student(session, student_id)
    if body.context_assignment_id:
        await _require_assignment(session, student_id, body.context_assignment_id)
    row = SkillObservation(
        student_id=student_id,
        skill_key=body.skill_key,
        scale_min=body.scale_min,
        scale_max=body.scale_max,
        value_numeric=body.value_numeric,
        value_text=body.value_text,
        source=body.source,
        confidence=body.confidence,
        context_assignment_id=body.context_assignment_id,
        observed_on=body.observed_on,
        metadata_=body.metadata,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def _require_student(session: AsyncSession, student_id: uuid.UUID) -> Student:
    row = await session.get(Student, student_id)
    if not row:
        raise HTTPException(status_code=404, detail="Student not found")
    return row


async def _require_assignment(session: AsyncSession, student_id: uuid.UUID, assignment_id: uuid.UUID) -> Assignment:
    row = await session.get(Assignment, assignment_id)
    if not row or row.student_id != student_id:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return row
