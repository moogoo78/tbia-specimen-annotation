"""SQLAlchemy setup for the two SQLite stores.

They are split by what it costs to lose them:

- **annotations** (``engine`` / ``Base`` / ``SessionLocal``) — users,
  annotations, transcribe requests. Nothing can regenerate these; this is the
  file to back up.
- **reference** (``ref_engine`` / ``RefBase`` / ``RefSessionLocal``) — collectors
  + aliases, and the sampling-event chronology. Both are rebuilt by their
  seeders, so the file is disposable, and a re-seed cannot reach user work
  because it is writing a different file.

No foreign key crosses the two, which is what makes the split safe: annotations
and transcribe requests point at ``users`` (same file), aliases and event actors
point at ``collectors`` (same file).
"""

from __future__ import annotations

import os
import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

engine = create_engine(
    settings.sqlite_url,
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

ref_engine = create_engine(
    settings.reference_url,
    connect_args={"check_same_thread": False},
    future=True,
)
RefSessionLocal = sessionmaker(bind=ref_engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Tables in the annotation store (the irreplaceable half)."""


class RefBase(DeclarativeBase):
    """Tables in the reference store (the seeded, rebuildable half)."""


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


# Columns appended to a table since the first deployments, as
# ``table -> [(column, DDL)]``. SQLite backfills existing rows from the DDL's
# DEFAULT, so each entry has to name a default that is *right* for rows written
# before the column existed — for ``annotations.license`` that is the platform
# default, the narrowest of the three grants, which is the conservative reading
# of work contributed when the form asked for no terms at all.
ADDED_COLUMNS = {
    "users": [
        ("show_in_ranking", "BOOLEAN DEFAULT 0"),
        ("default_license", "VARCHAR(32) DEFAULT 'CC-BY-NC-4.0'"),
    ],
    "annotations": [("license", "VARCHAR(32) DEFAULT 'CC-BY-NC-4.0'")],
}


def _add_columns() -> None:
    """Add columns appended to a table since a DB was first created.

    ``create_all`` only creates *missing tables*, so a column added to the model
    never reaches an existing ``annotations.sqlite``. Unlike ``_migrate_users()``
    — which had to rebuild the table because SQLite cannot ALTER a NOT NULL
    constraint away — appending a column with a default is a plain
    ``ADD COLUMN``. Idempotent: each column is added only if absent.
    """
    with engine.begin() as conn:
        for table, added in ADDED_COLUMNS.items():
            info = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            if not info:
                continue  # fresh install — create_all builds the current schema
            have = {row[1] for row in info}
            for name, ddl in added:
                if name not in have:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


REFERENCE_TABLES = (
    "collectors", "collector_alias", "sampling_event", "sampling_event_actor",
)


def _move_reference_tables() -> None:
    """Move the seeded tables out of a pre-split ``annotations.sqlite``.

    They used to live beside users and annotations; they now have their own file,
    so a DB created before the split still holds them in the wrong place. Same
    in-place style as ``_migrate_users()`` above — the deploy is a restart, with
    no step anyone can forget on the box.

    Copy first, verify the counts, and only then drop: a half-finished move that
    lost rows would be a silent data loss, and the seeders would happily "fix" it
    by rebuilding from scratch. Idempotent and a no-op on a fresh install (there
    is nothing to move) and after the first run (the tables are gone).
    """
    if not os.path.exists(settings.sqlite_path):
        return  # fresh install: create_all builds each table in its own file

    with engine.connect() as conn:
        present = [
            t for t in REFERENCE_TABLES
            if conn.exec_driver_sql(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)
            ).fetchone()
        ]
        counts = {
            t: conn.exec_driver_sql(f"SELECT count(*) FROM '{t}'").fetchone()[0]
            for t in present
        }
    if not present:
        return

    # Build the target schema first, then hand the file over: ATTACH/DETACH and
    # a pooled SQLAlchemy connection cannot both hold reference.sqlite, and the
    # move is the one that needs it.
    from . import models  # noqa: F401  (register mappers)

    os.makedirs(os.path.dirname(settings.reference_path) or ".", exist_ok=True)
    RefBase.metadata.create_all(ref_engine)
    ref_engine.dispose()

    # Raw sqlite3 rather than the ORM: ATTACH and DETACH must sit outside any
    # transaction, which is exactly what SQLAlchemy's connection handling is
    # otherwise busy managing for us.
    con = sqlite3.connect(settings.sqlite_path)
    try:
        con.execute("ATTACH DATABASE ? AS refdb", (settings.reference_path,))
        con.execute("BEGIN")
        for table in present:
            # An interrupted earlier attempt could have left rows behind; the
            # source file stays authoritative until the drop below, so clearing
            # the target first is safe and makes a retry converge.
            con.execute(f"DELETE FROM refdb.'{table}'")
            con.execute(f"INSERT INTO refdb.'{table}' SELECT * FROM '{table}'")
            moved = con.execute(f"SELECT count(*) FROM refdb.'{table}'").fetchone()[0]
            if moved != counts[table]:
                raise RuntimeError(
                    f"reference split: {table} copied {moved} of {counts[table]} rows"
                )
        con.commit()

        # Only now, with every row verified in the new file, is dropping safe.
        con.execute("BEGIN")
        for table in present:
            con.execute(f"DROP TABLE '{table}'")
        con.commit()
        con.execute("DETACH DATABASE refdb")
        con.execute("VACUUM")  # return the ~2.5 MB those tables held
    finally:
        con.close()

    print(
        "[db] moved to reference store: "
        + ", ".join(f"{t} ({counts[t]})" for t in present)
    )


def init_db() -> None:
    """Create tables if they do not exist (MVP migration strategy)."""
    from . import models  # noqa: F401  (register mappers)

    _migrate_users()
    _add_columns()
    _move_reference_tables()
    Base.metadata.create_all(engine)
    RefBase.metadata.create_all(ref_engine)


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_ref_session():
    db = RefSessionLocal()
    try:
        yield db
    finally:
        db.close()
