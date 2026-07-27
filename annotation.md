# Annotation Schema

欄位對應以「app 欄位名」(snake_case，見 `backend/ingest/ingest_tbia.py` 的 `COLUMNS`)

採集事件 (Sampling Event)
- 採集者: recorded_by            # TBIA recordedBy
- 採集號: record_number         # TBIA recordNumber
- 採集日期: event_date          # TBIA eventDate（原始值；標準化解析日期為 std_date）

生物分類 (Taxonomy)
- 學名: scientific_name          # TBIA scientificName
- 分類階層: taxon_rank           # TBIA taxonRank

地點 (Locality)
- 詳細地點: locality             # TBIA locality
- 經度 (十進位): std_lon         # TBIA standardLongitude（標準化；來源原值 verbatim_longitude）
- 緯度 (十進位): std_lat         # TBIA standardLatitude（標準化；來源原值 verbatim_latitude）
- 縣市: county                   # TBIA county（鄉鎮市區為 municipality）

典藏資訊
- 館號: catalog_number          # TBIA catalogNumber

標註專用 (Annotation-only；無 TBIA 來源欄位，由貢獻者填寫)
- 標籤全文: full_text            # 影像標籤的完整轉錄文字
- 其他/備註: other              # 自由文字
