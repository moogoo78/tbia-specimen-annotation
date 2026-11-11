#!/usr/bin/env bash
#
# Pull a consistent snapshot of the PRODUCTION annotation store to this machine.
#
#   scripts/dump-annotations.sh ubuntu@<host> [out-file]
#   make dump-annotations HOST=ubuntu@<host> [OUT=path]
#
# Only data/annotations.sqlite — users, annotations, transcribe_requests,
# app_settings: the one irreplaceable store. tbia.duckdb is rebuilt from the
# export and reference.sqlite from the seeders, so neither is dumped.
#
# How: one ssh session runs `VACUUM INTO` on the box (read-only connection, a
# consistent snapshot even mid-write — never `cp` a live rollback-journal
# SQLite file, see DEPLOY.md) into a temp file, streams it back over stdout,
# and deletes it. Locally the file lands as .partial, is integrity-checked,
# and only then renamed into place, so a dropped connection never leaves a
# truncated file under the final name.
#
# Uses python3's sqlite3 module on both ends, as deploy.sh does, so neither
# machine needs the sqlite3 CLI.
#
# The dump holds personal data (ORCID iDs and names, including contributors
# who have not opted in to being named). Treat it accordingly.
#
# Env overrides:
#   DUMP_HOST      ssh target, if not given as $1
#   DUMP_APP_DIR   checkout on the box, relative to the remote home or
#                  absolute (default: tbia-specimen-annotation)
#   DUMP_OUT_DIR   local directory for the default file name
#                  (default: data/backups/prod — gitignored with /data/*)

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${1:-${DUMP_HOST:-}}"
APP_DIR="${DUMP_APP_DIR:-tbia-specimen-annotation}"
OUT_DIR="${DUMP_OUT_DIR:-$REPO/data/backups/prod}"
OUT="${2:-$OUT_DIR/annotations.prod.$(date -u +%Y%m%dT%H%M%SZ).sqlite}"

log() { printf '%s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

[ -n "$HOST" ] || die "usage: $0 user@host [out-file]   (or set DUMP_HOST)"
[ -e "$OUT" ] && die "$OUT already exists — refusing to overwrite"
# Guard the one local path that must never be clobbered: the dev store.
case "$(realpath -m "$OUT")" in
  "$REPO/data/annotations.sqlite") die "refusing to write over the local dev store" ;;
esac

mkdir -p "$(dirname "$OUT")"
PARTIAL="$OUT.partial"
trap 'rm -f "$PARTIAL"' EXIT

log "snapshotting $HOST:$APP_DIR/data/annotations.sqlite ..."
# The remote script is sent on stdin; the database comes back on stdout.
ssh -o BatchMode=yes "$HOST" bash -s -- "$APP_DIR" >"$PARTIAL" <<'REMOTE'
set -euo pipefail
cd "$1"
SRC=data/annotations.sqlite
[ -f "$SRC" ] || { echo "no $SRC in $PWD" >&2; exit 1; }
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
python3 - "$SRC" "$TMP/dump.sqlite" <<'PY'
import sqlite3, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
con.execute("VACUUM INTO ?", (sys.argv[2],))
con.close()
PY
cat "$TMP/dump.sqlite"
REMOTE

[ -s "$PARTIAL" ] || die "received an empty file"

# Verify before it gets the real name, and print what was captured.
python3 - "$PARTIAL" <<'PY' >&2 || die "integrity check failed — dump discarded"
import sqlite3, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
ok = con.execute("PRAGMA integrity_check").fetchone()[0]
if ok != "ok":
    print(f"integrity_check: {ok}")
    sys.exit(1)
tables = [r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
for t in tables:
    n = con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
    print(f"  {t:<24} {n:>8} rows")
PY

mv "$PARTIAL" "$OUT"
trap - EXIT
log "wrote $OUT ($(du -h "$OUT" | cut -f1))"
