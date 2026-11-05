import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .deps import get_current_user
from .models import ImageItem, User
from .schemas import ImageOut, ImageUpdate

router = APIRouter(prefix="/images", tags=["images"])


def get_own_image(db: Session, image_id: int, user: User) -> ImageItem:
    item = db.get(ImageItem, image_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(404, "Image not found")
    return item


@router.get("", response_model=list[ImageOut])
def list_images(
    source_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(ImageItem).where(ImageItem.user_id == user.id)
    if source_id is not None:
        query = query.where(ImageItem.source_id == source_id)
    if status is not None:
        query = query.where(ImageItem.status == status)
    return db.scalars(query.order_by(ImageItem.source_id, ImageItem.order_index)).all()


@router.get("/{image_id}/file")
def image_file(image_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = get_own_image(db, image_id, user)
    return FileResponse(item.file_path)


@router.patch("/{image_id}", response_model=ImageOut)
def update_image(
    image_id: int,
    data: ImageUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = get_own_image(db, image_id, user)

    if data.label is not None:
        item.label = data.label.strip()

    if data.accepted_answers is not None:
        seen, cleaned = set(), []
        for answer in data.accepted_answers:
            answer = answer.strip()
            key = answer.lower()
            if answer and key not in seen and key != item.label.lower():
                seen.add(key)
                cleaned.append(answer)
        item.accepted_json = json.dumps(cleaned)

    if data.note is not None:
        item.note = data.note.strip()

    if data.status is not None:
        if data.status == "verified" and not item.label:
            raise HTTPException(400, "Add the correct label before verifying")
        item.status = data.status

    db.commit()
    db.refresh(item)
    return item