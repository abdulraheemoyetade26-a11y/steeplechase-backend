import io
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .deps import get_current_user
from .models import LabelFlag, LabelRegion, PageRender, User
from .ocr import MIN_CONF_AUTO
from .routes_pages import own_region

router = APIRouter(prefix="/label-review", tags=["label-review"])

CROP_MIN_WIDTH = 360
CROP_MAX_SCALE = 4.0

class DecisionIn(BaseModel):
    decision: Literal["correct", "fix", "reject"]
    text: str | None = Field(default=None, max_length=300)

@router.get("/queue")
def review_queue(
    source_id: int | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    limit = max(1, min(limit, 50))
    query = (
        select(LabelRegion, PageRender)
        .join(PageRender, PageRender.id == LabelRegion.page_id)
        .where(PageRender.user_id == user.id, LabelRegion.status.in_(["auto", "proposed"]))
    )
    if source_id is not None:
        query = query.where(PageRender.source_id == source_id)

    flagged = set(db.scalars(select(LabelFlag.region_id).where(LabelFlag.user_id == user.id)).all())
    pairs = [(r, p) for r, p in db.execute(query).all() if r.id not in flagged and r.status != "verified"]
    pairs.sort(key=lambda pair: -pair[0].confidence)
    
    return {
        "remaining": len(pairs),
        "items": [
            {
                "region_id": region.id,
                "text": region.text,
                "confidence": region.confidence,
                "source_id": page.source_id,
                "page_number": page.page_number,
            }
            for region, page in pairs[:limit]
        ],
    }

@router.get("/{region_id}/crop")
def label_crop(region_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    region = own_region(db, region_id, user)
    page = db.get(PageRender, region.page_id)
    if page is None:
        raise HTTPException(404, "The page for this label no longer exists")

    img = Image.open(page.file_path).convert("RGB")
    width, height = img.size
    box_w = (region.x1 - region.x0) * width
    box_h = (region.y1 - region.y0) * height
    pad_x = max(12, box_w * 0.25)
    pad_y = max(12, box_h * 0.6)
    crop_box = (
        max(0, int(region.x0 * width - pad_x)),
        max(0, int(region.y0 * height - pad_y)),
        min(width, int(region.x1 * width + pad_x)),
        min(height, int(region.y1 * height + pad_y)),
    )
    crop = img.crop(crop_box)
    scale = min(CROP_MAX_SCALE, max(1.0, CROP_MIN_WIDTH / crop.width))
    if scale > 1.0:
        crop = crop.resize((int(crop.width * scale), int(crop.height * scale)), Image.Resampling.LANCZOS)

    draw = ImageDraw.Draw(crop)
    outline = (
        (region.x0 * width - crop_box[0]) * scale,
        (region.y0 * height - crop_box[1]) * scale,
        (region.x1 * width - crop_box[0]) * scale,
        (region.y1 * height - crop_box[1]) * scale,
    )
    draw.rectangle(outline, outline=(37, 99, 235), width=2)

    buffer = io.BytesIO()
    crop.save(buffer, format="JPEG", quality=90)
    return Response(content=buffer.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

@router.post("/{region_id}/decision")
def decide(
    region_id: int,
    data: DecisionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    region = own_region(db, region_id, user)

    if data.decision == "reject":
        region.status = "rejected"
    else:
        text = (data.text if data.decision == "fix" and data.text is not None else region.text).strip()
        if not text:
            raise HTTPException(400, "Label text cannot be empty")
        region.text = text
        region.status = "verified"

    db.commit()
    return {"region_id": region.id, "status": region.status}

@router.post("/{region_id}/undo")
def undo(region_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    region = own_region(db, region_id, user)
    # Revert status based on confidence
    region.status = "auto" if region.confidence >= MIN_CONF_AUTO else "proposed"
    db.commit()
    return {"region_id": region.id, "status": region.status}