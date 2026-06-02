"""Export a unique list of *people* from the occurrences ``recorded_by`` field.

Thin CLI around the shared parser in ``app.collectors_parse`` (the single source
of truth, also used by ``app.seed_collectors``). Writes ``name`` (Chinese) +
``name_en`` (romanized) columns. See that module for the parsing rules.

Usage: backend/.venv/bin/python scripts/extract_recorded_by_people.py [--db ...] [--out ...]
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

import duckdb

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_DB = os.path.join(REPO, "data", "occurrences.duckdb")
DEFAULT_OUT = os.path.join(REPO, "data", "recorded_by_people.csv")

sys.path.insert(0, os.path.join(REPO, "backend"))
from app.collectors_parse import parse_collector  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=True)
    vals = [r[0] for r in con.execute(
        "SELECT DISTINCT recorded_by FROM occurrences "
        "WHERE recorded_by IS NOT NULL AND trim(recorded_by) <> ''"
    ).fetchall()]

    # group by Chinese name when present, else by English name; merge missing halves
    people: dict[str, list[str]] = {}
    dropped = 0
    for raw in vals:
        res = parse_collector(raw)
        if res is None:
            dropped += 1
            continue
        zh, en = res
        key = zh if zh else "@" + en
        if key not in people:
            people[key] = [zh, en]
        elif not people[key][1] and en:
            people[key][1] = en

    # drop English-only rows whose name_en already belongs to a Chinese-named person
    en_of_zh = {v[1] for k, v in people.items() if not k.startswith("@") and v[1]}
    rows = [(zh, en) for (zh, en) in people.values()
            if zh or en not in en_of_zh]
    rows.sort(key=lambda r: (r[0] == "", r[0], r[1]))

    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["name", "name_en"])
        w.writerows(rows)

    print(f"distinct recorded_by : {len(vals):,}")
    print(f"dropped (org/unknown): {dropped:,}")
    print(f"unique people written: {len(rows):,} -> {args.out}")
    print("--- preview ---")
    for zh, en in rows[:15]:
        print(f"  {zh!r:>14} | {en!r}")


if __name__ == "__main__":
    main()
