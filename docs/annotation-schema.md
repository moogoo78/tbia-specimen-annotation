# Annotation Schema

## Form

### 1. 典藏資訊 (Collection)

| label | tbia field name | type | widget | remarks |
| --- | --- | --- | --- | --- |
| 館號 | `catalogNumber` | string | input | |
| 標本類型 | `typeStatus` | string | select, options(HOLOTYPE/ISOTYPE/LECTOTYPE...) | |

### 2. 採集事件 (Sampling Event)

| label | tbia field name | type | widget | remarks |
| --- | --- | --- | --- | --- |
| 採集者 | `recordedBy` | string | input | |
| 採集號 | `recordNumber` | string | input | |
| 採集日期 | `eventDate` | date | `eventYear` / `eventMonth` / `eventDay` 分開 3 格（月份用 dropdown） | 標準化解析日期為 `std_date` |

### 3. 生物分類 (Taxonomy)

| label | tbia field name | type | widget | remarks |
| --- | --- | --- | --- | --- |
| 學名(抄錄) | `annotationScientificName` | string | input | 來源資料庫使用學名 |
| 中文名(抄錄) | `annotationVernacularName` | string | input | 來源資料庫使用中文名 |
| 分類階層 | `taxonRank` | string | select | |

### 4. 地點 (Locality)

| label | tbia field name | type | widget | remarks |
| --- | --- | --- | --- | --- |
| 採集地 | `locality` | string | input | |
| 座標系統 | `verbatimCoordinateSystem` | string | select, options(TWD 67/TWD 97) | |
| 緯度(抄錄) | `verbatimLatitude` | string | input |  |
| 經度(抄錄) | `verbatimLongitude` | string | input |  |
| 經度 (度分秒) | `annotationLongitudeDMS` | float | input | 4欄位 => select, option(東經/西經), input (度, limit: 0-180), input (分, limit: 0-59), input (秒, limit: 0-59) |
| 緯度 (度分秒) | `annotationLatitudeDMS` | float | input | 4欄位 => select, option(北緯/南緯), input (度, limit: 0-90), input (分, limit: 0-59), input (秒, limit: 0-59) |
| 經度 (十進位) | `annotationLongitudeDecimal` | float | input |  |
| 緯度 (十進位) | `annotationLatitudeDecimal` | float | input |  |
| 縣市 | `annotationCounty` | string | input |  |
| 鄉鎮市區 | `annotationMunicipality` | string | input |  |


Note:
- annotation開頭為 tbia 欄位沒有的
- 座標的度分秒, 10進位 可以自動轉換

## Status lifecycle

`STATUSES` (`backend/app/models.py:20`), one-way — there is no path back to `draft`:

```
draft ──> submitted ──> accepted ──> merged
                   └──> rejected
```

- `draft | submitted` = `CONTRIB_STATUSES`; a new annotation must be created in one
  of these two (`POST /occurrences/{id}/annotations` rejects anything else).
- `accepted | rejected | merged` = `REVIEW_STATUSES`; setting any of them stamps
  `reviewed_by` / `reviewed_at` and requires the reviewer role.
- `merged` means the value was handed back to the data provider. Export
  (`/api/export/*`) defaults to `statuses=accepted,merged`.

## Licensing

Every annotation carries the terms its contributor released it under —
`LICENSES` (`backend/app/models.py`), as SPDX identifiers so the *version* is
part of the value:

| id | shown as | |
| --- | --- | --- |
| `CC0-1.0` | CC0 1.0 | public domain dedication |
| `CC-BY-4.0` | CC BY 4.0 | attribution |
| `CC-BY-NC-4.0` | CC BY-NC 4.0 | attribution, non-commercial — **the default** |

