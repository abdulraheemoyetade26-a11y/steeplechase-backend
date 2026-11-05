from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .deps import get_current_user
from .models import ActivationCode, User, naive_now
from .plans import effective_plan, plan_summary, PLAN_ORDER

router = APIRouter(prefix="/plan", tags=["plan"])

class RedeemIn(BaseModel):
    code: str

@router.get("/me")
def get_my_plan(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return plan_summary(user, db)

@router.post("/redeem")
def redeem_code(data: RedeemIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    clean_code = data.code.strip().upper()
    
    code = db.scalar(select(ActivationCode).where(ActivationCode.code == clean_code))
    if code is None or code.used_by is not None:
        raise HTTPException(400, "Invalid or already used code.")
        
    current_plan = effective_plan(user)
    if PLAN_ORDER.get(code.plan, 0) < PLAN_ORDER.get(current_plan, 0):
        raise HTTPException(400, "You already have a higher plan.")
        
    now = naive_now()
    if current_plan == code.plan and user.plan_expires_at and user.plan_expires_at > now:
        user.plan_expires_at = user.plan_expires_at + timedelta(days=code.days)
    else:
        user.plan = code.plan
        user.plan_expires_at = now + timedelta(days=code.days)
        
    code.used_by = user.id
    code.used_at = now
    db.commit()
    
    return plan_summary(user, db)