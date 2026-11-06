from .grading import normalize
from .models import ImageItem, LabelAudit, LabelRegion, PageRender, User
from .ocr import OcrUnavailable, ocr_page_regions, run_ocr_for_source
from .worker import has_active_job
import hashlib
import io
import json
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .deps import get_current_user
from .page_rendering import render_source_pages
from .routes_sources import get_own_source
from .schemas import (
    CropIn,
    ImageOut,
    PageOut,
    RegionCreate,
    RegionOut,
    RegionUpdate,
    RenderIn,
)

router = APIRouter(prefix="/pages", tags=["pages"])
region_router = APIRouter(prefix="/regions", tags=["pages"])

MAX_PAGES_PER_CALL = 60


def own_page(db: Session, page_id: int, user: User) -> PageRender:
    page = db.get(PageRender, page_id)
    if page is None or page.user_id != user.id:
        raise HTTPException(404, "Page not found")
    return page


def own_region(db: Session, region_id: int, user: User) -> LabelRegion:
    region = db.get(LabelRegion, region_id)
    if region is None or region.user_id != user.id:
        raise HTTPException(404, "Label box not found")
    return region


def clean_answers(answers: list[str], label: str) -> list[str]:
    seen, cleaned = set(), []
    for answer in answers:
        answer = answer.strip()
        key = answer.lower()
        if answer and key not in seen and key != label.strip().lower():
            seen.add(key)
            cleaned.append(answer)
    return cleaned


def ordered(a: float, b: float) -> tuple[float, float]:
    return (a, b) if a <= b else (b, a)


@router.post("/render/{source_id}")
def render_pages(
    source_id: int,
    data: RenderIn | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = get_own_source(db, source_id, user)
    if has_active_job(db, source.id):
        raise HTTPException(409, "This file is being processed in the background. Wait for it to finish.")
    if source.status != "ready":
        raise HTTPException(400, "Only sources with extracted text can be rendered")

    requested = sorted({p for p in data.pages if p >= 1}) if data and data.pages else []
    if requested:
        pages = requested
    else:
        rows = db.scalars(
            select(ImageItem.location_number).where(
                ImageItem.source_id == source.id, ImageItem.status != "rejected"
            ).distinct()
        ).all()
        pages = sorted(rows)

    if not pages:
        raise HTTPException(400, "No pages to render. This source has no extracted images, so pass the page numbers you want.")
    if len(pages) > MAX_PAGES_PER_CALL:
        raise HTTPException(400, f"Too many pages at once. Choose at most {MAX_PAGES_PER_CALL}.")

    try:
        created = render_source_pages(db, source, pages)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc))
    db.commit()

    result = {"source_id": source.id, "rendered_new_pages": created}
    if data and data.ocr:
        try:
            result["ocr"] = run_ocr_for_source(db, source.id, pages)
        except OcrUnavailable as exc:
            db.rollback()
            result["ocr_error"] = str(exc)
    return result


