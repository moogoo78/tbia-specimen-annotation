# occurrence-store-build Specification

## Purpose

Builds the read-only occurrence store the platform serves from, out of a downloaded TBIA export and
the curated `data/registry.json`, so that what gets ingested is decided by one file the operator
controls.

## Requirements

### Requirement: Registry decides what is ingested

The build SHALL keep an export row when its `tbiaDatasetID` is listed under any institution or
aggregator in `data/registry.json`, or when its `rightsHolder` is exactly `GBIF`. All other rows
SHALL be dropped.

#### Scenario: Curated institution row

- **WHEN** a row's `tbiaDatasetID` is listed under `institutions` in `data/registry.json`
- **THEN** the row is written to the store

#### Scenario: GBIF row

- **WHEN** a row's `rightsHolder` is `GBIF` and its `tbiaDatasetID` is listed nowhere in the
  registry
- **THEN** the row is written to the store

#### Scenario: Uncurated non-GBIF row

- **WHEN** a row's `tbiaDatasetID` is absent from the registry and its rights holder is not `GBIF`
- **THEN** the row is not written to the store

#### Scenario: Dataset removed from the registry

- **WHEN** the operator deletes a dataset entry from `data/registry.json` and rebuilds
- **THEN** that dataset's rows are absent from the new store

#### Scenario: Registry missing or unreadable

- **WHEN** `data/registry.json` does not exist or is not valid JSON
- **THEN** the build exits with an error and leaves any existing store untouched

#### Scenario: Same dataset id under two institutions

- **WHEN** one `tbia_dataset_id` appears under more than one institution or aggregator
- **THEN** the build exits with an error naming the duplicated id, rather than picking one

### Requirement: Occurrence table mirrors the export columns

The `occurrence` table SHALL contain one column for every column of the source CSV, named by
snake-casing the CSV's header (`tbiaDatasetID` → `tbia_dataset_id`, `verbatimSRS` →
`verbatim_srs`). No CSV column SHALL be dropped, and no column SHALL be renamed beyond that
mechanical transformation.

#### Scenario: New column accepted into the baseline

- **WHEN** TBIA adds a column to the export and the operator records it in the column baseline
- **THEN** the rebuilt store carries it, without the projection having to be edited column by column

#### Scenario: Columns colliding with SQL keywords

- **WHEN** the export carries `class`, `order` or `references`
- **THEN** those columns exist in `occurrence` under exactly those names

#### Scenario: Typed columns

- **WHEN** the store is queried
- **THEN** `standard_latitude`, `standard_longitude`, `standard_organism_quantity`,
  `standard_raw_latitude` and `standard_raw_longitude` are DOUBLE; `created`, `modified`,
  `standard_date`, `source_created` and `source_modified` are TIMESTAMP; `data_generalizations` and
  `match_higher_taxon` are BOOLEAN; every other column is VARCHAR

#### Scenario: Unparseable value in a typed column

- **WHEN** a row carries a coordinate or date the cast cannot parse
- **THEN** that field is NULL for that row and the row is still ingested

### Requirement: A changed export column set stops the build

The build SHALL compare the export's column set against a recorded baseline before loading any
rows, and SHALL abort when they differ. The baseline is the checked-in column manifest when one
exists; otherwise the existing store's `occurrence` columns; otherwise the export itself, recorded
as the baseline for later builds.

#### Scenario: Column added to the export

- **WHEN** the export carries a column the baseline does not
- **THEN** the build aborts before loading, naming the added column

#### Scenario: Column removed from the export

- **WHEN** the baseline lists a column the export does not carry
- **THEN** the build aborts before loading, naming the missing column

#### Scenario: Column renamed in the export

- **WHEN** a column the platform reads is renamed upstream
- **THEN** the build aborts, reporting it as one added and one removed column

#### Scenario: Aborting leaves the store alone

- **WHEN** the build aborts on a column difference
- **THEN** no store is written and any existing store at the target path is left intact and
  servable

#### Scenario: Column order changed

- **WHEN** the export carries the same columns in a different order
- **THEN** the build proceeds, because columns are matched by name

#### Scenario: Operator accepts the change

- **WHEN** the operator edits the column manifest to match the new export and re-runs the build
- **THEN** the build proceeds

