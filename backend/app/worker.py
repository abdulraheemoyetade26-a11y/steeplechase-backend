import json
import threading
from .models import User
from sqlalchemy import select
from .plans import pages_remaining
from .database import SessionLocal
from .models import ImageItem, ProcessingJob, Source, naive_now
from .ocr import OcrUnavailable, run_ocr_for_source
from .page_rendering import render_source_pages

POLL_SECONDS = 2.0
MAX_JOB_PAGES = 150

_stop = threading.Event()
_thread: threading.Thread | None = None


def enqueue_job(db, source, scope: str = "image_pages", pages: list[int] | None = None) -> ProcessingJob:
    job = ProcessingJob(
        user_id=source.user_id,
        source_id=source.id,
        scope=scope,
        pages_json=json.dumps(sorted({p for p in (pages or []) if p >= 1})),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def has_active_job(db, source_id: int) -> bool:
    found = db.scalar(
        select(ProcessingJob.id)
        .where(ProcessingJob.source_id == source_id, ProcessingJob.status.in_(["queued", "running"]))
        .limit(1)
    )
    return found is not None


def job_summary(job: ProcessingJob) -> dict:
    return {
        "id": job.id,
        "source_id": job.source_id,
        "status": job.status,
        "scope": job.scope,
        "pages_total": job.pages_total,
        "pages_done": job.pages_done,
        "pages_failed": job.pages_failed,
        "labels_found": job.labels_found,
        "note": job.note,
        "error": job.error,
        "cancel_requested": job.cancel_requested,
    }


def _choose_pages(db, source, job) -> tuple[list[int], str]:
    note = ""
    try:
        explicit = json.loads(job.pages_json or "[]")
    except ValueError:
        explicit = []
    pages = sorted({p for p in explicit if isinstance(p, int) and p >= 1})

    if not pages and job.scope == "image_pages":
        rows = db.scalars(
            select(ImageItem.location_number)
            .where(ImageItem.source_id == source.id, ImageItem.status != "rejected")
            .distinct()
        ).all()
        pages = sorted(rows)
        if not pages:
            note = "No embedded pictures were found, so every page is being processed."
    if not pages:
        pages = list(range(1, (source.unit_count or 0) + 1))

    if len(pages) > MAX_JOB_PAGES:
        note = (note + " " if note else "") + f"Only the first {MAX_JOB_PAGES} pages were processed."
        pages = pages[:MAX_JOB_PAGES]
    return pages, note


def _execute(db, job_id: int) -> None:
    job = db.get(ProcessingJob, job_id)
    source = db.get(Source, job.source_id)
    user = db.get(User, source.user_id)
    
    if source is None or source.status != "ready" or user is None:
        raise ValueError("The source is missing or was not read successfully")

    pages, note = _choose_pages(db, source, job)
    job.pages_total = len(pages)
    job.note = note[:300]
    db.commit()

    for number in pages:
        db.refresh(job)
        if job.cancel_requested:
            job.status = "cancelled"
            job.finished_at = naive_now()
            db.commit()
            return
        if db.get(Source, job.source_id) is None:
            raise ValueError("The source was deleted while it was being processed")
            
        # THE LIMIT CHECK
        if pages_remaining(user, db) <= 0:
            job.note = "Monthly page allowance reached. Upgrade to process more."
            job.status = "done"
            job.finished_at = naive_now()
            db.commit()
            return
            
        try:
            render_source_pages(db, source, [number])
            db.commit()
            result = run_ocr_for_source(db, source.id, [number])
            job.labels_found += result["labels_found"]
            
            # Deduct 1 page
            user.pages_processed_this_month += 1
            
        except (OcrUnavailable, ValueError):
            raise
        except Exception:
            db.rollback()
            job.pages_failed += 1
        job.pages_done += 1
        db.commit()

    job.status = "done"
    job.finished_at = naive_now()
    db.commit()


def run_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        _execute(db, job_id)
    except Exception as exc:
        db.rollback()
        job = db.get(ProcessingJob, job_id)
        if job is not None and job.status == "running":
            job.status = "failed"
            job.error = str(exc)[:500]
            job.finished_at = naive_now()
            db.commit()
    finally:
        db.close()


def _claim_next_job() -> int | None:
    db = SessionLocal()
    try:
        job = db.scalar(
            select(ProcessingJob).where(ProcessingJob.status == "queued").order_by(ProcessingJob.id).limit(1)
        )
        if job is None:
            return None
        job.status = "running"
        job.started_at = naive_now()
        db.commit()
        return job.id
    finally:
        db.close()


def _loop() -> None:
    while not _stop.is_set():
        try:
            job_id = _claim_next_job()
        except Exception:
            job_id = None
        if job_id is None:
            _stop.wait(POLL_SECONDS)
            continue
        run_job(job_id)


def reset_stuck_jobs() -> None:
    """After a restart, jobs that were running go back to the queue. Finished pages are skipped."""
    db = SessionLocal()
    try:
        for job in db.scalars(select(ProcessingJob).where(ProcessingJob.status == "running")).all():
            job.status = "queued"
            job.pages_done = 0
            job.pages_failed = 0
            job.labels_found = 0
        db.commit()
    finally:
        db.close()


def start_worker() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    reset_stuck_jobs()
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="processing-worker", daemon=True)
    _thread.start()


def stop_worker() -> None:
    _stop.set()