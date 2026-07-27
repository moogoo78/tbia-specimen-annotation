## ADDED Requirements

### Requirement: Export-level markdown summary report

The inventory script SHALL write a markdown summary of the scanned export to a file, defaulting
to `data/tbia_export_summary.md` and overridable via a command-line option. The report SHALL
state the export file it describes, that file's created date, the total number of occurrence
rows, the number of distinct datasets, and the number of distinct rights holders. It SHALL also
list the rights holders themselves, not only count them.

#### Scenario: Report is written for a scanned export

- **WHEN** the script finishes scanning an export
- **THEN** a markdown file is written at the report path
- **AND** it names the export file scanned and that file's created date
- **AND** it reports total row count, distinct `tbiaDatasetID` count, and distinct
  `rightsHolder` count

#### Scenario: Created date comes from the export file's mtime

- **WHEN** the report records the export's created date
- **THEN** the date is the filesystem modification time of the source zip (or, when scanning an
  already-extracted CSV with no zip, of that CSV)
- **AND** it is rendered as a human-readable local timestamp, not a raw epoch value

#### Scenario: Report path is overridable

- **WHEN** the script is invoked with a report path option pointing elsewhere
- **THEN** the markdown report is written to that path instead of the default
- **AND** any missing parent directory is created

#### Scenario: Rights holders are listed

- **WHEN** the report is written
- **THEN** it lists every distinct rights holder in the export
- **AND** each entry shows how many datasets and how many records that holder accounts for

#### Scenario: Rights holders are counted export-wide

- **WHEN** a single dataset carries more than one rights holder
- **THEN** every distinct holder is counted and listed
- **AND** the count is not reduced to one representative value per dataset

#### Scenario: Counts are consistent with the per-dataset CSV

- **WHEN** the report and the per-dataset CSV are produced from the same scan without a
  registry filter applied
- **THEN** the report's dataset count equals the number of data rows in the CSV
- **AND** the report's total row count equals the sum of the CSV's `n_records` column plus any
  rows carrying no dataset id

#### Scenario: Rows carry no dataset id

- **WHEN** the export contains rows whose `tbiaDatasetID` is blank
- **THEN** those rows are counted in the report's total and disclosed as a separate figure
- **AND** they appear under no dataset in the per-dataset CSV

### Requirement: Registry review counts in the report

The report SHALL carry the registry comparison the script performs, so the pre-ingest review
is captured in a file rather than terminal scrollback. It SHALL state how many of the export's
datasets are already registered in `registry.json` and how many are not, with the record counts
behind each, and SHALL list datasets registered but absent from the export.

#### Scenario: Registered and unregistered datasets are counted

- **WHEN** the report is written
- **THEN** it states the count of datasets present in the registry and the count absent from it
- **AND** it states the number of occurrence records behind the unregistered datasets

#### Scenario: Largest unregistered datasets are listed

- **WHEN** the export contains datasets missing from the registry
- **THEN** the report lists them ordered by record count descending
- **AND** each entry shows its dataset id, dataset name, and record count

#### Scenario: Export omits a registered dataset

- **WHEN** `registry.json` registers a dataset id that the export does not contain
- **THEN** the report identifies that dataset id and the registry source that owns it

#### Scenario: Export adds no new datasets

- **WHEN** every dataset in the export is already registered
- **THEN** the report states that explicitly rather than emitting an empty list

### Requirement: Source and GBIF identifiers in the per-dataset CSV

The per-dataset CSV export SHALL include the originating identifiers for each dataset:
`source_dataset_id` from the export's `sourceDatasetID` field and `gbif_dataset_id` from its
`gbifDatasetID` field. Existing columns SHALL retain their current names and meaning so the
CSV stays readable by anything already consuming it.

#### Scenario: Identifier columns are present

- **WHEN** the per-dataset CSV is written
- **THEN** each row carries `source_dataset_id` and `gbif_dataset_id` alongside
  `tbia_dataset_id`, `dataset_name`, and `rights_holder`

#### Scenario: A dataset has no GBIF identifier

- **WHEN** a dataset's `gbifDatasetID` is empty or absent in the export
- **THEN** the corresponding CSV cell is empty
- **AND** the row is still written

#### Scenario: An identifier column is unpopulated across the whole export

- **WHEN** an export carries an identifier column that is blank on every row
- **THEN** the report states how many datasets have that identifier out of the total
- **AND** it marks the column as empty throughout, so the blank CSV column reads as a known
  fact about the export rather than a defect in the tool

#### Scenario: An identifier column is missing from the export entirely

- **WHEN** the export's header has no `sourceDatasetID` or `gbifDatasetID` column
- **THEN** the scan still completes and leaves that column blank
- **AND** the script says which column was absent

#### Scenario: Existing columns are unchanged

- **WHEN** the per-dataset CSV is written
- **THEN** the columns that existed before this change keep their names, meaning, and values

### Requirement: Single scan produces both outputs

Both the markdown report and the per-dataset CSV SHALL be produced from one pass over the
export. The script SHALL NOT read the export a second time to compute report figures.

#### Scenario: One pass over a full export

- **WHEN** the script runs against a full (~1.85 GB) export
- **THEN** the export is scanned once
- **AND** both the markdown report and the per-dataset CSV are written from that scan's results

### Requirement: Input selection and failure reporting

The script SHALL accept either a zip export or an already-extracted CSV, auto-detecting the zip
when not told which to use, and SHALL fail with a clear message rather than writing partial or
misleading output when the input cannot be resolved.

#### Scenario: Zip is auto-detected

- **WHEN** the script is invoked with neither an explicit zip nor a CSV path
- **THEN** it locates a `tbia_*.zip` export and extracts its CSV if not already extracted

#### Scenario: An extracted CSV is scanned directly

- **WHEN** the script is given a path to an already-extracted CSV
- **THEN** it scans that file without requiring the zip to be present

#### Scenario: No export can be found

- **WHEN** no export zip can be located and no CSV path is given
- **THEN** the script exits with a non-zero status and a message naming what it looked for
- **AND** neither the report nor the CSV is written
