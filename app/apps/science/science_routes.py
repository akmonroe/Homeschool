"""API routes for the Science sub-app (experiments, templates, media)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.apps.science import storage
from app.core.deps import get_core_pg_session
from app.core.models import Assignment, ScienceExperimentRun, ScienceExperimentTemplate, ScienceMedia, Student

router = APIRouter(prefix="/v1", tags=["Science lab"])

SessionDep = Annotated[AsyncSession, Depends(get_core_pg_session)]

APP_SLUG = "science"


# --- Schemas ---


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    summary: str | None
    subject_tags: list[Any]
    procedure_outline: str | None


class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    kind: str
    content_type: str | None
    file_size: int | None
    caption: str | None
    url: str
    created_at: datetime


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    student_id: uuid.UUID
    title: str
    source: str
    status: str
    assignment_id: uuid.UUID | None
    template_id: uuid.UUID | None
    hypothesis: str | None
    materials: str | None
    procedure_notes: str | None
    conclusions: str | None
    observations: list[Any] = []
    created_at: datetime
    updated_at: datetime
    media: list[MediaOut] = []


def _run_to_out(r: ScienceExperimentRun, include_media: bool) -> RunOut:
    med = r.media if include_media else []
    return RunOut(
        id=r.id,
        student_id=r.student_id,
        title=r.title,
        source=r.source,
        status=r.status,
        assignment_id=r.assignment_id,
        template_id=r.template_id,
        hypothesis=r.hypothesis,
        materials=r.materials,
        procedure_notes=r.procedure_notes,
        conclusions=r.conclusions,
        observations=list(r.observations_json or []),
        created_at=r.created_at,
        updated_at=r.updated_at,
        media=[
            MediaOut(
                id=m.id,
                run_id=m.run_id,
                kind=m.kind,
                content_type=m.content_type,
                file_size=m.file_size,
                caption=m.caption,
                url=f"/apps/science/v1/media/{m.id}/file?student_id={r.student_id}",
                created_at=m.created_at,
            )
            for m in med
        ],
    )


class RunCreateFromTemplate(BaseModel):
    template_id: uuid.UUID
    title: str | None = Field(None, max_length=500)
    take_title_from_template: bool = True


class RunCreateAdHoc(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)


class RunUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    hypothesis: str | None = None
    materials: str | None = None
    procedure_notes: str | None = None
    conclusions: str | None = None
    observations: list[Any] | None = None


class StartFromAssignmentIn(BaseModel):
    assignment_id: uuid.UUID
    template_id: uuid.UUID | None = None
    take_title_from_assignment: bool = True


class ScienceAssignmentSummary(BaseModel):
    id: uuid.UUID
    title: str
    instructions: str | None
    status: str
    due_at: datetime | None


# --- Helpers ---


async def _get_student_or_404(session: AsyncSession, student_id: uuid.UUID) -> Student:
    s = await session.get(Student, student_id)
    if not s:
        raise HTTPException(404, "Student not found.")
    return s


# --- Endpoints ---


@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(session: SessionDep):
    rows = await session.scalars(
        select(ScienceExperimentTemplate)
        .where(ScienceExperimentTemplate.is_published.is_(True))
        .order_by(ScienceExperimentTemplate.title)
    )
    return list(rows)


@router.get("/assignments", response_model=list[ScienceAssignmentSummary])
async def list_science_assignments_for_student(
    session: SessionDep,
    student_id: uuid.UUID = Query(..., description="Core student UUID"),
    active: bool = True,
):
    await _get_student_or_404(session, student_id)
    now = datetime.now(timezone.utc)
    stmt = select(Assignment).where(
        Assignment.student_id == student_id,
        Assignment.app_slug == APP_SLUG,
    )
    if active:
        stmt = stmt.where(
            and_(
                or_(Assignment.due_at.is_(None), Assignment.due_at >= now),
                Assignment.status != "cancelled",
            )
        )
    stmt = stmt.order_by(Assignment.created_at.desc())
    out = await session.scalars(stmt)
    return [
        ScienceAssignmentSummary(
            id=a.id,
            title=a.title,
            instructions=a.instructions,
            status=a.status,
            due_at=a.due_at,
        )
        for a in out
    ]


@router.post(
    "/students/{student_id}/runs/from-template",
    response_model=RunOut,
)
async def start_run_from_template(
    session: SessionDep, student_id: uuid.UUID, body: RunCreateFromTemplate
):
    await _get_student_or_404(session, student_id)
    tpl = await session.get(ScienceExperimentTemplate, body.template_id)
    if not tpl or not tpl.is_published:
        raise HTTPException(404, "Template not found.")
    title = tpl.title
    if not body.take_title_from_template and body.title:
        title = body.title.strip()
    r = ScienceExperimentRun(
        student_id=student_id,
        template_id=tpl.id,
        assignment_id=None,
        title=title,
        source="self_chosen",
        status="in_progress",
    )
    session.add(r)
    await session.flush()
    if tpl.procedure_outline and not (r.procedure_notes or "").strip():
        r.procedure_notes = tpl.procedure_outline
    await session.flush()
    await session.refresh(r, ["media"])
    return _run_to_out(r, include_media=True)


@router.post("/students/{student_id}/runs/ad-hoc", response_model=RunOut)
async def start_ad_hoc_run(session: SessionDep, student_id: uuid.UUID, body: RunCreateAdHoc):
    await _get_student_or_404(session, student_id)
    r = ScienceExperimentRun(
        student_id=student_id,
        template_id=None,
        assignment_id=None,
        title=body.title.strip(),
        source="ad_hoc",
        status="in_progress",
    )
    session.add(r)
    await session.flush()
    await session.refresh(r, ["media"])
    return _run_to_out(r, include_media=True)


@router.post(
    "/students/{student_id}/runs/from-assignment",
    response_model=RunOut,
)
async def start_from_assignment(
    session: SessionDep, student_id: uuid.UUID, body: StartFromAssignmentIn
):
    await _get_student_or_404(session, student_id)
    a = await session.get(Assignment, body.assignment_id)
    if not a or a.student_id != student_id:
        raise HTTPException(404, "Assignment not found for this student.")
    if a.app_slug != APP_SLUG:
        raise HTTPException(400, "This assignment is not a science lab assignment (app must be 'science').")
    title = a.title
    if not body.take_title_from_assignment and a.instructions:
        # optional: use first line -- keep simple, title stays assignment title
        pass
    tpl: ScienceExperimentTemplate | None = None
    if body.template_id:
        tpl = await session.get(ScienceExperimentTemplate, body.template_id)
        if not tpl:
            raise HTTPException(404, "Template not found.")
    r = ScienceExperimentRun(
        student_id=student_id,
        template_id=tpl.id if tpl else None,
        assignment_id=a.id,
        title=title,
        source="assigned",
        status="in_progress",
    )
    if a.instructions:
        r.procedure_notes = a.instructions
    if tpl and tpl.procedure_outline:
        r.procedure_notes = (r.procedure_notes or "") + "\n\n" + tpl.procedure_outline
    session.add(r)
    await session.flush()
    await session.refresh(r, ["media"])
    return _run_to_out(r, include_media=True)


@router.get("/students/{student_id}/runs", response_model=list[RunOut])
async def list_runs_for_student(
    session: SessionDep, student_id: uuid.UUID, limit: int = 100, offset: int = 0
):
    await _get_student_or_404(session, student_id)
    if limit < 1 or limit > 500 or offset < 0:
        raise HTTPException(400, "Invalid pagination.")
    q = (
        select(ScienceExperimentRun)
        .options(selectinload(ScienceExperimentRun.media))
        .where(ScienceExperimentRun.student_id == student_id)
        .order_by(ScienceExperimentRun.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = await session.scalars(q)
    return [_run_to_out(r, include_media=True) for r in rows]


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(
    session: SessionDep,
    run_id: uuid.UUID,
    student_id: uuid.UUID = Query(..., description="Core student UUID"),
):
    await _get_student_or_404(session, student_id)
    r = await session.scalar(
        select(ScienceExperimentRun)
        .options(selectinload(ScienceExperimentRun.media))
        .where(ScienceExperimentRun.id == run_id, ScienceExperimentRun.student_id == student_id)
    )
    if not r:
        raise HTTPException(404, "Experiment not found.")
    return _run_to_out(r, include_media=True)


@router.patch("/runs/{run_id}", response_model=RunOut)
async def update_run(
    session: SessionDep,
    run_id: uuid.UUID,
    student_id: uuid.UUID = Query(..., description="Core student UUID"),
    body: RunUpdate = ...
):
    r = await session.scalar(
        select(ScienceExperimentRun)
        .options(selectinload(ScienceExperimentRun.media))
        .where(ScienceExperimentRun.id == run_id, ScienceExperimentRun.student_id == student_id)
    )
    if not r:
        raise HTTPException(404, "Experiment not found.")
    d = body.model_dump(exclude_unset=True)
    for k, v in d.items():
        if k == "observations":
            setattr(r, "observations_json", v)
        else:
            setattr(r, k, v)
    await session.flush()
    return _run_to_out(r, include_media=True)


@router.post(
    "/runs/{run_id}/observations/append",
    response_model=RunOut,
)
async def append_observation(
    session: SessionDep,
    run_id: uuid.UUID,
    student_id: uuid.UUID = Query(..., description="Core student UUID"),
    note: str = Form(...),
):
    r = await session.scalar(
        select(ScienceExperimentRun)
        .options(selectinload(ScienceExperimentRun.media))
        .where(ScienceExperimentRun.id == run_id, ScienceExperimentRun.student_id == student_id)
    )
    if not r:
        raise HTTPException(404, "Experiment not found.")
    t = (note or "").strip()
    if not t:
        raise HTTPException(400, "Observation text is required.")
    obs: list = list(r.observations_json or [])
    obs.append({"at": datetime.now(timezone.utc).isoformat(), "text": t})
    r.observations_json = obs
    await session.flush()
    return _run_to_out(r, include_media=True)


@router.post("/runs/{run_id}/media", response_model=MediaOut)
async def upload_media(
    session: SessionDep,
    run_id: uuid.UUID,
    student_id: uuid.UUID = Query(..., description="Core student UUID"),
    file: UploadFile = File(...),
    caption: str | None = Form(None),
):
    r = await session.get(ScienceExperimentRun, run_id)
    if not r or r.student_id != student_id:
        raise HTTPException(404, "Experiment not found.")
    ct = file.content_type
    if not storage.is_allowed_content_type(ct):
        raise HTTPException(400, "Unsupported file type. Use a common image or video format.")
    if not ct:
        raise HTTPException(400, "File must have a content type (e.g. image/jpeg).")
    mid = uuid.uuid4()
    try:
        rel, kind, size = storage.write_stream(run_id, mid, file.file, content_type=ct)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    row = ScienceMedia(
        id=mid,
        run_id=run_id,
        rel_path=rel,
        original_filename=file.filename,
        content_type=ct,
        kind=kind,
        file_size=size,
        caption=(caption or "").strip() or None,
    )
    session.add(row)
    await session.flush()
    sid = str(student_id)
    return MediaOut(
        id=row.id,
        run_id=row.run_id,
        kind=row.kind,
        content_type=row.content_type,
        file_size=row.file_size,
        caption=row.caption,
        url=f"/apps/science/v1/media/{row.id}/file?student_id={sid}",
        created_at=row.created_at,
    )


@router.get("/media/{media_id}/file")
async def serve_media_file(
    session: SessionDep,
    media_id: uuid.UUID,
    student_id: uuid.UUID = Query(..., description="Core student UUID"),
):
    from fastapi.responses import FileResponse

    m = await session.get(ScienceMedia, media_id)
    if not m:
        raise HTTPException(404, "File not found.")
    run = await session.get(ScienceExperimentRun, m.run_id)
    if not run or run.student_id != student_id:
        raise HTTPException(404, "File not found.")
    try:
        p = storage.file_path_for_rel(m.rel_path)
    except ValueError:
        raise HTTPException(404, "File missing on disk.")
    if not p.is_file():
        raise HTTPException(404, "File missing on disk.")
    return FileResponse(p, media_type=m.content_type or "application/octet-stream")


@router.delete("/runs/{run_id}")
async def delete_run(
    session: SessionDep,
    run_id: uuid.UUID,
    student_id: uuid.UUID = Query(..., description="Core student UUID"),
):
    r = await session.scalar(
        select(ScienceExperimentRun).where(
            ScienceExperimentRun.id == run_id, ScienceExperimentRun.student_id == student_id
        )
    )
    if not r:
        raise HTTPException(404, "Experiment not found.")
    rid = r.id
    await session.delete(r)
    await session.flush()
    storage.delete_run_folder(rid)
    return {"ok": True}