@router.get("", response_model=list[PageOut])
def list_pages(source_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(
        select(PageRender)
        .where(PageRender.source_id == source_id, PageRender.user_id == user.id)
        .order_by(PageRender.page_number)
    ).all()


@router.get("/{page_id}/file")
def page_file(page_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return FileResponse(own_page(db, page_id, user).file_path)


@router.get("/{page_id}/regions", response_model=list[RegionOut])
def list_regions(page_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    page = own_page(db, page_id, user)
    return db.scalars(
        select(LabelRegion).where(LabelRegion.page_id == page.id).order_by(LabelRegion.y0, LabelRegion.x0)
    ).all()


@router.post("/{page_id}/regions", response_model=RegionOut)
def create_region(
    page_id: int,
    data: RegionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    page = own_page(db, page_id, user)
    x0, x1 = ordered(data.x0, data.x1)
    y0, y1 = ordered(data.y0, data.y1)
    if x1 - x0 < 0.005 or y1 - y0 < 0.005:
        raise HTTPException(400, "The box is too small")
    region = LabelRegion(
        page_id=page.id,
        user_id=user.id,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        text=data.text.strip(),
        accepted_json=json.dumps(clean_answers(data.accepted_answers, data.text)),
        origin="manual",
        status="verified",
    )
    db.add(region)
    db.commit()
    db.refresh(region)
    return region


@router.post("/{page_id}/crop", response_model=ImageOut)
def crop_to_spotter(
    page_id: int,
    data: CropIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    page = own_page(db, page_id, user)
    x0, x1 = ordered(data.x0, data.x1)
    y0, y1 = ordered(data.y0, data.y1)

    img = Image.open(page.file_path).convert("RGB")
    width, height = img.size
    box = (int(x0 * width), int(y0 * height), int(x1 * width), int(y1 * height))
    if box[2] - box[0] < 40 or box[3] - box[1] < 40:
        raise HTTPException(400, "The crop area is too small")
    cropped = img.crop(box)

    buffer = io.BytesIO()
    cropped.save(buffer, format="JPEG", quality=90)
    payload = buffer.getvalue()

    out_dir = Path(settings.upload_dir) / str(user.id) / "images" / str(page.source_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / f"crop_{uuid.uuid4().hex}.jpg"
    file_path.write_bytes(payload)

    current = db.scalar(select(func.max(ImageItem.order_index)).where(ImageItem.source_id == page.source_id))
    next_order = 0 if current is None else current + 1

    item = ImageItem(
        source_id=page.source_id,
        user_id=user.id,
        order_index=next_order,
        location_type="page",
        location_number=page.page_number,
        file_path=str(file_path),
        width=cropped.size[0],
        height=cropped.size[1],
        content_hash=hashlib.sha1(payload).hexdigest(),
        label=data.label.strip(),
        accepted_json=json.dumps(clean_answers(data.accepted_answers, data.label)),
        note=data.note.strip(),
        status="verified",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def draw_number(draw: ImageDraw.ImageDraw, box, text: str) -> None:
    height = max(14, box[3] - box[1])
    try:
        font = ImageFont.load_default(size=int(height * 0.7))
    except TypeError:
        font = ImageFont.load_default()
    center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    try:
        draw.text(center, text, fill=(255, 255, 255), font=font, anchor="mm")
    except ValueError:
        draw.text((box[0] + 3, box[1] + 2), text, fill=(255, 255, 255), font=font)


@router.get("/{page_id}/practice")
def practice_image(
    page_id: int,
    mode: Literal["single", "all"] = "single",
    region_id: int | None = None,
    include: Literal["usable", "all"] = "usable",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    page = own_page(db, page_id, user)

    if mode == "single":
        if region_id is None:
            raise HTTPException(400, "Choose which label to hide")
        region = own_region(db, region_id, user)
        if region.page_id != page.id:
            raise HTTPException(404, "Label box not found")
        regions = [region]
    else:
        statuses = ["verified", "auto"] if include == "usable" else ["verified", "auto", "proposed"]
        regions = db.scalars(
            select(LabelRegion)
            .where(LabelRegion.page_id == page.id, LabelRegion.status.in_(statuses))
            .order_by(LabelRegion.y0, LabelRegion.x0)
        ).all()
        if not regions:
            raise HTTPException(400, "No usable labels on this page yet")


    img = Image.open(page.file_path).convert("RGB")
    width, height = img.size
    draw = ImageDraw.Draw(img)
    for number, region in enumerate(regions, start=1):
        box = (int(region.x0 * width), int(region.y0 * height), int(region.x1 * width), int(region.y1 * height))
        draw.rectangle(box, fill=(70, 70, 70), outline=(255, 255, 255), width=2)
        if mode == "all":
            draw_number(draw, box, str(number))

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=90)
    return Response(content=buffer.getvalue(), media_type="image/jpeg")

def get_or_create_audit(db: Session, region: LabelRegion, user: User, original_text: str) -> LabelAudit:
    audit = db.scalar(select(LabelAudit).where(LabelAudit.region_id == region.id))
    if audit is None:
        audit = LabelAudit(
            user_id=user.id, region_id=region.id, ocr_text=original_text, confidence=region.confidence
        )
        db.add(audit)
    return audit



@region_router.patch("/{region_id}", response_model=RegionOut)
def update_region(
    region_id: int,
    data: RegionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    region = own_region(db, region_id, user)
    audit = get_or_create_audit(db, region, user, region.text) if region.origin == "ocr" else None

    if data.text is not None:
        region.text = data.text.strip()
    if data.accepted_answers is not None:
        region.accepted_json = json.dumps(clean_answers(data.accepted_answers, region.text))
    if data.status is not None:
        if data.status == "verified" and not region.text:
            raise HTTPException(400, "Add the label text before verifying")
        region.status = data.status

    if audit is not None:
        audit.final_text = region.text
        if region.status == "rejected":
            audit.decision = "rejected"
        elif region.status == "verified":
            same = normalize(region.text) == normalize(audit.ocr_text)
            audit.decision = "kept" if same else "edited"

    db.commit()
    db.refresh(region)
    return region



@region_router.delete("/{region_id}")
def delete_region(region_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    region = own_region(db, region_id, user)
    db.delete(region)
    db.commit()
    return {"deleted": region_id}

@router.post("/{page_id}/ocr")
def ocr_one_page(page_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    page = own_page(db, page_id, user)
    try:
        created = ocr_page_regions(db, page)
    except OcrUnavailable as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return {"page_id": page.id, "labels_found": created}

@router.get("/stats/labels")
def label_stats(
    source_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = (
        select(LabelRegion.origin, LabelRegion.status, func.count(), func.avg(LabelRegion.confidence))
        .join(PageRender, PageRender.id == LabelRegion.page_id)
        .where(LabelRegion.user_id == user.id)
    )
    if source_id is not None:
        query = query.where(PageRender.source_id == source_id)
    rows = db.execute(query.group_by(LabelRegion.origin, LabelRegion.status)).all()
    return [
        {"origin": origin, "status": status, "count": count, "avg_confidence": round(avg or 0, 1)}
        for origin, status, count, avg in rows
    ]


@router.post("/{page_id}/approve-auto")
def approve_auto(page_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Verify every remaining blue box on a page. Reject or fix mistakes first."""
    page = own_page(db, page_id, user)
    regions = db.scalars(
        select(LabelRegion).where(LabelRegion.page_id == page.id, LabelRegion.status == "auto")
    ).all()
    
    approved = 0
    for region in regions:
        if not region.text.strip():
            continue
        region.status = "verified"
        approved += 1
        
    db.commit()
    return {"page_id": page.id, "approved": approved}