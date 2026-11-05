import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .security import decode_token
from datetime import timedelta
from .models import naive_now

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    error = HTTPException(status_code=401, detail="Invalid or expired login")
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise error
    user = db.get(User, user_id)
    if user is None:
        raise error
        
    # Update last active (only if > 5 mins ago to save DB writes)
    now = naive_now()
    if user.last_active_at is None or (now - user.last_active_at) > timedelta(minutes=5):
        user.last_active_at = now
        db.commit()
        
    return user

def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user