"""HTTP API for the shared `core` schema (students, projects, assignments, grades, skills)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import core_db_enabled, session_scope
from app.core.models import Assignment, AssignmentItem, Grade, Project, SkillObservation, Student
from app.core.schemas import (
    AssignmentCreate,
    AssignmentItemCreate,
    AssignmentItemOut,
    AssignmentOut,
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


async def get_session():
    if not core_db_enabled():
        raise HTTPException(
            status_code=503,
            detail="Core database is not configured. Set DATABASE_URL (postgresql+asyncpg://...).",
        )
    async with session_scope() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/health")
async def core_health():
    return {"core_db_configured": core_db_enabled()}


@router.get("/students", response_model=list[StudentOut])
async def list_students(session: SessionDep, limit: int = Query(100, ge=1, le=500)):
    result = await session.scalars(select(Student).order_by(Student.display_name).limit(limit))
    return list(result)


@router.post("/students", response_model=StudentOut)
async def create_student(session: SessionDep, body: StudentCreate):
    row = Student(
        display_name=body.display_name,
        notes=body.notes,
        metadata_=body.metadata,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
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
    return row


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