The rules follow [iNaturalist's][inat], which is the model most of our
contributors will already have met. Three and no more, because the point of the
platform is handing enrichment back to providers and **GBIF ingests only CC0 /
CC BY / CC BY-NC** — iNat's fourth option, all-rights-reserved, would be a
contribution that could never be delivered.

[inat]: https://help.inaturalist.org/en/support/solutions/articles/151000173511-how-do-licenses-work-on-inaturalist-should-i-change-my-licenses

- **Per annotation, with a per-user default.** `users.default_license` seeds the
  picker (Dashboard → *Default licence for your annotations*); the record form
  applies one choice to every field submitted in a click and may override it for
  that submission alone. The stored value is the grant attached to *that work* —
  a provider export has to state the terms it was written under, and a
  contributor may license one record differently from the next.
- **Changing the default is prospective only.** It decides what new annotations
  start on and touches nothing already contributed — the same split iNat draws
  between a default and a bulk relicense (we have no bulk operation; relicensing
  is per annotation, on the record).
- **An absent licence is the contributor's default, never "none".**
  `AnnotationCreate.license` is optional and resolves server-side to
  `user.default_license`, falling back to `DEFAULT_LICENSE`. The SQLite
  `ADD COLUMN` that brings an existing deployment forward backfills
  `CC-BY-NC-4.0`, so work contributed when the form asked for no terms is read
  conservatively rather than as an open grant. An AI draft
  (`pipeline.build_annotations`) takes the column default: nobody picked for it.
- **Only the contributor may relicense — but at any time, in any status.** A
  reviewer may edit a *value* in any status (that is the job) and may not restate
  someone else's terms; not even an admin inherits that. There is deliberately no
  status past which the licence freezes: what cannot be revoked is the copy a
  provider already took, not the record. Enforced in `PATCH /annotations/{id}`,
  offered in the UI on the contributor's own rows in *Annotation history*.
- The export (`/api/export/provider`) carries `license` and `license_uri` per
  row — the id we store, and the deed URI DwC's `license` term wants. Terms vary
  row by row, so a file cannot be described by one blanket statement. **An export
  is a snapshot**: it states the terms in force when it ran, the delivered file
  keeps them, and a later change shows up in the next export.

## Naming a contributor

Two settings, one rule. `users.show_in_ranking` decides **whether** to name a
contributor and governs **every surface that says who contributed** — not just
the ranking it is named after; `users.public_display_name` decides **as what**.
Both live on the user, both are self-service (`PATCH /api/auth/me`), and the
first is off by default, so a new account is never named without asking.

- **The server withholds the name; it does not ask the UI to hide it.**
  `models.public_name(user)` returns `None` for a user who has not opted in, and
  otherwise `public_display_name or display_name`; every read path calls it: the volunteer ranking
  (`api/volunteers.py`), the dashboard's annotation list and each annotation
  response (`api/annotations.py`), a record's annotation history and its
  transcription queue line (`annotations_store.py`). It matters that this is
  server-side: `GET /api/occurrences/{id}` is unauthenticated and edge-cached,
  so a name left in that payload is published to everyone who asks, whatever
  the page chooses to render.
- **The chosen name is a separate column because `display_name` is ORCID's.**
  The callback overwrites `display_name` from the token response on *every*
  sign-in (`api/auth.py`), so a name edited in place would revert the next time
  its owner signed in. `public_display_name` is null until someone sets one,
  which is why an untouched account is still published exactly as ORCID has it;
  a blank submission clears it back to null rather than storing `""`. Capped at
  60 characters (`api/auth.py:MAX_PUBLIC_NAME`), whitespace collapsed, and
  applied retroactively — it is a name, not a per-annotation byline, so changing
  it renames work already contributed.
- **`contributor_name: null` means "not for publication", never "no
  contributor".** The id always ships (`contributor_id`, `requested_by_id`), and
  `frontend/src/contributors.ts` turns the pair into the same *Unnamed
  contributor #<id>* everywhere — one function, because five separate call sites
  formatting it themselves is how the opt-out came to cover only the ranking.
- **The provider export is deliberately not one of these surfaces.**
  `/api/export/*` ships the ORCID `display_name` unconditionally, honouring
  neither setting. That file is the hand-off to a data provider, where the name
  is the attribution the row's own licence asks for — `CC-BY-4.0` and
  `CC-BY-NC-4.0` both require it, and the contributor chose the licence — and
  the ORCID-verified name is what makes that attribution checkable against an
  iD. A contributor who wants no attribution anywhere releases under `CC0-1.0`.

## Roles and permissions

`ROLES = ("contributor", "reviewer", "admin")` (`backend/app/models.py:21`). Assigned
at first ORCID sign-in: an iD listed in `ORCID_ADMIN_IDS` gets `admin`, everyone else
`contributor` (`backend/app/api/auth.py:89`). The role is read from SQLite on every
request, so a change takes effect immediately.

| Action | contributor | reviewer | admin |
| --- | --- | --- | --- |
| Browse / search / view records | ✅ | ✅ | ✅ |
| AI transcription (request, paste, extract) | ✅ | ✅ | ✅ |
| Create annotation (`draft` / `submitted`) | ✅ | ✅ | ✅ |
| Edit **own** annotation while `draft` / `submitted` | ✅ | ✅ | ✅ |
| Edit **anyone's** annotation, in any status | ❌ | ✅ | ✅ |
| Set the licence on **own** annotation, in any status | ✅ | ✅ | ✅ |
| Set the licence on **anyone else's** | ❌ | ❌ | ❌ |
| Set `accepted` / `rejected` / `merged` | ❌ | ✅ | ✅ |
| Export accepted deltas | ❌ | ✅ | ✅ |

Enforced in exactly two places — `require_role("reviewer")` on export
(`backend/app/api/export.py`) and the `is_reviewer` / `is_owner` branches of
`PATCH /annotations/{id}` (`backend/app/api/annotations.py`), which is also
where the licence rule above lives, as the one edit a reviewer does *not*
inherit. Every other endpoint takes any authenticated user.

Note:
- **`admin` grants one thing beyond `reviewer`: the AI transcription route.**
  `require_role` lets an admin through every gate (`backend/app/auth.py:65`), and
  `PUT /api/transcribe/config` is the one endpoint only they reach — it sets
  `policy.transcribe_route` for the whole system, and under `now` a contributor's
  click spends a vision call inside their own request, so it is a spending
  decision rather than a review one. `POST /occurrences/{id}/transcribe-now`
  follows from it: an admin always, everyone else exactly while that route is
  `now`. There is still no user management and no delete.
- The frontend mirrors the single boundary with
  `isReviewer = role === "reviewer" || role === "admin"` — export button
  (`frontend/src/pages/Dashboard.tsx:35`) and the accept / reject / mark-merged
  controls (`frontend/src/pages/RecordDetail.tsx:395`). It is UI convenience only;
  the API is the authority.
