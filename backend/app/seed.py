"""Seed the SQLite schema + demo user rows (idempotent). Run: python -m app.seed

Sign-in is ORCID-only, so these rows carry no password — they exist so local
dev and the test suite have deterministic users to reference by role/email.
Real users are created automatically on first ORCID sign-in (see api/auth.py)."""

from __future__ import annotations

from sqlalchemy import select

from .db import SessionLocal, init_db
from .models import User

# (email, display_name, role, is_identifier) — no passwords; ORCID-only auth.
# The curator holds the identifier flag and the reviewer does not, so dev and
# the tests have one of each side of it.
DEMO_USERS = [
    ("curator@tbia.test", "Ada Curator", "contributor", True),
    ("reviewer@tbia.test", "Rex Reviewer", "reviewer", False),
    ("admin@tbia.test", "Ola Admin", "admin", False),
]


def seed() -> None:
    init_db()
    with SessionLocal() as db:
        for email, name, role, ident in DEMO_USERS:
            exists = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if exists:
                exists.is_identifier = ident  # demo rows only; real users are an admin's call
                continue
            db.add(User(email=email, display_name=name, role=role, is_identifier=ident))
        db.commit()
    print("Seeded demo user rows (ORCID-only auth — no passwords):")
    for email, _, role, ident in DEMO_USERS:
        print(f"  {email:22} ({role}{', identifier' if ident else ''})")


if __name__ == "__main__":
    seed()
