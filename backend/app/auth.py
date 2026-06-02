"""Password hashing, JWT issuing, and current-user / role dependencies."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import settings
from .db import get_session
from .models import User

pwd = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def hash_password(raw: str) -> str:
    return pwd.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return pwd.verify(raw, hashed)


def create_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def current_user(
    token: str | None = Depends(oauth2),
    db: Session = Depends(get_session),
) -> User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise cred_exc
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise cred_exc
    user = db.get(User, user_id)
    if user is None:
        raise cred_exc
    return user


def require_role(*roles: str):
    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles and user.role != "admin":
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return checker
