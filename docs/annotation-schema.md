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
