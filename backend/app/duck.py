"""Read-only DuckDB access for the occurrence store.

A single read-only connection is opened at startup; each query uses an
independent ``cursor()`` (safe across threads) and runs in the threadpool so it
never blocks the event loop. The SQLite annotation DB is ATTACHed read-only so
dashboard/export queries can join occurrences against annotations in one pass.

**Concurrency is capped here, not upstream.** Reads are public and
unauthenticated, and a facet or species rollup is a grouped scan over ~2M rows,
so the load that matters is not requests-per-second from one client but how many
scans run *at once* — a figure per-IP rate limiting cannot bound, because the
requests arrive from many IPs (a crawler working through the sitemap is the
benign version of exactly that shape). Left alone, ``run_in_threadpool`` would
admit anyio's default 40, each at ``PRAGMA threads`` of its own, all spilling
into ``temp_directory``: on a 2-vCPU box that is slower for everyone than
serving a few and shedding the rest. So queries take a token from a capacity
limiter, wait a bounded time for one, and are interrupted if they overrun.

Both limits shed load by *failing*, which is the point: a fast 503 with
``Retry-After`` tells a crawler to back off and lets the queue drain, where an
unbounded wait converts a traffic spike into a dead box. The two exceptions are
plain ``RuntimeError`` subclasses so non-HTTP callers (``worker.py``,
``import_results.py``) see a normal error; ``main.py`` maps them to responses.
"""

from __future__ import annotations

import asyncio
import os
import threading
import weakref
from typing import Any

import anyio
import duckdb
from anyio import to_thread

from .config import settings

_con: duckdb.DuckDBPyConnection | None = None
_attached = False


class DuckOverloaded(RuntimeError):
    """No query slot came free within ``duck_queue_timeout`` seconds."""


class DuckTimeout(RuntimeError):
    """The query itself ran past ``duck_query_timeout`` and was interrupted."""


# One limiter per event loop. anyio binds a CapacityLimiter to the loop that
# created it, and the test suite may run more than one loop over the life of the
# process, so this cannot simply be a module-level constant. The dictionary is
# weak-keyed, so a finished loop's limiter is collected with it.
_limiters: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, anyio.CapacityLimiter]" = (
    weakref.WeakKeyDictionary()
)


def _limiter() -> anyio.CapacityLimiter:
    loop = asyncio.get_running_loop()
    lim = _limiters.get(loop)
    # total_tokens is re-checked so a settings change (tests, a reload) takes
    # effect rather than being pinned by whichever loop got here first.
    if lim is None or lim.total_tokens != settings.duck_max_concurrency:
        lim = anyio.CapacityLimiter(settings.duck_max_concurrency)
        _limiters[loop] = lim
    return lim


def connect() -> None:
    """Open the read-only DuckDB connection and attach the annotation DB."""
    global _con, _attached
    if not os.path.exists(settings.duckdb_path):
        raise RuntimeError(
            f"DuckDB not found at {settings.duckdb_path}. Run `make prepare` first."
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
    # DuckDB has no statement_timeout, but a query can be cancelled from another
    # thread via interrupt(), which makes execute() raise. The timer targets this
    # cursor alone (cursors are independent connections), so a slow query is shot
    # without touching the ones running beside it.
    timeout = settings.duck_query_timeout
    timer = threading.Timer(timeout, cur.interrupt) if timeout > 0 else None
    if timer is not None:
        timer.start()
    try:
        cur.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    except duckdb.InterruptException as exc:
        raise DuckTimeout(f"query exceeded {timeout}s and was cancelled") from exc
    finally:
        if timer is not None:
            timer.cancel()
        cur.close()


async def query(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    """Run a read query, returning a list of dict rows."""
    limiter = _limiter()
    try:
        with anyio.fail_after(settings.duck_queue_timeout):
            await limiter.acquire()
    except TimeoutError as exc:
        raise DuckOverloaded(
            f"all {settings.duck_max_concurrency} query slots busy for "
            f"{settings.duck_queue_timeout}s"
        ) from exc
    try:
        # The token is already held, so run_sync gets no limiter of its own —
        # passing one here would take a second token from the same limiter and
        # deadlock. anyio's default thread limiter still bounds the pool overall.
        return await to_thread.run_sync(_run, sql, params)
    finally:
        limiter.release()


async def query_one(sql: str, params: list[Any] | None = None) -> dict[str, Any] | None:
    rows = await query(sql, params)
    return rows[0] if rows else None


def annotations_attached() -> bool:
    return _attached
