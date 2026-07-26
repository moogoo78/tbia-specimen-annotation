"""Batch transcription worker. Drains pending transcribe_requests once and
exits — run it from cron (or `make transcribe`) at whatever cadence you want.

    python -m app.worker            # process up to TRANSCRIBE_BATCH pending
    python -m app.worker --limit 5  # process at most 5

Requires ANTHROPIC_API_KEY in the environment; the DuckDB occurrence store and
the SQLite annotation DB must already exist (make ingest / make seed)."""

from __future__ import annotations

import argparse
import asyncio
import logging

from . import duck
from .db import SessionLocal, init_db
from .pipeline import process_pending


async def _run(limit: int | None) -> None:
    init_db()      # ensure annotation tables exist
    duck.connect()  # read-only occurrence store (for record images + fields)
    try:
        with SessionLocal() as db:
            summary = await process_pending(db, limit)
    finally:
        duck.close()
    logging.getLogger("worker").info(
        "transcribed: %(done)s done, %(failed)s failed, %(annotations)s annotations "
        "(%(requests)s pending picked up)", summary,
    )
    print(summary)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Drain pending AI transcription requests.")
    ap.add_argument("--limit", type=int, default=None, help="max requests this run")
    args = ap.parse_args()
    asyncio.run(_run(args.limit))


if __name__ == "__main__":
    main()
