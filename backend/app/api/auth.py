"""Authentication — ORCID-only sign-in.

Flow (Authorization Code):
  1. Frontend fetches ``GET /api/auth/orcid/config`` and redirects the browser to
     ORCID's authorize endpoint with a CSRF ``state`` it minted itself.
  2. ORCID redirects back to ``<frontend>/auth/orcid/callback?code=...&state=...``.
  3. Frontend POSTs the ``code`` to ``POST /api/auth/orcid/callback``; the backend
     exchanges it for the user's ORCID iD + name (the /authenticate token response
     carries both), upserts a local ``User``, and returns *our* JWT.

The ORCID client secret stays server-side; the browser never sees it.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth
from ..config import settings
from ..db import get_session
from ..models import User
from ..schemas import (
    DevLoginConfig,
    DevLoginRequest,
    DevUser,
    OrcidCallback,
    OrcidConfig,
    TokenResponse,
    UserOut,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/orcid/config", response_model=OrcidConfig)
def orcid_config():
    """Public parameters for building the ORCID authorize URL (no secret)."""
    if not settings.orcid_client_id:
        raise HTTPException(status_code=503, detail="ORCID sign-in is not configured")
    return OrcidConfig(
        authorize_endpoint=settings.orcid_authorize_endpoint,
        client_id=settings.orcid_client_id,
        redirect_uri=settings.orcid_redirect_uri,
        scope=settings.orcid_scope,
    )


@router.post("/orcid/callback", response_model=TokenResponse)
def orcid_callback(body: OrcidCallback, db: Session = Depends(get_session)):
    if not (settings.orcid_client_id and settings.orcid_client_secret):
        raise HTTPException(status_code=503, detail="ORCID sign-in is not configured")

    try:
        resp = httpx.post(
            settings.orcid_token_endpoint,
            data={
                "client_id": settings.orcid_client_id,
                "client_secret": settings.orcid_client_secret,
                "grant_type": "authorization_code",
                "code": body.code,
                "redirect_uri": settings.orcid_redirect_uri,
            },
            headers={"Accept": "application/json"},
            timeout=15.0,
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach ORCID")

    if resp.status_code != 200:
        # Bad/expired/replayed code, or redirect_uri mismatch.
        raise HTTPException(status_code=401, detail="ORCID authorization failed")

    data = resp.json()
    orcid_id = data.get("orcid")
    if not orcid_id:
        raise HTTPException(status_code=401, detail="ORCID did not return an iD")
    name = data.get("name") or orcid_id

    user = _upsert_orcid_user(db, orcid_id, name)
    return TokenResponse(access_token=auth.create_token(user), user=UserOut.model_validate(user))


def _upsert_orcid_user(db: Session, orcid_id: str, name: str) -> User:
    user = db.execute(select(User).where(User.orcid == orcid_id)).scalar_one_or_none()
    if user is None:
        role = "admin" if orcid_id in settings.orcid_admin_list else "contributor"
        user = User(orcid=orcid_id, display_name=name, role=role)
        db.add(user)
    elif name and user.display_name != name:
        user.display_name = name  # keep the name fresh from ORCID
    db.commit()
    db.refresh(user)
    return user


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(auth.current_user)):
    return UserOut.model_validate(user)


# ── Dev-only sign-in ────────────────────────────────────────────────────────
# Lets local dev sign in as a seeded demo user without ORCID, which cannot
# round-trip on localhost. This is an authentication bypass — one of the demo
# users is an `admin` — so it takes BOTH NDB_DEV_LOGIN and NDB_DEV_MODE to
# enable (settings.dev_login_enabled); neither flag alone opens it.
@router.get("/dev-login/config", response_model=DevLoginConfig)
def dev_login_config(db: Session = Depends(get_session)):
    """Tell the frontend whether dev sign-in is available and list demo users."""
    if not settings.dev_login_enabled:
        return DevLoginConfig(enabled=False, users=[])
    # Only seeded demo users have an email (ORCID users are keyed on iD).
    rows = db.execute(select(User).where(User.email.isnot(None))).scalars().all()
    return DevLoginConfig(
        enabled=True,
        users=[DevUser(email=u.email, display_name=u.display_name, role=u.role) for u in rows],
    )


@router.post("/dev-login", response_model=TokenResponse)
def dev_login(body: DevLoginRequest, db: Session = Depends(get_session)):
    if not settings.dev_login_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    user = db.execute(
        select(User).where(User.email == body.email, User.email.isnot(None))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Unknown dev user")
    return TokenResponse(access_token=auth.create_token(user), user=UserOut.model_validate(user))
