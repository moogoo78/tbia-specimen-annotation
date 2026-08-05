# tbia-export-inspect Specification

## Purpose

Lets an operator inspect a freshly downloaded TBIA export before any of it is ingested, so the
curated `data/registry.json` can be brought in line with what the export actually contains.

## Requirements

### Requirement: Read an export from zip or csv

The inspect step SHALL accept either a TBIA `.zip` containing one CSV, or a plain `.csv`, and SHALL
process it in constant memory regardless of file size.

#### Scenario: Zip input

- **WHEN** the operator points the inspect step at a `.zip` holding one `.csv` member
- **THEN** the CSV inside is read directly from the archive without extracting it to disk

#### Scenario: Csv input

- **WHEN** the operator points the inspect step at a plain `.csv`
- **THEN** it is read directly

#### Scenario: Multi-gigabyte export

- **WHEN** the export holds several million rows
- **THEN** the step completes without loading the whole file into memory

#### Scenario: Oversized field

- **WHEN** a row carries a field larger than the CSV reader's default field limit (TBIA `synonyms`
  and `associatedMedia` values do)
- **THEN** the row is still read rather than aborting the run

#### Scenario: Missing required column

- **WHEN** the export lacks any of `tbiaDatasetID`, `datasetName`, `sourceDatasetID`,
  `gbifDatasetID`, `rightsHolder`
- **THEN** the step exits with a message naming the missing column(s) and writes no output files

#### Scenario: Ragged row

- **WHEN** a row has fewer fields than the header
- **THEN** it is padded rather than shifting the column lookups, and the count of such rows is
  reported in the summary

### Requirement: Dataset inventory output

The inspect step SHALL write a CSV holding one row per `tbiaDatasetID` observed in the export, with
that dataset's name, `sourceDatasetID`, `gbifDatasetID`, the set of `rightsHolder` values seen for
it, and its record count.

#### Scenario: Inventory is written

- **WHEN** the inspect step finishes reading an export
- **THEN** a `<export-name>-datasets.csv` is written next to the export (or into a requested output
  directory), grouped by rights holder with the largest datasets first within each holder

#### Scenario: Chinese names survive the round trip

- **WHEN** the inventory is opened in a spreadsheet application
- **THEN** the Chinese dataset and institution names render correctly

#### Scenario: Identifiers blank on the first row seen

- **WHEN** a dataset's first row leaves `datasetName`, `sourceDatasetID` or `gbifDatasetID` empty
  but a later row of the same dataset fills it in
- **THEN** the inventory reports the non-empty value

### Requirement: Export summary output

The inspect step SHALL write a Markdown summary reporting the total row count, the number of
distinct datasets, and a per-`rightsHolder` breakdown with counts and shares.

#### Scenario: Summary is written

- **WHEN** the inspect step finishes reading an export
- **THEN** a `<export-name>-summary.md` is written alongside the inventory, naming the source file
  it was produced from

### Requirement: Registry reconciliation report

The inspect step SHALL compare the export against `data/registry.json` and report what the operator
must decide before ingesting, distinguishing curated datasets that are gone from the export,
datasets present in the export but not curated, and curated datasets whose name has changed.

#### Scenario: Curated dataset missing from the export

- **WHEN** a `tbia_dataset_id` listed in `data/registry.json` appears in no row of the export
- **THEN** the report lists it under a "missing from export" heading with its institution code and
  curated name, warning that keeping it in the registry ingests nothing

#### Scenario: Uncurated non-GBIF dataset

- **WHEN** the export holds a dataset whose `tbiaDatasetID` is absent from `data/registry.json` and
  whose rights holder is not `GBIF`
- **THEN** the report lists it under a "not in registry" heading with its name, rights holder and
  row count, so the operator can decide whether to curate it

#### Scenario: Renamed dataset

- **WHEN** a curated dataset's `datasetName` in the export differs from the `name` in
  `data/registry.json`
- **THEN** the report shows both names side by side

#### Scenario: GBIF datasets are not listed individually

- **WHEN** the export holds hundreds of datasets whose rights holder is `GBIF`
- **THEN** they are summarised as a count rather than enumerated, because they are ingested without
  being curated

#### Scenario: Registry file absent

- **WHEN** `data/registry.json` does not exist
- **THEN** the summary and inventory are still written, and the reconciliation section says the
  registry was not found instead of failing the run

### Requirement: Column change report

The inspect step SHALL compare the export's column set against the recorded column baseline and
report any difference, so the operator learns that the build will stop before they spend time on
the registry edit.

#### Scenario: Columns differ from the baseline

- **WHEN** the export's columns do not match the baseline
- **THEN** the summary names the added and removed columns and states that the build will abort
  until the baseline is updated

#### Scenario: Columns match

- **WHEN** the export's columns match the baseline
- **THEN** the summary says so in one line

#### Scenario: No baseline yet

- **WHEN** neither a column manifest nor an existing store is available to compare against
- **THEN** the summary lists the export's columns and says no baseline was found, without failing
  the run

#### Scenario: Reporting only

- **WHEN** the columns differ
- **THEN** the inspect step still writes both output files and exits successfully — refusing the
  export is the build's job, not inspect's

### Requirement: Inspect never mutates state

The inspect step SHALL be read-only with respect to the annotation store, the occurrence store and
the registry file.

#### Scenario: Nothing but reports is written

- **WHEN** the inspect step runs to completion
- **THEN** the only files created or modified are the summary and inventory it reports having
  written; `data/registry.json`, `data/tbia.duckdb` and `data/annotations.sqlite` are untouched
