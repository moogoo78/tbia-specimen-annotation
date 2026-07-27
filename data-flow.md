# Data Flow

1. downloaded TBIA data
   - `scripts/list_tbia_datasets.py` inventories the export in one scan ->
     `data/tbia_export_summary.md` (rows / datasets / rightsHolders + registry diff)
     and `data/tbia_datasets.csv` (a row per dataset)
2. organization data
   - ignore some dataset that not natural history collection
   - the summary's "not in the registry" list is what needs a decision
3. save to duckdb


