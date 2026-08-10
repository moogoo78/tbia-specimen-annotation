# sampling-event-reference Specification

## Purpose

Holds a curated, Darwin Core–shaped chronology of historical collecting events, so a collector's
work can be explored from the documented expedition downward rather than only from their specimen
rows upward.

## Requirements

### Requirement: Curated reference source

The chronology SHALL live in `data/sampling_events.json`, tracked in git and editable by hand. The
system SHALL NOT extract sampling events from images at request time.

#### Scenario: Transcription is a one-off

- **WHEN** the reference data is built from `tmp/sampling-event/*.png`
- **THEN** the transcription runs once, its output is committed to `data/sampling_events.json`, and
  serving the data never re-reads the scans

#### Scenario: Hand correction

- **WHEN** a curator corrects a mis-transcribed locality or date in `data/sampling_events.json` and
  re-runs the seeder
- **THEN** the corrected value is served, with no reprocessing of any image

#### Scenario: Source citation is per-row

- **WHEN** an event is stored
- **THEN** it carries its own `location_according_to` (`許建昌, 1975; 黃增泉, 1983, 1986` for every
  row of this chronology) rather than the citation being fixed in code

### Requirement: Darwin Core event fields

Each sampling event SHALL record `event_date`, `verbatim_event_date`, `verbatim_locality`,
`event_remarks` and `location_according_to`, mapping to the DwC terms `eventDate`,
`verbatimEventDate`, `verbatimLocality`, `eventRemarks` and `locationAccordingTo`. `event_remarks`
SHALL carry the chronology's 標本存放處 (specimen repository) column.

#### Scenario: Single year

- **WHEN** the chronology gives 年代 as `1854`
- **THEN** `event_date` is `1854`, `year_start` and `year_end` are both `1854`, and
  `verbatim_event_date` preserves the original string

#### Scenario: Year range

- **WHEN** 年代 is `1861-1866`
- **THEN** `event_date` is the ISO 8601 interval `1861/1866`, `year_start` is `1861`, `year_end` is
  `1866`, and `verbatim_event_date` is `1861-1866`

#### Scenario: Abbreviated range

- **WHEN** 年代 is written with an elided century, such as `1960-62`
- **THEN** it expands to `year_start` `1960` / `year_end` `1962`, and `verbatim_event_date` keeps
  `1960-62`

#### Scenario: Range derived from the verbatim cell

- **WHEN** a hand-added row carries a parseable 年代 cell but omits `year_start` / `year_end`
- **THEN** the range is derived from that cell rather than the row being rejected

#### Scenario: Year pair contradicts its own cell

- **WHEN** a row's `year_start` / `year_end` disagree with the 年代 cell they were transcribed from
- **THEN** seeding fails naming both the implied and the stated range, so a typo cannot reach the store

#### Scenario: Repository recorded

- **WHEN** the 標本存放處 column reads `台北帝大植物系標本館`
- **THEN** that value is stored verbatim in `event_remarks` and served unchanged, in Chinese

#### Scenario: Narrative preserved

- **WHEN** the 主要記事 column carries prose beyond the localities
- **THEN** the full text is retained verbatim on the event, distinct from `verbatim_locality`, so
  nothing in the source is lost to the locality extraction

#### Scenario: Empty column

- **WHEN** a chronology row leaves 標本存放處 or the localities blank
- **THEN** the corresponding field is empty rather than guessed, and the event is still stored

### Requirement: Multi-participant events

A sampling event SHALL support any number of participants, each stored as a verbatim
`recorded_by` name with a stable position, so a collecting party is not flattened into one string.

#### Scenario: Expedition party

- **WHEN** the 1905–1908 entry names fifteen participants
- **THEN** fifteen actor rows are stored, each with its own `recorded_by`, in the order the source
  lists them

#### Scenario: Two collectors, two nationalities

- **WHEN** an entry names 松村任三 (日) and V. Faurie (英)
- **THEN** each actor keeps its own nationality rather than the event carrying a single one

