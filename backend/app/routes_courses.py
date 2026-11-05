from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .deps import get_current_user
from .models import Course, User
from .schemas import CourseIn, CourseOut

router = APIRouter(prefix="/courses", tags=["courses"])

PROFILES = {"strict_facts", "balanced", "structure_friendly"}


@router.post("", response_model=CourseOut)
def create_course(data: CourseIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    profile = data.marking_profile if data.marking_profile in PROFILES else "balanced"
    course = Course(user_id=user.id, name=data.name.strip(), marking_profile=profile)
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@router.get("", response_model=list[CourseOut])
def list_courses(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(select(Course).where(Course.user_id == user.id)).all()