#### Scenario: Baseline from the existing store

- **WHEN** no column manifest exists but a store does
- **THEN** the export is compared against that store's `occurrence` columns, disregarding the
  columns the build and the prepare step add themselves

#### Scenario: First build on a fresh checkout

- **WHEN** neither a manifest nor a store exists
- **THEN** the build records the export's columns as the baseline, reports that it did so, and
  proceeds

### Requirement: Registry attribution on every occurrence row

The build SHALL add `institution_code`, `institution_name`, `dataset_code` and `groups` to
`occurrence`, resolved from `data/registry.json` for curated rows.

#### Scenario: Curated row attribution

- **WHEN** a row belongs to a dataset curated under institution `NMNS`
- **THEN** its `institution_code` is `NMNS`, its `institution_name` is that institution's `name`,
  and `dataset_code` and `groups` carry the dataset's curated values

#### Scenario: Uncurated GBIF row attribution

- **WHEN** a row is kept only because its rights holder is `GBIF`
- **THEN** its `institution_code` and `institution_name` are both `GBIF`, and `dataset_code` and
  `groups` are NULL

#### Scenario: Groups are a list

- **WHEN** a curated dataset lists several `groups`
- **THEN** `groups` is a list-typed column holding them all, not a delimited string

### Requirement: Dataset table derived from the ingested rows

The build SHALL create a `dataset` table with one row per `tbia_dataset_id` present in
`occurrence`, carrying `dataset_name`, `source_dataset_id`, `gbif_dataset_id`, `rights_holder`,
`institution_code`, `institution_name`, `dataset_code`, `groups`, `in_registry`, `num_of_rows` and
`n_source_dataset_ids`.

#### Scenario: Row counts

- **WHEN** `dataset.num_of_rows` is summed across all datasets
- **THEN** the total equals the number of rows in `occurrence`

#### Scenario: Curated flag

- **WHEN** a dataset's id is listed in `data/registry.json`
- **THEN** its `in_registry` is true; for a dataset kept only via the GBIF rule it is false

#### Scenario: Dataset spanning several source ids

- **WHEN** one `tbia_dataset_id` carries rows with more than one distinct `source_dataset_id`
- **THEN** `n_source_dataset_ids` reports that count, and `source_dataset_id` holds one of the
  observed values

#### Scenario: Completeness roll-up columns are not populated here

- **WHEN** the build finishes
- **THEN** the completeness roll-ups (`n_identified`, `n_georeferenced`, `n_dated`, `n_with_media`,
  `avg_completeness`) are absent from `dataset`, because deriving them is the prepare step's job

### Requirement: Build reports what it did

The build SHALL report, on completion, the per-institution row and dataset counts, the total row
count, and any registry dataset that matched no row in the export.

#### Scenario: Unmatched registry dataset

- **WHEN** a dataset curated in `data/registry.json` matches no row of the export
- **THEN** the build reports it by institution code and id, and still completes

#### Scenario: Next step is stated

- **WHEN** the build completes
- **THEN** it tells the operator that the store is not yet servable and that the prepare step must
  be run against it

### Requirement: The store is not servable until prepared

The build SHALL NOT derive the completeness flags, `year`, `completeness_score` or the query
indexes; those remain the prepare step's responsibility, run as a separate command against the
built store.

#### Scenario: Freshly built store

- **WHEN** the build has completed and the prepare step has not been run
- **THEN** `occurrence` has no `has_identification` / `has_coordinates` / `has_date` / `has_media` /
  `completeness_score` / `year` columns

#### Scenario: After preparing

- **WHEN** the prepare step is run against the built store
- **THEN** those columns and the per-dataset completeness roll-ups exist, and the API serves queries
  against the store

### Requirement: Rebuilds replace the store wholesale

The build SHALL produce a complete store from the export alone, so that a rebuild never merges into
or inherits from a previous store.

#### Scenario: Rebuilding over an existing file

- **WHEN** the build is pointed at a path where a store already exists
- **THEN** the resulting `occurrence` and `dataset` tables reflect only the current export and
  registry, with no rows carried over from the previous build

#### Scenario: Building to a side path

- **WHEN** the operator asks for the store at a path other than the default `data/tbia.duckdb`
- **THEN** it is written there, leaving the live store in place
