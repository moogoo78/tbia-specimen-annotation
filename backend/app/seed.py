"""Seed demo users (idempotent). Run: python -m app.seed"""

from __future__ import annotations

from sqlalchemy import select

from .auth import hash_password
from .db import SessionLocal, init_db
from .models import User

DEMO_USERS = [
    ("curator@tbia.test", "Ada Curator", "contributor", "demo1234"),
    ("reviewer@tbia.test", "Rex Reviewer", "reviewer", "demo1234"),
    ("admin@tbia.test", "Ola Admin", "admin", "demo1234"),
]


def seed() -> None:
    init_db()
    with SessionLocal() as db:
        for email, name, role, pw in DEMO_USERS:
            exists = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if exists:
                continue
            db.add(User(email=email, display_name=name, role=role, pw_hash=hash_password(pw)))
        db.commit()
    print("Seeded demo users:")
    for email, _, role, pw in DEMO_USERS:
        print(f"  {email:22} ({role:11}) password: {pw}")


if __name__ == "__main__":
    seed()
