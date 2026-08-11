"""Load the curated sampling-event chronology into SQLite.

    python -m app.seed_sampling_events            # replace both tables from the JSON
    python -m app.seed_sampling_events --json …   # from a different file
    python -m app.seed_sampling_events --dry-run  # parse + resolve, write nothing

Reads ``data/sampling_events.json`` -- a hand-curated transcription of a
published chronology, tracked in git the way ``data/registry.json`` is. Re-run it
after correcting a transcription; it replaces both tables wholesale, so it is
idempotent.

Actors are matched to existing ``Collector`` rows on a best-effort basis. Most
19th-century names will not resolve, because those botanists hold no records in
the TBIA export at all -- that is the expected outcome, not a failure, so an
unmatched actor is kept verbatim with a null ``collector_id`` and reported here.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from sqlalchemy import delete, select

from .db import SessionLocal, init_db
from .models import SamplingEvent, SamplingEventActor
from .names import collector_index as _resolver
from .names import fold as _norm

# repo root: backend/app/seed_sampling_events.py -> backend/app -> backend -> repo
DEFAULT_JSON = Path(__file__).resolve().parents[2] / "data" / "sampling_events.json"


def parse_years(verbatim: str) -> tuple[int, int] | None:
    """The 年代 cell -> (year_start, year_end), or None if it is not a plain span.

    Three shapes occur in the source: a single year ("1854"), a full range
    ("1861-1866"), and a range with an elided century ("1960-62" -> 1960/1962).
    Kept here rather than in a build script so a hand-added row can omit the
    derived years, and so a hand-typed pair can be checked against the cell it
    came from.
    """
    v = verbatim.strip().replace("\u2013", "-").replace("\u2014", "-")
    if re.fullmatch(r"\d{4}", v):
        y = int(v)
        return y, y
    m = re.fullmatch(r"(\d{4})\s*-\s*(\d{2}|\d{4})", v)
    if not m:
        return None
    start, tail = m.group(1), m.group(2)
    # "1960-62" borrows the century from the start year.
    end = int(tail) if len(tail) == 4 else int(start[: 4 - len(tail)] + tail)
    return int(start), end


class SeedError(Exception):
    """The chronology file is unusable; nothing was written."""


def _load(path: Path) -> tuple[dict, list[dict]]:
    if not path.exists():
        raise SeedError(f"chronology not found: {path}")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SeedError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(doc, dict) or "events" not in doc:
        raise SeedError(f"{path} must be an object with an 'events' array")
    events = doc["events"]
    if not isinstance(events, list) or not events:
        raise SeedError(f"{path} carries no events")
    return doc.get("source", {}) or {}, events


def _validate(events: list[dict]) -> None:
    """Refuse a partial chronology rather than seeding one."""
    for i, e in enumerate(events):
        where = f"event #{i} (seq={e.get('seq', '?')})"
        derived = parse_years(str(e.get("verbatim_event_date", "")))

        # Derive the range when the row omits it, so a hand-added entry only has
        # to carry the 年代 cell as printed.
        if e.get("year_start") is None and e.get("year_end") is None and derived:
            e["year_start"], e["year_end"] = derived

        for field in ("year_start", "year_end"):
            if not isinstance(e.get(field), int):
                raise SeedError(
                    f"{where}: {field} must be an integer "
                    f"(or give a parseable verbatim_event_date)"
                )
        if e["year_end"] < e["year_start"]:
            raise SeedError(f"{where}: year_end {e['year_end']} precedes year_start {e['year_start']}")
        # Catch a typo'd hand edit: the pair must agree with the cell it came from.
        if derived and derived != (e["year_start"], e["year_end"]):
            raise SeedError(
                f"{where}: verbatim_event_date {e['verbatim_event_date']!r} implies "
                f"{derived[0]}-{derived[1]}, but the row says "
                f"{e['year_start']}-{e['year_end']}"
            )
        actors = e.get("actors")
        if not isinstance(actors, list) or not actors:
            raise SeedError(f"{where}: needs at least one actor")
        for a in actors:
            if not str(a.get("recorded_by", "")).strip():
                raise SeedError(f"{where}: an actor has no recorded_by")


def populate(json_path: Path | str | None = None, dry_run: bool = False) -> dict:
    init_db()
    path = Path(json_path) if json_path else DEFAULT_JSON
    source, events = _load(path)
    _validate(events)

    default_citation = source.get("citation", "")
    unmatched: list[str] = []
    n_actors = n_resolved = 0

    with SessionLocal() as db:
        index = _resolver(db)

        # Replace wholesale in one transaction: re-running after a correction
        # must leave exactly the file's contents, never a merge of both.
        db.execute(delete(SamplingEventActor))
        db.execute(delete(SamplingEvent))
        db.flush()

        for e in events:
            ev = SamplingEvent(
                event_date=e.get("event_date", ""),
                verbatim_event_date=e.get("verbatim_event_date", ""),
                year_start=e["year_start"],
                year_end=e["year_end"],
                verbatim_locality=e.get("verbatim_locality", ""),
                event_remarks=e.get("event_remarks", ""),
                location_according_to=e.get("location_according_to") or default_citation,
                narrative=e.get("narrative", ""),
                source_page=e.get("source_page", 0),
                seq=e.get("seq", 0),
            )
            for pos, a in enumerate(e["actors"]):
                name = str(a["recorded_by"]).strip()
                cid = index.get(_norm(name))
                n_actors += 1
                if cid is None:
                    unmatched.append(name)
                else:
                    n_resolved += 1
                ev.actors.append(SamplingEventActor(
                    recorded_by=name,
                    collector_id=cid,
                    nationality=str(a.get("nationality", "")).strip(),
                    position=a.get("position", pos),
                ))
            db.add(ev)

        if dry_run:
            db.rollback()
        else:
            db.commit()

    return {
        "source": str(path),
        "citation": default_citation,
        "events": len(events),
        "actors": n_actors,
        "resolved": n_resolved,
        "unmatched": sorted(set(unmatched)),
        "dry_run": dry_run,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", dest="json_path", default=None,
                    help=f"chronology file (default: {DEFAULT_JSON})")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse and resolve, but write nothing")
    args = ap.parse_args()
    try:
        r = populate(args.json_path, dry_run=args.dry_run)
    except SeedError as exc:
        raise SystemExit(f"sampling events: {exc}")

    print(f"[{'dry-run' if r['dry_run'] else 'seed'}] {r['source']}")
    print(f"  events   : {r['events']:,}")
    print(f"  actors   : {r['actors']:,}  ({r['resolved']:,} resolved to a collector)")
    if r["unmatched"]:
        # Curation input: these are the names worth chasing, not an error.
        print(f"  unmatched: {len(r['unmatched'])} distinct")
        for n in r["unmatched"]:
            print(f"      - {n}")


if __name__ == "__main__":
    main()
