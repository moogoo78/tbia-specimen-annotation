"""Populate the SQLite collector tables from the DuckDB occurrence store.

    python -m app.seed_collectors          # full (re)build of collectors + aliases
    python -m app.seed_collectors --sync   # incremental: map only NEW recorded_by
                                           #   values, preserving existing rows
                                           #   (incl. curator-edited mappings)

Run once to seed, then again with ``--sync`` after each ``make ingest`` of a
fresh TBIA zip. The mapping joins back to occurrences via the raw ``recorded_by``
string, so the read-only DuckDB is never touched -- a re-ingest can rebuild the
occurrence store without disturbing any of this enrichment.
"""

from __future__ import annotations

import argparse

import duckdb
from sqlalchemy import delete, func, select

from .collectors_parse import parse_collector
from .config import settings
from .db import SessionLocal, init_db
from .models import Collector, CollectorAlias


def _distinct_recorded_by(db_path: str) -> list[tuple[str, int]]:
    """(raw recorded_by, occurrence count) for every non-blank value."""
    con = duckdb.connect(db_path, read_only=True)
    try:
        return con.execute(
            "SELECT recorded_by, count(*) FROM occurrences "
            "WHERE recorded_by IS NOT NULL AND trim(recorded_by) <> '' "
            "GROUP BY recorded_by"
        ).fetchall()
    finally:
        con.close()


def _key(zh: str, en: str) -> str:
    return zh if zh else "@" + en


def populate(sync: bool = False, db_path: str | None = None) -> dict:
    init_db()
    db_path = db_path or settings.duckdb_path
    raws = _distinct_recorded_by(db_path)

    with SessionLocal() as db:
        if not sync:
            db.execute(delete(CollectorAlias))
            db.execute(delete(Collector))
            db.commit()

        # Existing state (empty on a full rebuild).
        index: dict[str, Collector] = {}
        en_index: dict[str, Collector] = {}
        for c in db.execute(select(Collector)).scalars():
            index[_key(c.name, c.name_en)] = c
            if c.name and c.name_en:
                en_index.setdefault(c.name_en, c)
        existing_alias = {
            r[0] for r in db.execute(select(CollectorAlias.recorded_by)).all()
        }

        # Parse the unmapped raws up front so we can process Chinese-named people
        # first; that lets a later English-only variant attach to the same person
        # instead of spawning a duplicate (mirrors the CSV exporter's dedup).
        todo: list[tuple[str, int, str, str]] = []
        skipped = 0
        for raw, n in raws:
            if raw in existing_alias:
                continue
            res = parse_collector(raw)
            if res is None:
                skipped += 1
                continue
            todo.append((raw, n, res[0], res[1]))
        todo.sort(key=lambda t: t[2] == "")  # zh-present (False) before en-only

        new_collectors = new_aliases = 0
        for raw, n, zh, en in todo:
            if zh:
                k = _key(zh, en)
                c = index.get(k)
                if c is None:
                    c = Collector(name=zh, name_en=en)
                    db.add(c)
                    db.flush()
                    index[k] = c
                    new_collectors += 1
                elif not c.name_en and en:
                    c.name_en = en  # backfill romanization once we learn it
                if en:
                    en_index.setdefault(en, c)
            else:  # English/romanized only
                c = en_index.get(en)  # fold into a Chinese-named person if known
                if c is None:
                    k = _key("", en)
                    c = index.get(k)
                    if c is None:
                        c = Collector(name="", name_en=en)
                        db.add(c)
                        db.flush()
                        index[k] = c
                        new_collectors += 1
            c.n_records += n
            db.add(CollectorAlias(recorded_by=raw, collector_id=c.id, source="auto"))
            new_aliases += 1

        db.commit()
        totals = {
            "collectors": db.execute(select(func.count(Collector.id))).scalar_one(),
            "aliases": db.execute(
                select(func.count(CollectorAlias.recorded_by))
            ).scalar_one(),
        }

    return {
        "mode": "sync" if sync else "rebuild",
        "distinct_recorded_by": len(raws),
        "new_collectors": new_collectors,
        "new_aliases": new_aliases,
        "skipped_non_person": skipped,
        **totals,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sync", action="store_true",
                    help="incremental: map only new recorded_by values, keep existing")
    args = ap.parse_args()
    r = populate(sync=args.sync)
    print(f"[{r['mode']}] distinct recorded_by: {r['distinct_recorded_by']:,}")
    print(f"  new collectors : {r['new_collectors']:,}")
    print(f"  new aliases    : {r['new_aliases']:,}")
    print(f"  non-person skip: {r['skipped_non_person']:,}")
    print(f"  totals -> collectors={r['collectors']:,} aliases={r['aliases']:,}")


if __name__ == "__main__":
    main()
