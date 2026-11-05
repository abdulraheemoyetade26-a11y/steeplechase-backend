from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .schemas import RegisterIn, TokenOut
from .security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    if "@" not in email:
        raise HTTPException(400, "Enter a valid email address")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(400, "This email is already registered")
    user = User(email=email, password_hash=hash_password(data.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    email = form.username.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    return TokenOut(access_token=create_access_token(user.id))