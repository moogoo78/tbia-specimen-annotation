## 1. Probe the exports

- [x] 1.1 Check both repo zips (`tbia_6a2912275e9edc001925b00c.zip`,
      `tbia_6a56e7a62a75e6001769cb69.zip`) for the presence of `sourceDatasetID` and
      `gbifDatasetID` in their CSV headers — a header-only read, no full scan
      → both carry all 7 needed columns (66 columns each); zip mtimes 2026-06-10 / 2026-07-15
- [x] 1.2 Record the current `data/tbia_datasets.csv` dataset count and total `n_records` as the
      baseline the refactor must reproduce
      → 989 datasets, 2,068,590 records (904 registered / 85 not)

## 2. Column resolution

- [x] 2.1 Add a helper that reads the export's header once (`read_csv` with `LIMIT 0`) and
      returns the set of available column names
- [x] 2.2 Add a projection helper that emits `"<col>"` when present and `NULL` when absent, so a
      missing `sourceDatasetID` / `gbifDatasetID` yields an empty column instead of a binder error

## 3. Single-scan fold

- [x] 3.1 Replace the multi-CTE query with one `CREATE TEMP TABLE facts AS SELECT ... count(*)
      FROM read_csv(...) GROUP BY tbia_dataset_id, rights_holder, source_dataset_id,
      gbif_dataset_id, resource_contacts, bio_group`, filtering blank dataset ids as today
- [x] 3.2 Derive per-dataset rows from `facts`: `n_records` as the summed count, `bio_groups` as
      the existing top-5 frequency-ranked `grp:n|...` string, ordered by `n_records` descending
- [x] 3.3 Make `dataset_name`, `rights_holder`, `resource_contacts`, `source_dataset_id`, and
      `gbif_dataset_id` the highest-count non-empty value per dataset, replacing `any_value`
- [x] 3.4 Derive export-level figures from `facts`: total rows parsed, `count(DISTINCT
      tbia_dataset_id)`, and `count(DISTINCT rights_holder)` counted export-wide
- [x] 3.5 Verify against 1.2 — dataset count and total records must match the baseline
      → 989 datasets / 2,068,590 records — exact match

## 4. CSV export

- [x] 4.1 Add `source_dataset_id` and `gbif_dataset_id` to `FIELDS` and to each written row,
      leaving existing column names and their order untouched
- [x] 4.2 Confirm a dataset with no `gbifDatasetID` still writes its row, with an empty cell
      → `gbifDatasetID` is blank on ALL rows of BOTH exports; rows still written

## 5. Markdown report

- [x] 5.1 Add `--report` (default `data/tbia_export_summary.md`), creating parent directories on
      write
- [x] 5.2 Resolve the export created date from the zip's mtime, falling back to the CSV's mtime
      under `--csv`, formatted as a readable local timestamp
- [x] 5.3 Write the headline table: export file scanned, which file the created date came from,
      created date, total rows parsed, dataset count, rights-holder count
- [x] 5.4 Write the registry review section: registered vs. unregistered dataset counts with the
      records behind each, and datasets registered but absent from this export (with their
      section/code)
- [x] 5.5 Write the largest-unregistered table (id, name, record count, bio groups) ordered by
      records descending, with an explicit "adds no new datasets" line when the list is empty
- [x] 5.6 Make the report always describe the whole export — `--new-only` filters CSV rows only
- [x] 5.7 Keep the existing stdout summary unchanged; add one line naming the report path written

## 6. Verify and document

- [x] 6.1 Run against the extracted CSV (`--csv source/tbia_6a56e7a62a75e6001769cb69.csv`) and
      read the report — figures sane, dataset count equals CSV data rows, `n_records` sums to the
      reported total
      → verified via Docker (no host venv exists); figures reconcile
- [x] 6.2 Run against a zip via auto-detection and confirm the created date is the zip's mtime
      → verified with a synthetic mini-export; date = zip mtime, now stamped with UTC offset
- [x] 6.3 Confirm a missing/bogus input exits non-zero with a clear message and writes neither
      output
      → needed a fix: bare --zip path threw a traceback; now exits 1 with a clear message
- [x] 6.4 Run `--new-only` and confirm the CSV narrows while the report's totals do not
- [x] 6.5 Update the module docstring for the report output and the new flag; point
      `task-tbia-data-etl.md` step 2 and `data-flow.md` at the report
- [ ] 6.6 Commit the script (currently untracked) together with the doc updates
