from .plans import effective_plan, PLAN_LIMITS
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .deps import get_current_user
from .extraction import EXTRACTORS, extract_file, split_text
from .image_extraction import store_images
from .models import Chunk, Course, ImageItem, Source, User
from .schemas import ChunkOut, SourceOut
from .worker import enqueue_job

router = APIRouter(prefix="/sources", tags=["sources"])

UNSUPPORTED_HINT = {
    ".ppt": "Old PowerPoint files are not supported. Save the file as .pptx and upload again.",
    ".doc": "Old Word files are not supported. Save the file as .docx and upload again.",
}


def get_own_source(db: Session, source_id: int, user: User) -> Source:
    source = db.get(Source, source_id)
    if source is None or source.user_id != user.id:
        raise HTTPException(404, "Source not found")
    return source


@router.post("/upload", response_model=SourceOut)
def upload_source(
    file: UploadFile = File(...),
    course_id: int | None = Form(None),
    process: bool = Form(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext in UNSUPPORTED_HINT:
        raise HTTPException(400, UNSUPPORTED_HINT[ext])
    if ext not in EXTRACTORS:
        raise HTTPException(400, f"File type {ext or '(none)'} is not supported.")

    # Plan limits
    plan = effective_plan(user)
    max_decks = PLAN_LIMITS[plan]["max_decks"]
    deck_count = db.scalar(select(func.count()).select_from(Source).where(Source.user_id == user.id))
    if deck_count >= max_decks:
        raise HTTPException(400, f"You have reached your deck limit ({max_decks} decks) on the {plan.capitalize()} plan.")
        
    max_file_mb = PLAN_LIMITS[plan]["max_file_mb"]
    max_bytes = max_file_mb * 1024 * 1024

    if course_id is not None:
        course = db.get(Course, course_id)
        if course is None or course.user_id != user.id:
            raise HTTPException(404, "Course not found")

    user_dir = Path(settings.upload_dir) / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    stored = user_dir / f"{uuid.uuid4().hex}{ext}"

    # Stream to disk and check size safely
    size = 0
    with open(stored, "wb") as out:
        while True:
            block = file.file.read(1024 * 1024) # Read 1MB at a time
            if not block:
                break
            size += len(block)
            if size > max_bytes:
                out.close()
                stored.unlink(missing_ok=True) # Delete the partial file
                raise HTTPException(413, f"File is too large. Your plan allows up to {max_file_mb} MB.")
            out.write(block)

    source = Source(
        user_id=user.id,
        course_id=course_id,
        filename=(file.filename or "file")[:300],
        file_type=ext.lstrip("."),
        stored_path=str(stored),
        status="processing",
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    try:
        units, count = extract_file(stored, ext)
        order = 0
        for location_type, number, text in units:
            for piece in split_text(text):
                db.add(
                    Chunk(
                        source_id=source.id,
                        order_index=order,
                        location_type=location_type,
                        location_number=number,
                        text=piece,
                    )
                )
                order += 1
        source.unit_count = count
        source.status = "ready"
        db.commit()
    except Exception as exc:
        db.rollback()
        source = db.get(Source, source.id)
        source.status = "failed"
        source.error = str(exc)[:500]
        db.commit()

    if source.status == "ready":
        try:
            store_images(db, source, ext)
            db.commit()
        except Exception:
            db.rollback()

    if source.status == "ready" and ext in (".pdf", ".pptx") and process:
        try:
            enqueue_job(db, source)
        except Exception:
            db.rollback()

    db.refresh(source)
    return source

@router.get("", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(select(Source).where(Source.user_id == user.id).order_by(Source.id.desc())).all()


@router.get("/{source_id}", response_model=SourceOut)
def get_source(source_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return get_own_source(db, source_id, user)


@router.get("/{source_id}/chunks", response_model=list[ChunkOut])
def get_chunks(source_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    source = get_own_source(db, source_id, user)
    return source.chunks


@router.delete("/{source_id}")
def delete_source(source_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    source = get_own_source(db, source_id, user)
    Path(source.stored_path).unlink(missing_ok=True)
    base = Path(settings.upload_dir) / str(source.user_id)
    for folder in ("images", "pages", "converted"):
        shutil.rmtree(base / folder / str(source.id), ignore_errors=True)
    db.delete(source)
    db.commit()
    return {"deleted": source_id}


@router.post("/{source_id}/extract-images")
def extract_images_again(source_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    source = get_own_source(db, source_id, user)
    if source.status != "ready":
        raise HTTPException(400, "Only sources with extracted text can be processed")
    existing = db.scalar(select(func.count()).select_from(ImageItem).where(ImageItem.source_id == source.id))
    if existing:
        raise HTTPException(409, "This source already has images. Review them, or delete the source and upload again.")
    count = store_images(db, source, "." + source.file_type)
    db.commit()
    return {"source_id": source.id, "images_found": count}