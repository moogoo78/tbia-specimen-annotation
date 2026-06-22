# TBIA Specimen Annotation Platform — Build Summary

*How this site was made: the concept, the design, and the you-plus-Claude-Code collaboration.*

## What you're building

**TBIA Specimen Annotation & Feedback Platform** — a collaborative tool tied to the
**TDWG 2026 abstract, *"Closing Gaps in Specimen Metadata."*** The core idea: natural-history
specimen records (from the Taiwan Biodiversity Information Alliance, ~2M occurrences) are often
missing key metadata — taxonomic ID, coordinates, or collection date. The platform lets
contributors **find those gaps**, **fill them** (manually or with AI label transcription), and
**export reviewed enrichments back to the original data providers** as a trackable feedback loop.
It's inspired by Europe's DiSSCover initiative, and aimed especially at smaller institutions that
can image specimens faster than they can transcribe labels.

## The design (the "Claude design")

The architecture is deliberately shaped around one constraint: **occurrence data is read-only;
enrichment lives only as annotations.** That drove the two-store split:

- **DuckDB** — ~2M read-only occurrence rows. Columnar, so faceting and completeness aggregation
  are fast. The product's signature feature is the **completeness score (0–4)** computed at ingest,
  so the default search surfaces the *least*-complete records first (gaps first).
- **SQLite (via SQLAlchemy)** — the writable store for annotations + users.
- **Federated join** — DuckDB `ATTACH`es the SQLite file so dashboard/export queries join
  occurrences ↔ annotations in one SQL pass.
- **FastAPI** backend (JWT auth; contributor/reviewer/admin roles) + **React/Vite/TypeScript**
  frontend, bilingual zh-TW / English, with design tokens ported from a `naturedb-portal` mockup.
- **AI extraction** is currently a stub shaped exactly like a real Claude vision response
  (per-field value + confidence) — a drop-in slot for the real call.

## How you and Claude Code built it (the git story)

The whole thing was built in a compressed window. **June 3, 2026** is the big day:

1. **Initial commit** — the entire platform landed at once (~7,000 lines, 65 files): backend,
   ingest pipeline, full React frontend, tests, Makefile, README, and the CLAUDE.md that documents
   all the architectural reasoning and gotchas (the pbkdf2 hashing quirk, the lifespan ordering for
   the ATTACH, etc.).
2. Then a same-day **deployment iteration sequence**: production Docker setup (multi-stage frontend
   + Caddy) → `DEPLOY.md` → Debian-compatible Docker install fix → **Cloudflare Origin cert TLS
   support** (fixing a 525 error behind the CF proxy).
3. **June 10** — a cleanup pass: `.dockerignore` files and a named volume for the frontend
   `node_modules`.

The division of labor that the repo reflects: **you** set the direction — the scientific goal, the
TBIA data, the real-world deployment problems (the CF 525, Debian Docker quirks) — and **Claude
Code** turned each into working code and documentation, encoding the *why* into CLAUDE.md so future
sessions stay consistent. The Docker-everything approach and multi-stage production builds also
trace straight to your global preferences.

## Where it stands

Functionally complete MVP with tests passing. The flagged **next steps** are: swap the
`extract.py` stub for a real Claude vision call, add Alembic migrations (currently
`metadata.create_all`), and add a real index if ranked fuzzy Chinese search becomes important.
