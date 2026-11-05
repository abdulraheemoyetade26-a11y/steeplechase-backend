import re
from .models import naive_now

PLAN_ORDER = {"free": 0, "basic": 1, "pro": 2}

PLAN_LIMITS = {
    "free": {"pages_per_month": 30, "max_decks": 2, "max_file_mb": 25},
    "basic": {"pages_per_month": 300, "max_decks": 10, "max_file_mb": 50},
    "pro": {"pages_per_month": 1000, "max_decks": 100, "max_file_mb": 100},
}

def effective_plan(user) -> str:
    if user.plan in ("basic", "pro"):
        if user.plan_expires_at is None or user.plan_expires_at > naive_now():
            return user.plan
    return "free"

def roll_usage_month(user, db) -> None:
    month = naive_now().strftime("%Y-%m")
    if user.usage_month != month:
        user.usage_month = month
        user.pages_processed_this_month = 0
        db.commit()

def pages_remaining(user, db) -> int:
    roll_usage_month(user, db)
    limit = PLAN_LIMITS[effective_plan(user)]["pages_per_month"]
    return max(0, limit - user.pages_processed_this_month)

def plan_summary(user, db) -> dict:
    roll_usage_month(user, db)
    plan = effective_plan(user)
    limits = PLAN_LIMITS[plan]
    return {
        "plan": plan,
        "expires_at": user.plan_expires_at.isoformat() if user.plan_expires_at else None,
        "pages_used": user.pages_processed_this_month,
        "pages_limit": limits["pages_per_month"],
        "max_decks": limits["max_decks"],
        "max_file_mb": limits["max_file_mb"],
    }

def normalise_phone(raw: str) -> str:
    digits = re.sub(r"[^\d+]", "", raw or "")
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if digits.startswith("0") and len(digits) == 11:
        digits = "+234" + digits[1:]
    elif digits.startswith("234") and len(digits) == 13:
        digits = "+" + digits
    if not re.fullmatch(r"\+[1-9]\d{7,14}", digits):
        raise ValueError("Enter a valid phone number, for example 08012345678 or +2348012345678")
    return digits
def apply_plan(db, user, plan: str, days: int):
    now = naive_now()
    current_plan = effective_plan(user)
    
    if current_plan == plan and user.plan_expires_at and user.plan_expires_at > now:
        user.plan_expires_at = user.plan_expires_at + timedelta(days=days)
    else:
        user.plan = plan
        user.plan_expires_at = now + timedelta(days=days)
    
    if plan == "free":
        user.plan_expires_at = None
        
    db.commit()
