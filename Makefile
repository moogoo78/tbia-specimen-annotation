.PHONY: install backend-install frontend-install prepare inspect build-db seed seed-collectors sync-collectors api web test build clean

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
	cd backend && .venv/bin/python -m ingest.prepare $(if $(DB),--db ../$(DB),)

# Step 1 of a data refresh: summarise a downloaded export and diff it against
# data/registry.json. Read-only — writes <name>-summary.md + <name>-datasets.csv
# next to the export. Read the summary, then edit registry.json by hand.
#   make inspect ZIP=tmp/tbia_xxx.zip
inspect:
	cd backend && .venv/bin/python -m ingest.inspect ../$(ZIP)

# Step 3: load the export into a NEW store, keeping only the datasets
# registry.json lists plus everything rightsHolder=GBIF. Aborts if the export's
# columns moved (see backend/ingest/columns.json). Build to a side path, run
# `make prepare DB=...` on it, then swap it in — a store without completeness
# flags cannot be served.
#   make build-db ZIP=tmp/tbia_xxx.zip DB=data/tbia.new.duckdb
build-db:
	cd backend && .venv/bin/python -m ingest.build --zip ../$(ZIP) \
		$(if $(DB),--db ../$(DB),)

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
