# species-browse Specification

## Purpose

Gives the collection a taxonomic index: a browsable, searchable list of every distinct
scientific name the occurrence store holds, with the record counts and coverage behind each
one, so a user can enter the data by taxon rather than only by record, source, person or
expedition.

## Requirements


### Requirement: Species index is reachable from the navbar

The top navigation SHALL include a `Species` entry that opens the species index. The entry
SHALL be highlighted whenever the species index is the active view, following the same
active-tab behavior as the other primary navigation entries.

#### Scenario: Navigating to the index

- **WHEN** a user selects the `Species` navigation entry
- **THEN** the species index is shown and the `Species` entry is marked active

#### Scenario: Available without signing in

- **WHEN** an anonymous visitor opens the species index
- **THEN** the full index is served, since occurrence data is public and read-only

### Requirement: One row per distinct scientific name

The index SHALL list one row per distinct `scientific_name` value in the occurrence store.
Records whose scientific name is absent or empty SHALL be excluded from the index, because
they name no taxon.

Each row SHALL report, for that name: the number of occurrence records, the taxonomic rank,
the family, the genus, the kingdom, a common name where the store carries one, the number of
distinct counties, the earliest and latest collecting year, and the number of records that
are georeferenced, that carry media, and that are type specimens.

#### Scenario: Counts match the store

- **WHEN** a name is listed with a record count of N
- **THEN** N equals the number of occurrence records carrying exactly that `scientific_name`
  value, across every dataset and rank

#### Scenario: Unnamed records are not a row

- **WHEN** the store holds records with a null or empty `scientific_name`
- **THEN** those records appear in no row of the index, and are not grouped under a blank or
  placeholder name

#### Scenario: A name held by one specimen

- **WHEN** a name is carried by exactly one record
- **THEN** it is listed like any other, with a record count of 1 — the singleton tail is the
  index's subject, not noise to be filtered out

### Requirement: Search, sort and paging

The index SHALL support substring search over the scientific name and the common name,
case-insensitively. It SHALL support sorting by record count and by scientific name, in both
directions, and SHALL be paged with a caller-supplied limit and offset. The response SHALL
report the total number of names matching the current search so the caller can render the
result size and page count.

#### Scenario: Substring search

- **WHEN** a user searches `bego`
- **THEN** every name whose scientific or common name contains that substring, in any case,
  is returned, and the reported total counts only those names

#### Scenario: Default ordering

- **WHEN** the index is opened with no sort specified
- **THEN** names are ordered by record count, most records first, so the names carrying the
  collection appear without scrolling

#### Scenario: Paging is stable

- **WHEN** a user pages through the index without changing the search or sort
- **THEN** each name appears exactly once across the pages, with no name skipped or repeated

### Requirement: Rank scope is user-controlled

The index SHALL default to names identified at species rank or below, and SHALL offer a
control that widens it to every rank present in the store, including genus- and family-level
identifications. The active scope SHALL be reflected in the reported total.

#### Scenario: Default scope

- **WHEN** the index is opened with no scope specified
- **THEN** only names at species rank or below are listed

#### Scenario: Widened scope

- **WHEN** the user widens the scope to all ranks
- **THEN** genus-level and family-level identifications are listed alongside the species,
  each showing its own rank, so the coarse identifications are visible as the
  identification gap they represent

### Requirement: Rows link to their records

Selecting a name SHALL open the record search filtered to exactly that scientific name. The
resulting record count SHALL equal the count shown on the species row.

#### Scenario: Exact name, not substring

- **WHEN** a user opens the records for `Begonia`
- **THEN** the result contains only records whose `scientific_name` is exactly `Begonia`,
  excluding `Begonia formosana`, `Begoniaceae`, and records that merely mention the string
  in a locality or dataset name

#### Scenario: Count agrees with the index

- **WHEN** a species row reports N records and the user opens its records
- **THEN** the record search reports the same N, with no filter applied that the species row
  did not account for

### Requirement: A name is a string in the data, not a resolved taxon

The index SHALL present the store's scientific names verbatim. The system SHALL NOT
reconcile them against an external checklist, resolve synonyms, merge orthographic or
gender variants, or assert that a listed name is currently accepted.

#### Scenario: Variants stay separate

- **WHEN** the store holds both `Trema orientalis` and `Trema orientale`
- **THEN** both are listed as separate rows with their own counts, and neither is silently
  merged into or relabelled as the other

#### Scenario: Cross-kingdom homonyms

- **WHEN** one name string is used under more than one kingdom (21 such names in the current
  store)
- **THEN** it is listed as a single row whose counts cover every record carrying that string,
  and the row does not claim the name denotes a single taxon

### Requirement: Derived from the store, never persisted

The index SHALL be derived from the occurrence store rather than stored as its own table, so
that rebuilding the store cannot leave it stale and no ingest or seeding step is required to
keep it correct. Any caching SHALL be internal and time-bounded.

#### Scenario: Store rebuild

- **WHEN** the occurrence store is rebuilt from a new export
- **THEN** the index reflects the new store's names and counts with no migration, no seeding
  command, and no manual invalidation beyond the cache's own expiry

#### Scenario: Repeated requests are cheap

- **WHEN** a user pages or re-sorts the index
- **THEN** the response is served without re-scanning the full occurrence store for each
  request

### Requirement: Bilingual chrome, source-language data

The index's labels, controls and column headers SHALL be available in both English and
zh-TW. Taxonomic values and vernacular names SHALL be shown as the store holds them and
SHALL NOT be translated.

#### Scenario: Language switch

- **WHEN** a user switches the interface language
- **THEN** the headers and controls change language while the scientific names, families and
  common names are unchanged
