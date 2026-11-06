# backend/ingest/CLAUDE.md

Loaded when working under `backend/ingest/`. Moved from the root CLAUDE.md, which still holds the cross-cutting rules.

## Data refresh

`backend/ingest/` owns the whole path from a downloaded export to a servable store. Four
steps, one of which is a human:

```bash
make inspect ZIP=tmp/tbia_xxx.zip         # 1. ~3 min; writes <name>-summary.md + -datasets.csv
                                          # 2. read the summary, edit data/registry.json
make build-db ZIP=tmp/tbia_xxx.zip DB=data/tbia.new.duckdb   # 3. ~75s
make prepare DB=data/tbia.new.duckdb                          # 4. ~12s
mv data/tbia.new.duckdb data/tbia.duckdb                      # swap in
```

- **inspect.py** is read-only and streams the zip (constant memory, no extraction). Its
  summary carries the counts, the registry diff and the column diff.
- **build.py** extracts the CSV once (~1.9 GB into `tmp/`, gitignored) and lets DuckDB scan
  it. `occurrence` mirrors the export's columns snake_cased — every column, no hand-kept
  list — plus the registry's `institution_code / institution_name / dataset_code / groups`.
  `dataset` is rolled up from the rows actually loaded, so its counts cannot drift.
- Downloaded exports live in `tmp/`; `find_zip()` looks there first, then the repo root.

The 2026-08-05 export (`tbia_6a72e385d2fb88001772ccd4`): 2,113,068 rows / 1,018 datasets /
66 columns in, **2,079,798 rows / 945 datasets** (20 curated + 925 GBIF) out.

## registry.json

`data/registry.json` maps source → datasets, two-level:
`{ institutions: {...}, aggregators: {...} }`, each `CODE: { name, datasets: { <tbia_dataset_id>: { name, groups[] } } }`.
`groups` vocabulary: `Aves, Amphibia, Reptilia, Mammalia, Actinopterygii, Mollusca,
Arachnida, Insecta, Plantae, Fungi, Protozoa` (plus `Zoology`/`Other` used as broad tags).

It is **hand-curated (tracked in git), holds only the 20 stable institution datasets**
across 9 institutions, and **decides what gets ingested**: `build.py` keeps a row only if
its `tbiaDatasetID` is listed here or its `rightsHolder` is `GBIF`. Deleting an entry
deletes those records from the next store, so edit it from `make inspect`'s report rather
than from memory. The GBIF
aggregator's datasets (925 of them) turn over with every TBIA export, so their ids are
*not* pinned here — `GET /api/registry` reads them from the `dataset` table at request
time and merges them under `aggregators`, keyed by `institution_code`. The GBIF uuid
comes from `source_dataset_id` (the export's own `gbif_dataset_id` is empty). Curated
entries always win: anything registry.json lists is left untouched, so promoting a
dataset to "stable" is just adding it to the file.

**Anything uncurated falls into `aggregators`, not just GBIF** (`occurrences.py`, the
`reg["aggregators"].setdefault(...)` merge). So an institution missing from registry.json
shows up in the UI under 整合平台 instead of 典藏機構 — and because entries are matched on
`tbia_dataset_id`, a stale *code* keeps working silently while the sidebar shows the old
name. `make inspect` reports exactly this — curated-but-absent, present-but-uncurated, and
renamed-upstream — so run it before every refresh and edit from its output.

`../tbia-data/registry-institutions.json` is a **separate, upstream** filter and no longer
something to mirror: it gates which records reach the *export* (TBIA's own ETL drops
anything not listed there or held by GBIF), while `data/registry.json` gates which of the
exported records reach *our store*. The dependency is one-way — an institution dropped
upstream never appears in the export, and no edit here brings it back.

Reconciled against the 2026-08-05 list (now 9 institutions / 20 datasets): NMNS gained the
鳥獸學門 mammal + bird and 古生物學門 datasets, `NTU` (TAI) was added, 林業試驗所 is split
back into `TAIF` (herbarium) and `TFRI` (insect museum) — same display name, two entries —
NMNS dataset codes went Chinese→Latin (`維管束`→`TNM`, `昆蟲`→`ENT`, …), the 農業部 prefix
was dropped from names. `TBRI` (TESRI moth + the two TAIE sets) is gone from the *upstream*
list, but its three datasets are still in the export — held by 台灣生物多樣性網絡 TBN, not by
TBRI — so only their absence here excluded them; they are curated back in and contribute
189,843 rows. Upstream absence therefore does not by itself mean a source is unavailable:
check the export before dropping an entry.

The Explore **Source** facet is driven by that merged response; selecting a source
expands to the union of its `tbia_dataset_id`s.
