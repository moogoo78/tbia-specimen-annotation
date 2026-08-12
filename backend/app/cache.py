"""``Cache-Control`` policy for the read API.

The occurrence store is read-only between ETL refreshes, so most of what this
API returns is a fixed snapshot that every visitor sees identically — exactly
the thing a CDN exists to hold. Nothing said so, though: no response carried a
``Cache-Control`` header at all, and Cloudflare's default cache is keyed on file
extension, so JSON under ``/api/*`` is a straight bypass. Every facet rollup
reached DuckDB no matter how many times it had just been computed. This module
is what makes putting a CDN in front do anything.

**The policy is an allowlist, and the default is ``no-store``.** A route is
publicly cacheable only by being named below, because the cost of a mistake is
asymmetric: too little caching is a slow page, while wrongly marking a
per-user response ``public`` hands one visitor's data to the next one through a
shared cache. New endpoints therefore start uncached and opt in deliberately.

Two further conditions narrow it, both about not storing what shouldn't be
stored:

* **A request carrying ``Authorization`` never gets a ``public`` response.**
  The listed routes are user-invariant today, so this is belt-and-braces — but
  it means the day one of them grows a "your annotations" field, the leak is
  already closed. Signed-in contributors bypass the edge and hit origin; they
  are a handful of people, while the traffic this protects against is anonymous.
* **Only 200s.** Otherwise an error during a deploy pins itself to the edge for
  an hour, long after the origin is healthy again.

``stale-while-revalidate`` lets the edge serve the old copy while it refetches,
so expiry doesn't send a thundering herd at DuckDB, and ``stale-if-error`` keeps
the site readable if the origin goes down.
"""

from __future__ import annotations

from starlette.requests import Request

from .config import settings

# Cacheable for a long time: pure reads of the occurrence store, or of curated
# data that only a re-seed changes. Values are route *templates* as FastAPI
# holds them, not request paths -- test_cache.py asserts each one still matches
# a mounted route, so a rename shows up as a failure rather than as silent
# uncached traffic.
STATIC_ROUTES = frozenset({
    "/api/registry",
    "/api/datasets",
    "/api/occurrences",
    "/api/occurrences/facets",
    "/api/occurrences/{occ_id}",
    "/api/species",
    "/api/collectors",
    "/api/collectors/resolve",
    "/api/collectors/board",
    "/api/collectors/{collector_id}",
    "/api/collectors/{collector_id}/career",
    "/api/sampling-events",
    "/api/sampling-events/counts",
    "/api/sampling-events/{event_id}",
    "/api/stories",
    "/api/stories/{key}",
})

# Cacheable briefly: correct now, but moves as people annotate. A minute of
# staleness on the leaderboard is invisible; an hour would look broken to
# someone who just had work accepted.
LIVE_ROUTES = frozenset({
    "/api/volunteers",
})

# Everything unlisted -- /api/health, all of /api/auth, the annotation writes and
# their reads, /api/export/provider, the transcribe endpoints -- lands here.
PRIVATE = "private, no-store"


def _public(ttl: int) -> str:
    return (
        f"public, max-age={settings.cache_browser_ttl}, s-maxage={ttl}, "
        f"stale-while-revalidate={ttl}, stale-if-error=86400"
    )


def policy_for(request: Request, status_code: int) -> str:
    """The ``Cache-Control`` value for one response."""
    if request.method not in ("GET", "HEAD"):
        return PRIVATE
    if status_code != 200:
        return PRIVATE
    if request.headers.get("authorization"):
        return PRIVATE
    # Set by the router once it has matched, so this is the declared template
    # ("/api/collectors/{collector_id}") rather than the concrete path. An
    # unmatched request (404) has no route and falls through to PRIVATE.
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if path in STATIC_ROUTES and settings.cache_static_ttl > 0:
        return _public(settings.cache_static_ttl)
    if path in LIVE_ROUTES and settings.cache_live_ttl > 0:
        return _public(settings.cache_live_ttl)
    return PRIVATE


async def cache_control_middleware(request: Request, call_next):
    response = await call_next(request)
    # Unconditional: an endpoint that sets its own header would otherwise be
    # exempt from the allowlist, which is the one thing this must not allow.
    response.headers["Cache-Control"] = policy_for(request, response.status_code)
    return response
