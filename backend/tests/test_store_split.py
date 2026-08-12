"""Moving the seeded tables out of a pre-split annotations.sqlite.

Deployments created before the split hold all seven tables in one file, and the
move happens once, at startup. It runs in a subprocess here because the engines
in `app.db` bind to the settings at import time — this is also exactly what a
deploy does, so the test exercises the real path rather than a re-wired copy.
"""

import os
import sqlite3
import subprocess
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models  # noqa: F401  (registers the mappers on both metadatas)
from app.db import Base, RefBase

REF_TABLES = ("collectors", "collector_alias", "sampling_event", "sampling_event_actor")


def _pre_split_db(path: str) -> None:
    """The old layout: every table in one file, schema straight from the models
    so the column order the copy relies on is the real one."""
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    RefBase.metadata.create_all(engine)

    # Rows go in through the ORM so the Python-side defaults apply — the point
    # of the fixture is a *realistic* old file, not hand-written SQL.
    with Session(engine) as db:
        db.add(models.User(id=1, display_name="Curator", role="contributor"))
        db.add(models.Annotation(
            id=1, occurrence_id="r1", field="locality", proposed_value="野柳",
            contributor_id=1,
        ))
        db.add(models.Collector(id=1, name="呂碧鳳", name_en="Lu", n_records=3))
        db.add(models.CollectorAlias(recorded_by="呂碧鳳", collector_id=1, source="curator"))
        db.add(models.SamplingEvent(
            id=1, seq=1, event_date="1901", verbatim_event_date="1901",
            year_start=1901, year_end=1901, narrative="採集於淡水。",
        ))
        db.add(models.SamplingEventActor(id=1, event_id=1, recorded_by="呂碧鳳", position=0))
        db.commit()
    engine.dispose()


def _init_db(ann: str, ref: str):
    env = {
        **os.environ,
        "NDB_SQLITE_PATH": ann,
        "NDB_REFERENCE_PATH": ref,
        "NDB_JWT_SECRET": "test-secret",
    }
    return subprocess.run(
        [sys.executable, "-c", "from app.db import init_db; init_db()"],
        env=env, capture_output=True, text=True, check=True,
    )


def _tables(path: str) -> set[str]:
    db = sqlite3.connect(path)
    try:
        return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        db.close()


def _count(path: str, table: str) -> int:
    db = sqlite3.connect(path)
    try:
        return db.execute(f"SELECT count(*) FROM '{table}'").fetchone()[0]
    finally:
        db.close()


def test_migration_moves_seeded_tables_and_leaves_user_work_alone(tmp_path):
    ann, ref = str(tmp_path / "annotations.sqlite"), str(tmp_path / "reference.sqlite")
    _pre_split_db(ann)

    out = _init_db(ann, ref)
    assert "moved to reference store" in out.stdout

    # Seeded rows are in the new file, with their curator-set values intact —
    # a rebuild-from-scratch instead of a copy would have reset source to 'auto'.
    for table in REF_TABLES:
        assert _count(ref, table) == 1, table
    assert sqlite3.connect(ref).execute(
        "SELECT source FROM collector_alias"
    ).fetchone()[0] == "curator"

    # ...and gone from the old file, which keeps every row of user work.
    assert _tables(ann).isdisjoint(REF_TABLES)
    assert _count(ann, "users") == 1
    assert _count(ann, "annotations") == 1


def test_migration_is_idempotent(tmp_path):
    ann, ref = str(tmp_path / "annotations.sqlite"), str(tmp_path / "reference.sqlite")
    _pre_split_db(ann)

    _init_db(ann, ref)
    second = _init_db(ann, ref)

    assert "moved to reference store" not in second.stdout  # nothing left to move
    for table in REF_TABLES:
        assert _count(ref, table) == 1, table


def test_fresh_install_just_creates_both_stores(tmp_path):
    ann, ref = str(tmp_path / "annotations.sqlite"), str(tmp_path / "reference.sqlite")

    _init_db(ann, ref)

    assert {"users", "annotations", "transcribe_requests"} <= _tables(ann)
    assert set(REF_TABLES) <= _tables(ref)
    assert _tables(ann).isdisjoint(REF_TABLES)
