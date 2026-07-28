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
| Set `accepted` / `rejected` / `merged` | ❌ | ✅ | ✅ |
| Export accepted deltas | ❌ | ✅ | ✅ |

Enforced in exactly two places — `require_role("reviewer")` on export
(`backend/app/api/export.py:81`) and the `is_reviewer` branches of
`PATCH /annotations/{id}` (`backend/app/api/annotations.py:152`). Every other
endpoint takes any authenticated user.

Note:
- **`admin` currently grants nothing beyond `reviewer`.** `require_role` lets an
  admin through every gate (`backend/app/auth.py:65`), but no admin-only endpoint
  exists — there is no user management and no delete. Treat it as a reserved
  wildcard for future gates.
- The frontend mirrors the single boundary with
  `isReviewer = role === "reviewer" || role === "admin"` — export button
  (`frontend/src/pages/Dashboard.tsx:35`) and the accept / reject / mark-merged
  controls (`frontend/src/pages/RecordDetail.tsx:395`). It is UI convenience only;
  the API is the authority.
