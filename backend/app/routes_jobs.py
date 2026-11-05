from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .deps import get_current_user
from .models import ProcessingJob, User, naive_now
from .routes_sources import get_own_source
from .worker import enqueue_job, has_active_job, job_summary

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobCreate(BaseModel):
    scope: Literal["image_pages", "all_pages"] = "image_pages"
    pages: list[int] | None = None


def own_job(db: Session, job_id: int, user: User) -> ProcessingJob:
    job = db.get(ProcessingJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(404, "Job not found")
    return job


@router.post("/process/{source_id}")
def start_processing(
    source_id: int,
    data: JobCreate | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = get_own_source(db, source_id, user)
    if source.status != "ready":
        raise HTTPException(400, "Only files that were read successfully can be processed")
    if source.file_type not in ("pdf", "pptx"):
        raise HTTPException(400, "Only PDF and PowerPoint files can be processed into practice labels")
    if has_active_job(db, source.id):
        raise HTTPException(409, "This file is already being processed")
    scope = data.scope if data else "image_pages"
    pages = data.pages if data else None
    return job_summary(enqueue_job(db, source, scope=scope, pages=pages))


@router.get("")
def list_jobs(
    source_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(ProcessingJob).where(ProcessingJob.user_id == user.id)
    if source_id is not None:
        query = query.where(ProcessingJob.source_id == source_id)
    return [job_summary(j) for j in db.scalars(query.order_by(ProcessingJob.id.desc()).limit(20)).all()]


@router.get("/{job_id}")
def job_detail(job_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return job_summary(own_job(db, job_id, user))


@router.post("/{job_id}/cancel")
def cancel_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = own_job(db, job_id, user)
    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = naive_now()
    elif job.status == "running":
        job.cancel_requested = True
    else:
        raise HTTPException(409, "This job has already finished")
    db.commit()
    return job_summary(job)