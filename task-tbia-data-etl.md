# TBIA data ETL process

1. read downloaded zip (csv)

2. get tha csv stats
- total rows
- total datasets
- total rightsHolder (listed, with dataset/record counts each)

`scripts/list_tbia_datasets.py` does this in one scan, writing both:
- `data/tbia_export_summary.md` — the stats above + the registry diff
- `data/tbia_datasets.csv` — a row per dataset (tbiaDatasetID, datasetName,
  sourceDatasetID, gbifDatasetID, rightsHolder, bio_groups, n_records, registry status)

3. human check the csv and update the registry.json

4. make a filter that only extract dataset from a json

5. make a duckdb that has extracted dataset
