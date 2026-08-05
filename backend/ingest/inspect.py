"""Summarise a downloaded TBIA export and diff it against data/registry.json.

Step 1 of the refresh: read-only, so it can be pointed at anything. It answers
the two questions that have to be settled before ingesting —

  * what does this export contain (rows, datasets, rights holders)?
  * what must data/registry.json change to match it?

and warns when the export's columns have moved, which stops build.py.

Writes two files next to the export (or into --outdir):

    <name>-summary.md    counts, rights holders, registry diff, column diff
    <name>-datasets.csv  one row per tbiaDatasetID, for the human decision

The export is streamed row by row, so multi-GB files work in constant memory.

    python -m ingest.inspect ../tmp/tbia_xxx.zip
    python -m ingest.inspect ../tmp/tbia_xxx.csv -o ../tmp
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter

from ingest.common import (
    COLUMNS_MANIFEST,
    DEFAULT_DB,
    DEFAULT_REGISTRY,
    GBIF,
    INSPECT_COLUMNS,
    column_baseline,
    compare_columns,
    flatten_registry,
    load_registry,
    open_export,
    raise_field_limit,
)


def scan(stream):
    """One pass: totals, per-dataset facts, per-rightsHolder counts."""
    reader = csv.reader(stream)
    try:
        header = next(reader)
    except StopIteration:
        sys.exit("export is empty")

    missing = [c for c in INSPECT_COLUMNS if c not in header]
    if missing:
        sys.exit(f"missing expected column(s): {', '.join(missing)}")
    idx = {c: header.index(c) for c in INSPECT_COLUMNS}
    width = len(header)

    total = 0
    short_rows = 0
    # tbiaDatasetID -> [datasetName, sourceDatasetID, gbifDatasetID, count, {rightsHolder}]
    datasets: dict[str, list] = {}
    rights: Counter = Counter()

    for row in reader:
        total += 1
        if len(row) < width:
            # Ragged row: pad so a truncated tail doesn't shift/crash the lookups.
            short_rows += 1
            row = row + [""] * (width - len(row))

        holder = row[idx["rightsHolder"]].strip()
        rights[holder] += 1

        key = row[idx["tbiaDatasetID"]].strip()
        entry = datasets.get(key)
        if entry is None:
            datasets[key] = [row[idx["datasetName"]].strip(),
                             row[idx["sourceDatasetID"]].strip(),
                             row[idx["gbifDatasetID"]].strip(),
                             1,
                             {holder} if holder else set()]
        else:
            entry[3] += 1
            if holder:
                entry[4].add(holder)
            # Fill in identifiers that were blank on the first row we saw.
            for slot, col in enumerate(("datasetName", "sourceDatasetID", "gbifDatasetID")):
                if not entry[slot]:
                    entry[slot] = row[idx[col]].strip()

        if total % 1_000_000 == 0:
            print(f"  ...{total:,} rows", file=sys.stderr)

    return header, total, datasets, rights, short_rows


def write_datasets_csv(path, datasets):
    # Group by rightsHolder; largest datasets first within each holder.
    rows = sorted(datasets.items(),
                  key=lambda kv: (";".join(sorted(kv[1][4])), -kv[1][3], kv[0]))
    # utf-8-sig: the BOM is what makes Excel read the CJK names as UTF-8.
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tbiaDatasetID", "datasetName", "sourceDatasetID", "gbifDatasetID",
                    "rightsHolder", "numOfRows"])
        for ds_id, (name, src, gbif, count, holders) in rows:
            w.writerow([ds_id, name, src, gbif, ";".join(sorted(holders)), count])


def md(cell: str) -> str:
    return cell.replace("|", "\\|") if cell else ""


def registry_section(datasets: dict, registry_path: str) -> list[str]:
    """Curated vs export: what the operator has to decide before building."""
    lines = ["## Registry reconciliation", ""]
    if not os.path.exists(registry_path):
        lines += [f"`{registry_path}` not found — nothing to reconcile against. "
                  "`build.py` will refuse to run until it exists.", ""]
        return lines

    curated = {r["tbia_dataset_id"]: r for r in flatten_registry(load_registry(registry_path))}
    lines.append(f"Registry: `{os.path.basename(registry_path)}` — "
                 f"{len(curated)} dataset(s) across "
                 f"{len({r['institution_code'] for r in curated.values()})} source(s).")
    lines.append("")

    gone = [(ds_id, r) for ds_id, r in curated.items() if ds_id not in datasets]
    lines += ["### Curated but missing from this export", ""]
    if gone:
        lines += ["Keeping these in registry.json ingests nothing.", "",
                  "| tbiaDatasetID | Source | Curated name |", "| --- | --- | --- |"]
        for ds_id, r in sorted(gone, key=lambda kv: kv[1]["institution_code"]):
            lines.append(f"| `{ds_id}` | {md(r['institution_code'])} | "
                         f"{md(r.get('dataset_name') or '')} |")
    else:
        lines.append("_None — every curated dataset is present._")
    lines.append("")

    # GBIF rows are ingested without being curated, so listing ~900 of them
    # would bury the handful the operator has to act on.
    gbif_ids = {ds_id for ds_id, e in datasets.items() if GBIF in e[4]}
    new = [(ds_id, e) for ds_id, e in datasets.items()
           if ds_id not in curated and ds_id not in gbif_ids]
    lines += ["### In this export but not in the registry", ""]
    if new:
        lines += ["Not ingested unless you add them (GBIF-held datasets are ingested "
                  "regardless and are not listed here).", "",
                  "| tbiaDatasetID | Dataset | rightsHolder | Rows |",
                  "| --- | --- | --- | ---: |"]
        for ds_id, e in sorted(new, key=lambda kv: -kv[1][3]):
            lines.append(f"| `{ds_id}` | {md(e[0])} | {md(';'.join(sorted(e[4])))} | {e[3]:,} |")
    else:
        lines.append("_None._")
    lines.append("")

    renamed = [(ds_id, r.get("dataset_name") or "", datasets[ds_id][0])
               for ds_id, r in curated.items()
               if ds_id in datasets and (r.get("dataset_name") or "") != datasets[ds_id][0]]
    lines += ["### Renamed upstream", ""]
    if renamed:
        lines += ["| tbiaDatasetID | registry.json | This export |", "| --- | --- | --- |"]
        for ds_id, old, new_name in sorted(renamed):
            lines.append(f"| `{ds_id}` | {md(old)} | {md(new_name)} |")
    else:
        lines.append("_None._")
    lines.append("")

    lines += [f"GBIF-held datasets in this export: **{len(gbif_ids):,}** "
              "(ingested by rightsHolder, never curated).", ""]
    return lines


def columns_section(header: list[str], db_path: str, manifest_path: str) -> list[str]:
    """The same comparison build.py aborts on — reported here, never enforced."""
    lines = ["## Columns", ""]
    baseline, source = column_baseline(db_path, manifest_path)
    if baseline is None:
        lines += [f"No column baseline found (no `{os.path.basename(manifest_path)}`, no store "
                  f"at `{db_path}`). The first build will record one.", "",
                  f"This export has {len(header)} column(s):", "",
                  "```", ", ".join(header), "```", ""]
        return lines

    added, removed = compare_columns(baseline, header)
    lines.append(f"Baseline: `{source}` ({len(baseline)} columns). "
                 f"This export: {len(header)} columns.")
    lines.append("")
    if not added and not removed:
        lines += ["Matches the baseline.", ""]
        return lines

    lines += ["**The columns have changed — `build.py` will abort until the baseline is "
              "updated.** A rename shows up as one added and one removed column.", ""]
    if added:
        lines += ["Added in this export:", ""] + [f"- `{c}`" for c in added] + [""]
    if removed:
        lines += ["Gone from this export:", ""] + [f"- `{c}`" for c in removed] + [""]
    lines += [f"Accept them by editing `{os.path.basename(manifest_path)}` to match, then "
              "re-run the build.", ""]
    return lines


def write_summary_md(path, source_name, header, total, datasets, rights, short_rows,
                     registry_path, db_path, manifest_path):
    lines = [
        "# TBIA Export Summary",
        "",
        f"Source: `{source_name}`",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
        f"| Rows (occurrence records) | {total:,} |",
        f"| Datasets (`tbiaDatasetID`) | {len(datasets):,} |",
        f"| Rights holders (`rightsHolder`) | {len(rights):,} |",
        f"| Columns | {len(header):,} |",
        "",
        "## Rights holders",
        "",
        "| # | rightsHolder | Rows | Share |",
        "| ---: | --- | ---: | ---: |",
    ]
    for n, (holder, count) in enumerate(rights.most_common(), 1):
        share = f"{count / total * 100:.2f}%" if total else "-"
        lines.append(f"| {n} | {md(holder) or '_(blank)_'} | {count:,} | {share} |")
    if short_rows:
        lines += ["", f"> Note: {short_rows:,} row(s) had fewer fields than the header "
                      "and were padded."]
    lines.append("")

    lines += registry_section(datasets, registry_path)
    lines += columns_section(header, db_path, manifest_path)

    with open(path, "w", encoding="utf-8-sig") as fh:
        fh.write("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser(description="Summarise a TBIA CSV/ZIP export.")
    ap.add_argument("export", help="path to the TBIA .zip or .csv")
    ap.add_argument("-o", "--outdir", help="output directory (default: alongside the export)")
    ap.add_argument("--registry", default=DEFAULT_REGISTRY, help="registry JSON to diff against")
    ap.add_argument("--db", default=DEFAULT_DB, help="store to fall back on for the column baseline")
    ap.add_argument("--manifest", default=COLUMNS_MANIFEST, help="column manifest")
    args = ap.parse_args()

    if not os.path.exists(args.export):
        sys.exit(f"no such file: {args.export}")

    outdir = args.outdir or os.path.dirname(os.path.abspath(args.export))
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.export))[0]
    summary_path = os.path.join(outdir, f"{stem}-summary.md")
    datasets_path = os.path.join(outdir, f"{stem}-datasets.csv")

    raise_field_limit()
    print(f"reading {args.export} ...", file=sys.stderr)
    with open_export(args.export) as (stream, member):
        header, total, datasets, rights, short_rows = scan(stream)

    write_datasets_csv(datasets_path, datasets)
    write_summary_md(summary_path, member, header, total, datasets, rights, short_rows,
                     args.registry, args.db, args.manifest)

    print(f"\n{total:,} rows | {len(datasets):,} datasets | {len(rights):,} rights holders "
          f"| {len(header)} columns", file=sys.stderr)
    print(f"wrote {summary_path}", file=sys.stderr)
    print(f"wrote {datasets_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