#### Scenario: Lone collector

- **WHEN** an entry names one person
- **THEN** exactly one actor row is stored

### Requirement: Actors resolve to collectors

Seeding SHALL attempt to match each actor's `recorded_by` against the existing collector records
(`Collector.name`, `Collector.name_en`, `CollectorAlias.recorded_by`) and store a nullable
`collector_id`. An unmatched actor SHALL be kept.

#### Scenario: Known collector

- **WHEN** an actor's name matches a collector already seeded from the occurrence store
- **THEN** `collector_id` is set, and the event appears on that collector's career response

#### Scenario: Collector absent from the export

- **WHEN** a 19th-century botanist in the chronology holds no records in the TBIA export
- **THEN** the actor is stored with `collector_id` null and the name intact, and the event is still
  browsable — the absence is not a reason to drop the row

#### Scenario: Seed reports coverage

- **WHEN** seeding finishes
- **THEN** it reports how many actors resolved and lists the unmatched names, so curation has
  something to work from

#### Scenario: Re-seeding is idempotent

- **WHEN** the seeder is run twice against the same JSON
- **THEN** the resulting tables are identical, with no duplicated events or actors

#### Scenario: Survives a store rebuild

- **WHEN** the DuckDB occurrence store is rebuilt from a fresh TBIA export
- **THEN** the sampling-event tables are untouched, matching how collectors and annotations behave

### Requirement: Browse the chronology

The system SHALL serve the chronology in chronological order, filterable by free text, year range
and collector.

#### Scenario: Default order

- **WHEN** the chronology is requested with no filter
- **THEN** events come back ordered by `year_start` ascending, earliest first

#### Scenario: Year range filter

- **WHEN** a year range is supplied
- **THEN** every event whose own span overlaps that range is returned, including one that starts
  before the range and ends inside it

#### Scenario: Collector filter

- **WHEN** a collector is supplied
- **THEN** only events with an actor resolving to that collector are returned

#### Scenario: Free-text filter

- **WHEN** free text is supplied
- **THEN** it matches against participant names, locality, repository and narrative, using the same
  substring/`ILIKE` approach as the rest of the platform (no CJK tokenizer)

#### Scenario: Unknown event

- **WHEN** a single event is requested by an id that does not exist
- **THEN** the response is 404

### Requirement: Reference events on a collector's career

`GET /api/collectors/{id}/career` SHALL additionally return the chronology entries naming that
collector, alongside the trips derived from their records.

#### Scenario: Documented collector

- **WHEN** a collector appears in the chronology
- **THEN** their career response carries those reference events, and the existing `summary`,
  `years` and `trips` keys are unchanged in shape

#### Scenario: Undocumented collector

- **WHEN** a collector appears nowhere in the chronology
- **THEN** the reference list is empty and the rest of the career response is unaffected

#### Scenario: Derived trips stay derived

- **WHEN** a reference event overlaps a derived trip in time
- **THEN** the trip list is not altered, re-labelled, or merged — the two are reported side by side

### Requirement: Provenance is not asserted

The system SHALL NOT record or imply that a specimen belongs to a chronology event. Any pairing
shown SHALL rest only on collector identity and date overlap.

#### Scenario: No occurrence linkage

- **WHEN** a reference event covers 1861–1866 and a collector has records dated 1862
- **THEN** no field on any occurrence or annotation is written to associate them

#### Scenario: Exports unaffected

- **WHEN** enrichment is exported back to data providers
- **THEN** the export contains no sampling-event association, because none was ever asserted

### Requirement: Bilingual chrome, Chinese data

The chronology UI SHALL follow the platform convention: labels in both `en` and `zh`, data values
served as they appear in the source.

#### Scenario: Interface language

- **WHEN** the timeline is viewed in English
- **THEN** column headings and filter labels are English while names, localities and repositories
  remain in Chinese

#### Scenario: Entry links to career

- **WHEN** an entry whose actor resolved to a collector is selected
- **THEN** it links to that collector's career page; an unresolved actor renders as plain text
