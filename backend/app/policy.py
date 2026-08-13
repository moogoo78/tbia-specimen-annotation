"""Runtime policy an admin sets for the whole system.

The counterpart to ``config.py``: that file is the deployment's settings, read
from the environment and fixed until someone restarts the process. This one is
the handful of decisions an **admin** makes from the UI, at runtime, on behalf
of every user — persisted in ``app_settings`` (annotation store, so it is backed
up and no rebuild reverts it).

**The transcribe route is the system's, not the caller's.** ``queue`` persists
every request for the batch worker; ``now`` makes the click spend the vision
call inside the request that made it — the caller waits tens of seconds and the
API bill lands immediately. Under ``now`` that applies to *every* contributor,
not just the admin who flipped it, which is exactly why the setter is admin-only
and the default is ``queue``.

Reads hit SQLite per request rather than caching: this is a primary-key lookup
on a table with a handful of rows, and a policy that needs a restart or a TTL
to take effect is the thing it replaces. ``endpoints`` read it through
``transcribe_route()`` so the answer the UI is given and the rule the API
enforces come from one place — a UI-only switch would be a suggestion, and the
raw endpoint would still be there to call.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from .models import AppSetting

TRANSCRIBE_ROUTE = "transcribe_route"

# "queue" -> transcribe_requests row + Discord ping, drained by `make transcribe`.
# "now"   -> pipeline.process_one runs inside the request.
ROUTES = ("queue", "now")
DEFAULT_ROUTE = "queue"


def get(db: Session, key: str, default: str = "") -> str:
    row = db.get(AppSetting, key)
    return row.value if row is not None else default


def set_value(db: Session, key: str, value: str, user_id: int | None = None) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key)
        db.add(row)
    row.value = value
    row.updated_by = user_id
    db.commit()


def transcribe_route(db: Session) -> str:
    """Which route a transcribe click takes, for everyone. Falls back to the
    default on an unset *or unrecognised* value: the column is free text, and a
    typo written straight into SQLite should degrade to the cheap route rather
    than to an unbilled 500."""
    value = get(db, TRANSCRIBE_ROUTE, DEFAULT_ROUTE)
    return value if value in ROUTES else DEFAULT_ROUTE


def set_transcribe_route(db: Session, value: str, user_id: int | None = None) -> str:
    if value not in ROUTES:
        raise ValueError(f"route must be one of {ROUTES}")
    set_value(db, TRANSCRIBE_ROUTE, value, user_id)
    return value
