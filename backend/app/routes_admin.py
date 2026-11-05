import random
import string
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from datetime import timedelta

from .database import get_db
from .deps import require_admin
from .models import User, ActivationCode, LabelFlag, LabelRegion, naive_now
from .plans import effective_plan, apply_plan # We will add apply_plan to plans.py next

router = APIRouter(prefix="/admin", tags=["admin"])

class PlanUpdate(BaseModel):
    plan: str
    days: int

@router.get("/users")
def list_users(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    users = db.scalars(select(User).order_by(User.id.desc())).all()
    return [
        {
            "id": u.id, "email": u.email, "phone": u.phone, 
            "plan": effective_plan(u), 
            "pages_used": u.pages_processed_this_month,
            "created_at": u.created_at.isoformat() if u.created_at else None
        } for u in users
    ]

@router.post("/users/{user_id}/plan")
def set_plan(user_id: int, data: PlanUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    apply_plan(db, user, data.plan, data.days)
    return {"status": "success", "new_plan": user.plan}

@router.post("/codes/generate")
def generate_codes(plan: str, days: int, count: int, batch: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    codes = []
    for _ in range(count):
        part1 = "".join(random.choice(chars) for _ in range(4))
        part2 = "".join(random.choice(chars) for _ in range(4))
        code = f"STP-{part1}-{part2}"
        db.add(ActivationCode(code=code, plan=plan, days=days, batch=batch))
        codes.append(code)
    db.commit()
    return {"generated": codes}

@router.get("/flags")
def list_flags(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    flags = db.scalars(select(LabelFlag).where(LabelFlag.status == "pending")).all()
    result = []
    for f in flags:
        region = db.get(LabelRegion, f.region_id)
        user = db.get(User, f.user_id)
        result.append({
            "id": f.id, "user_email": user.email, 
            "region_text": region.text if region else "deleted",
            "confidence": region.confidence if region else 0,
            "status": f.status
        })
    return result

@router.post("/flags/{flag_id}/resolve")
def resolve_flag(flag_id: int, decision: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    flag = db.get(LabelFlag, flag_id)
    if not flag:
        raise HTTPException(404, "Flag not found")
    flag.status = "accepted" if decision == "accept" else "dismissed"
    flag.resolved_at = naive_now()
    flag.resolved_by = admin.id
    
    if decision == "accept":
        region = db.get(LabelRegion, flag.region_id)
        if region:
            region.status = "rejected" # Remove from practice
            
    db.commit()
    return {"status": "success"}