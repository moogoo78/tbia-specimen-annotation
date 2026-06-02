"""Read-only DuckDB access for the occurrence store.

A single read-only connection is opened at startup; each query uses an
independent ``cursor()`` (safe across threads) and runs in the threadpool so it
never blocks the event loop. The SQLite annotation DB is ATTACHed read-only so
dashboard/export queries can join occurrences against annotations in one pass.
"""

from __future__ import annotations

import os
from typing import Any

import duckdb
from fastapi.concurrency import run_in_threadpool

from .config import settings

_con: duckdb.DuckDBPyConnection | None = None
_attached = False


def connect() -> None:
    """Open the read-only DuckDB connection and attach the annotation DB."""
    global _con, _attached
    if not os.path.exists(settings.duckdb_path):
        raise RuntimeError(
            f"DuckDB not found at {settings.duckdb_path}. Run `make ingest` first."
        )
    _con = duckdb.connect(settings.duckdb_path, read_only=True)
    _con.execute(f"PRAGMA threads={settings.duck_threads}")
    if settings.duck_memory_limit:
        # With a cap set, DuckDB spills oversized aggregations to temp_directory
        # instead of OOM-killing the process — essential on small instances.
        _con.execute(f"PRAGMA memory_limit='{settings.duck_memory_limit}'")
    if settings.duck_temp_dir:
        _con.execute(f"PRAGMA temp_directory='{settings.duck_temp_dir}'")
    _attach_annotations()


def _attach_annotations() -> None:
    global _attached
    if _con is None or _attached:
        return
    if not os.path.exists(settings.sqlite_path):
        return  # annotations DB not created yet; search still works
    try:
        _con.execute("INSTALL sqlite")
        _con.execute("LOAD sqlite")
        _con.execute(
            f"ATTACH '{settings.sqlite_path}' AS ann (TYPE sqlite, READ_ONLY)"
        )
        _attached = True
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[duck] could not attach annotations sqlite: {exc}")


def close() -> None:
    global _con, _attached
    if _con is not None:
        _con.close()
        _con = None
        _attached = False


def _cursor() -> duckdb.DuckDBPyConnection:
    if _con is None:
        raise RuntimeError("DuckDB connection not initialised")
    return _con.cursor()


def _run(sql: str, params: list[Any] | None) -> list[dict[str, Any]]:
    cur = _cursor()
    cur.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


async def query(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    """Run a read query, returning a list of dict rows."""
    return await run_in_threadpool(_run, sql, params)


async def query_one(sql: str, params: list[Any] | None = None) -> dict[str, Any] | None:
    rows = await query(sql, params)
    return rows[0] if rows else None


def annotations_attached() -> bool:
    return _attached
