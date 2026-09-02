"""Import transcription result JSON files into the annotation store.

The sibling of `app.worker`: same destination, different source. The worker calls
Claude and stores what comes back; this reads result JSON that was produced
elsewhere — an agent session, a contributor's own AI chat, a re-run of a batch —
and lands it through the same code path.

What it lands is a **proposal**, not a contribution: like the worker, it stores
the result on the `transcribe_request` that asked for it, and the person who
asked still decides field by field in the record's annotation form. Importing a
file therefore never writes an annotation in anyone's name.

    python -m app.import_results results/                 # dry run, whole directory
    python -m app.import_results results/ --commit        # actually write
    python -m app.import_results a.json b.json --commit   # specific files

Writing requires --commit; without it the run reports what it would do and rolls
back. Each file is matched to the newest *pending* `transcribe_request` for its
occurrence, which on success becomes `done` and on failure `failed` (with the
reason in `error`) — exactly as the worker marks them. Matching only pending
requests is also what makes re-running safe: an already-imported file finds no
pending row and is skipped rather than duplicated.

File format is the shape `extract.parse_pasted` accepts (the same JSON the
copy-paste flow takes), plus an optional top-level "occurrence_id":

    {
      "occurrence_id": "672827c48f4bdf00d795a9ea",
      "meta": {"service": "...", "model": "...", "date": "2026-07-27"},
      "fields": [{"field": "eventDate", "value": "1907", "confidence": 0.9}]
    }

Without "occurrence_id" the file's stem is used, so `672827c4....json` also works.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import duck, extract, search
from .db import SessionLocal, init_db
from .models import TranscribeRequest

log = logging.getLogger("import_results")

# What the stored result credits when a file carries no meta.service. Not
# "anthropic": these did not necessarily come from our pipeline, and whoever
# reads the proposal should be able to tell.
DEFAULT_SERVICE = "imported JSON"


def discover(paths: list[str]) -> list[Path]:
    """Expand the CLI arguments into a sorted list of .json files."""
    found: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            found.extend(sorted(p.glob("*.json")))
        elif p.is_file():
            found.append(p)
        else:
            log.warning("skipping %s — no such file or directory", p)
    return found


def occurrence_id_of(path: Path, raw: str) -> str:
    """Prefer an explicit occurrence_id in the payload; fall back to the stem."""
    try:
        payload = extract._loads_lenient(raw)  # tolerates ```json fences
        if isinstance(payload, dict):
            value = payload.get("occurrence_id") or payload.get("occurrenceID")
            if value:
                return str(value).strip()
    except Exception:  # noqa: BLE001 - parse_pasted will report the real problem
        pass
    return path.stem


async def import_file(db: Session, path: Path, *, commit: bool) -> str:
    """Import one file. Returns an outcome: done | failed | skipped.

    Never raises: a malformed file marks its own request `failed` and leaves the
    rest of the batch alone, matching `pipeline.process_one`.
    """
    raw = path.read_text(encoding="utf-8")
    occ_id = occurrence_id_of(path, raw)

    req = db.execute(
        select(TranscribeRequest)
        .where(TranscribeRequest.occurrence_id == occ_id)
        .where(TranscribeRequest.status == "pending")
        .order_by(TranscribeRequest.created.desc())
    ).scalars().first()

    if req is None:
        print(f"  {path.name}: no pending request for {occ_id} — skipped")
        return "skipped"

    try:
        record = await search.get_detail(occ_id)
        if record is None:
            raise ValueError("occurrence not found")

        result = extract.parse_pasted(occ_id, raw)  # validates, clamps, drops unknowns
        result.image_urls = extract.images(record)
        result.service = result.service or DEFAULT_SERVICE

        req.result_json = result.model_dump_json()
        req.status = "done"
        req.processed_at = datetime.now(timezone.utc)
        req.error = None

        if commit:
            db.commit()
        print(f"  {path.name}: {len(result.fields)} fields -> request {req.id} done")
        for f in result.fields:
            value = f.value.replace("\n", "⏎")
            if len(value) > 46:
                value = value[:45] + "…"
            print(f"      {f.field:<26} {f.confidence:.2f}  {value}")
        return "done"

    except Exception as exc:  # noqa: BLE001 - isolate one file's failure
        db.rollback()
        req.status = "failed"
        req.processed_at = datetime.now(timezone.utc)
        req.error = str(exc)[:500]
        if commit:
            db.commit()
        log.warning("import of %s failed: %s", path.name, exc)
        print(f"  {path.name}: FAILED -> request {req.id} failed ({exc})")
        return "failed"


async def _run(paths: list[str], commit: bool) -> dict:
    files = discover(paths)
    if not files:
        print("no .json files found")
        return {"files": 0, "done": 0, "failed": 0, "skipped": 0, "fields": 0}

    init_db()
    duck.connect()
    try:
        tally = {"files": len(files), "done": 0, "failed": 0, "skipped": 0}
        print(f"{len(files)} file(s){'' if commit else '  [DRY RUN — nothing will be written]'}\n")
        with SessionLocal() as db:
            for path in files:
                tally[await import_file(db, path, commit=commit)] += 1
            if not commit:
                db.rollback()
        return tally
    finally:
        duck.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(
        description="Import transcription result JSON into the annotation store.",
    )
    ap.add_argument("paths", nargs="+", help="JSON files, or directories of them")
    ap.add_argument("--commit", action="store_true",
                    help="write to the database (without it, this is a dry run)")
    args = ap.parse_args()

    tally = asyncio.run(_run(args.paths, args.commit))
    print(f"\n{tally['done']} done · {tally['failed']} failed · "
          f"{tally['skipped']} skipped  (of {tally['files']} file(s))")
    if not args.commit and tally["files"]:
        print("dry run — re-run with --commit to write.")


if __name__ == "__main__":
    main()
