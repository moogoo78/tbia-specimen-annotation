.PHONY: install backend-install frontend-install ingest ingest-sample seed seed-collectors sync-collectors api web test build clean

PY := backend/.venv/bin/python
PIP := backend/.venv/bin/pip

install: backend-install frontend-install

backend-install:
	python3 -m venv backend/.venv
	$(PIP) install --upgrade pip
	$(PIP) install -r backend/requirements.txt

frontend-install:
	cd frontend && npm install

# Load into data/occurrences.duckdb, scoped to exactly the datasets in
# registry.json (auto-detects tbia_*.zip).
ingest:
	cd backend && .venv/bin/python -m ingest.ingest_filtered --registry

# Quick dev slice (same registry scope).
ingest-sample:
	cd backend && .venv/bin/python -m ingest.ingest_filtered --registry --limit 50000

# Create the SQLite schema + demo users (curator/reviewer/admin, pw: demo1234).
seed:
	cd backend && .venv/bin/python -m app.seed

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
