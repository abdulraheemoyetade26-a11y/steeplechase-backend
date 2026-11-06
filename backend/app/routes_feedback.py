from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .database import get_db
from .deps import get_current_user
from .models import Feedback, User

router = APIRouter(prefix="/feedback", tags=["feedback"])

class FeedbackIn(BaseModel):
    message: str
    page: str
    user_agent: str

@router.post("")
def submit_feedback(data: FeedbackIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    fb = Feedback(
        user_id=user.id,
        message=data.message[:1000],
        page=data.page[:300],
        user_agent=data.user_agent[:300]
    )
    db.add(fb)
    db.commit()
    return {"status": "ok"}