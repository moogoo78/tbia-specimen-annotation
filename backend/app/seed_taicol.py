"""Load a TaiCOL release CSV into the reference store (``taicol_taxon``).

    python -m app.seed_taicol                       # newest TaiCOL_taxon_*.csv in data/ or tmp/
    python -m app.seed_taicol --csv path/to/file    # a specific release
    python -m app.seed_taicol --version 2026-10-30  # when the filename carries no date
    python -m app.seed_taicol --dry-run             # parse + derive, write nothing

The CSV is TaiCOL's own taxon export (``TaiCOL_taxon_YYYYMMDD.csv``): one row per
taxon with its kingdom…genus but **no parent id**, so the tree is derived here:

- a major rank's parent is the taxon named in the deepest higher major column
  (a genus's family, a family's order …), looked up by (kingdom, rank, name);
- an infraspecific taxon's parent is its species (the binomial), else its genus;
- minor ranks (subfamily, tribe, section, …) are kept for search but are not
  tree nodes, so a family's children are its genera, as on Explore's tree.

Replaces both tables wholesale, so it is idempotent; the release version (from
the filename, or ``--version``) is what identifications cite as nameAccordingTo.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import delete, insert

from .db import RefSessionLocal, init_db
from .models import TaicolRelease, TaicolTaxon

REPO = Path(__file__).resolve().parents[2]
MAJOR = ("kingdom", "phylum", "class", "order", "family", "genus", "species")
INFRA = {"subspecies", "variety", "form", "special form", "hybrid formula"}
_DATE = re.compile(r"(\d{4})(\d{2})(\d{2})")


def find_csv() -> Path | None:
    files = sorted([*REPO.glob("data/TaiCOL_taxon_*.csv"), *REPO.glob("tmp/TaiCOL_taxon_*.csv")],
                   key=lambda p: p.name)
    return files[-1] if files else None


def version_from(path: Path) -> str | None:
    m = _DATE.search(path.name)
    return f"{m[1]}-{m[2]}-{m[3]}" if m else None


def derive(rows: list[dict]) -> list[dict]:
    """CSV rows -> taicol_taxon rows, with parent_id / n_children / n_species."""
    out, by_key = [], {}
    for r in rows:
        rank = (r["rank"] or "").strip().lower()
        row = {
            "taxon_id": r["taxon_id"],
            "name_id": int(r["name_id"]) if (r.get("name_id") or "").isdigit() else None,
            "simple_name": r["simple_name"] or "",
            "name_author": r.get("name_author") or "",
            "rank": rank,
            "common_name_c": r.get("common_name_c") or "",
            "alternative_name_c": r.get("alternative_name_c") or "",
            "kingdom": r.get("kingdom") or "",
            "family": r.get("family") or "",
            "family_c": r.get("family_c") or "",
            "updated_at": r.get("updated_at") or "",
            "in_tree": rank in MAJOR or rank in INFRA,
            "parent_id": None, "n_children": 0, "n_species": 0,
            "_higher": {k: (r.get(k) or "") for k in MAJOR[:-1]},
        }
        row["search"] = " ".join(x for x in (
            row["simple_name"].lower(), row["common_name_c"], row["alternative_name_c"]) if x)
        out.append(row)
        if rank in MAJOR:
            by_key.setdefault((row["kingdom"], rank, row["simple_name"]), row["taxon_id"])

    for row in out:
        if not row["in_tree"]:
            continue
        rank, h, k = row["rank"], row["_higher"], row["kingdom"]
        parent = None
        if rank in INFRA:
            binomial = " ".join(row["simple_name"].split()[:2])
            parent = by_key.get((k, "species", binomial)) or by_key.get((k, "genus", h["genus"]))
        elif rank != "kingdom":
            # Deepest higher major rank that is filled and above this one.
            above = MAJOR[:MAJOR.index(rank)]
            for col in reversed(above):
                if h.get(col) and (pid := by_key.get((k, col, h[col]))) and pid != row["taxon_id"]:
                    parent = pid
                    break
        row["parent_id"] = parent

    kids: dict[str, list[dict]] = defaultdict(list)
    for row in out:
        if row["in_tree"] and row["parent_id"]:
            kids[row["parent_id"]].append(row)
    index = {r["taxon_id"]: r for r in out}

    def count(tid: str) -> int:  # species + infraspecific at or below
        row = index[tid]
        if "_n" in row:
            return row["_n"]
        n = int(row["rank"] == "species" or row["rank"] in INFRA)
        for c in kids.get(tid, ()):
            n += count(c["taxon_id"])
        row["_n"] = n
        return n

    sys.setrecursionlimit(10_000)
    for row in out:
        row["n_children"] = len(kids.get(row["taxon_id"], ()))
        if row["in_tree"]:
            row["n_species"] = count(row["taxon_id"])
    for row in out:
        row.pop("_higher", None)
        row.pop("_n", None)
    return out


def populate(csv_path: Path | str | None = None, version: str | None = None,
             dry_run: bool = False) -> dict:
    path = Path(csv_path) if csv_path else find_csv()
    if path is None or not path.exists():
        raise SystemExit("seed-taicol: no TaiCOL_taxon_*.csv found in data/ or tmp/ (use --csv)")
    version = version or version_from(path)
    if not version:
        raise SystemExit(f"seed-taicol: no date in {path.name}; pass --version YYYY-MM-DD")
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = derive(list(csv.DictReader(fh)))
    stats = {
        "version": version, "file": path.name, "n_taxa": len(rows),
        "in_tree": sum(r["in_tree"] for r in rows),
        "roots": sum(r["in_tree"] and not r["parent_id"] for r in rows),
        "orphans": sum(r["in_tree"] and not r["parent_id"] and r["rank"] != "kingdom" for r in rows),
    }
    if dry_run:
        return stats
    init_db()
    with RefSessionLocal() as db:
        db.execute(delete(TaicolTaxon))
        db.execute(delete(TaicolRelease))
        for i in range(0, len(rows), 5000):
            db.execute(insert(TaicolTaxon), rows[i:i + 5000])
        db.add(TaicolRelease(version=version, source_file=path.name, n_taxa=len(rows)))
        db.commit()
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--csv")
    ap.add_argument("--version")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    s = populate(a.csv, a.version, a.dry_run)
    print(f"TaiCOL {s['version']} ({s['file']}): {s['n_taxa']:,} taxa, {s['in_tree']:,} in the tree, "
          f"{s['roots']} roots, {s['orphans']} without a parent"
          + (" — dry run, nothing written" if a.dry_run else ""))


if __name__ == "__main__":
    main()
