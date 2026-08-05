"""SQLAlchemy setup for the SQLite annotation/user store."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

engine = create_engine(
    settings.sqlite_url,
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _migrate_users() -> None:
    """Bring a pre-ORCID ``users`` table up to the current schema in place.

    The MVP has no Alembic; ``create_all`` only creates *missing* tables, so an
    existing SQLite file keeps its old ``users`` definition (NOT NULL email /
    pw_hash, no ``orcid`` column). ORCID sign-in needs ``orcid`` and nullable
    email/pw_hash, which SQLite can't add via ``ALTER``, so we rebuild just that
    one table — preserving every row (ids intact, so annotation FKs still resolve)
    and leaving collectors/annotations untouched. No-op on a fresh DB or once the
    ``orcid`` column already exists.
    """
    with engine.begin() as conn:
        info = conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()
        if not info or any(row[1] == "orcid" for row in info):
            return  # fresh install (create_all builds it) or already migrated
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.exec_driver_sql("ALTER TABLE users RENAME TO users_old")
        conn.exec_driver_sql(
            """CREATE TABLE users (
                id INTEGER NOT NULL PRIMARY KEY,
                orcid VARCHAR(32),
                email VARCHAR(255),
                display_name VARCHAR(255) NOT NULL,
                role VARCHAR(20),
                pw_hash VARCHAR(255),
                created DATETIME
            )"""
        )
        conn.exec_driver_sql(
            "INSERT INTO users (id, email, display_name, role, pw_hash, created) "
            "SELECT id, email, display_name, role, pw_hash, created FROM users_old"
        )
        conn.exec_driver_sql("DROP TABLE users_old")
        conn.exec_driver_sql("CREATE UNIQUE INDEX ix_users_orcid ON users (orcid)")
        conn.exec_driver_sql("CREATE UNIQUE INDEX ix_users_email ON users (email)")


def _add_user_columns() -> None:
    """Add columns appended to ``users`` since a DB was first created.

    ``create_all`` only creates *missing tables*, so a column added to the model
    never reaches an existing ``annotations.sqlite``. Unlike ``_migrate_users()``
    — which had to rebuild the table because SQLite cannot ALTER a NOT NULL
    constraint away — appending a nullable column with a default is a plain
    ``ADD COLUMN``. Idempotent: each column is added only if absent.
    """
    added = [("show_in_ranking", "BOOLEAN DEFAULT 0")]
    with engine.begin() as conn:
        info = conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()
        if not info:
            return  # fresh install — create_all builds the current schema
        have = {row[1] for row in info}
        for name, ddl in added:
            if name not in have:
                conn.exec_driver_sql(f"ALTER TABLE users ADD COLUMN {name} {ddl}")


def init_db() -> None:
    """Create tables if they do not exist (MVP migration strategy)."""
    from . import models  # noqa: F401  (register mappers)

    _migrate_users()
    _add_user_columns()
    Base.metadata.create_all(engine)


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
