from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth
from ..db import get_session
from ..models import User
from ..schemas import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_session)):
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if user is None or not auth.verify_password(body.password, user.pw_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenResponse(access_token=auth.create_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(auth.current_user)):
    return UserOut.model_validate(user)
