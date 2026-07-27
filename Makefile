.PHONY: install backend-install frontend-install prepare ingest ingest-sample seed seed-collectors sync-collectors api web test build clean

PY := backend/.venv/bin/python
PIP := backend/.venv/bin/pip

install: backend-install frontend-install

backend-install:
	python3 -m venv backend/.venv
	$(PIP) install --upgrade pip
	$(PIP) install -r backend/requirements.txt

frontend-install:
	cd frontend && npm install

# Derive the app-facing columns on the ETL's data/tbia.duckdb: completeness
# flags + score + year on `occurrence`, roll-ups on `dataset`, plus indexes.
# Idempotent — run it after every ETL refresh. This is what the API reads.
prepare:
	cd backend && .venv/bin/python -m ingest.prepare

# LEGACY CSV loaders, superseded by the TBIA ETL (task-tbia-data-etl.md) which
# now produces data/tbia.duckdb directly. These still build the old
# data/occurrences.duckdb from a tbia_*.zip, scoped to registry.json — which
# since the GBIF ids moved out of that file means the 13 institution datasets
# only. Point NDB_DUCKDB_PATH at the result if you need the old store.
ingest:
	cd backend && .venv/bin/python -m ingest.ingest_filtered --registry

# Quick dev slice (same registry scope).
ingest-sample:
	cd backend && .venv/bin/python -m ingest.ingest_filtered --registry --limit 50000

# Create the SQLite schema + demo users (curator/reviewer/admin, pw: demo1234).
seed:
	cd backend && .venv/bin/python -m app.seed

# Drain pending AI transcription requests (needs ANTHROPIC_API_KEY). Run on
# demand; it processes what's queued and exits (cron it later if you want).
transcribe:
	cd backend && .venv/bin/python -m app.worker

# Import transcription result JSON produced elsewhere (agent session, a
# contributor's own AI chat) into the annotation store. Dry run by default:
#   make import-results DIR=../results          # preview
#   make import-results DIR=../results COMMIT=1 # write
import-results:
	cd backend && .venv/bin/python -m app.import_results $(DIR) $(if $(COMMIT),--commit,)

# Build the collector table + alias map from recorded_by (run after `make ingest`).
seed-collectors:
	cd backend && .venv/bin/python -m app.seed_collectors

# Incrementally map only NEW recorded_by values after re-ingesting a fresh zip.
sync-collectors:
	cd backend && .venv/bin/python -m app.seed_collectors --sync

# Run the API on :8000 (the Vite dev server proxies /api here).
api:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

# Run the frontend dev server on :5173.
web:
	cd frontend && npm run dev

test:
	cd backend && .venv/bin/python -m pytest -q

build:
	cd frontend && npm run build

clean:
	rm -f data/*.duckdb data/*.sqlite
