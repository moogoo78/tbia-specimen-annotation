"""Cache-Control policy (app/cache.py) and DuckDB admission control (app/duck.py)."""

import pytest

from app import cache
from app.config import settings
from tests.conftest import auth_header


def _cc(client, path, **kw):
    return client.get(path, **kw).headers["cache-control"]


@pytest.mark.parametrize("path", [
    "/api/occurrences",
    "/api/occurrences/facets",
    "/api/registry",
    "/api/species",
    # Path-param routes are the ones that depend on the middleware reading the
    # matched *template* rather than the concrete URL, so cover one of each.
    "/api/occurrences/r1",
    "/api/collectors/1/career",
])
def test_public_reads_are_cacheable(client, path):
    cc = _cc(client, path)
    assert "public" in cc
    assert f"s-maxage={settings.cache_static_ttl}" in cc
    assert f"max-age={settings.cache_browser_ttl}" in cc


@pytest.mark.parametrize("path", [
    "/api/volunteers",
    # A contributor's public work, opened from a board row or a record byline.
    # Its sibling "/api/contributors/{id}" 404s until someone has contributed,
    # and a 404 is never cached — so that one is asserted in test_contributions,
    # where there is a contributor to ask about.
    "/api/contributors/1/annotations",
])
def test_live_tier_gets_the_short_ttl(client, path):
    assert f"s-maxage={settings.cache_live_ttl}" in _cc(client, path)


@pytest.mark.parametrize("path", [
    "/api/health",
    "/api/auth/orcid/config",
    "/api/transcribe/config",
    # A contributor's own view depends on who is asking, so it must never be
    # storable — even though its public sibling above is.
    "/api/annotations/mine",
])
def test_unlisted_routes_are_never_stored(client, path):
    assert _cc(client, path) == cache.PRIVATE


def test_authenticated_requests_are_never_public(client):
    """The same public route, with credentials, must not reach a shared cache —
    otherwise the day one of these grows per-user content it leaks."""
    assert "public" in _cc(client, "/api/occurrences")
    with_token = _cc(client, "/api/occurrences", headers=auth_header(client, "curator@tbia.test"))
    assert with_token == cache.PRIVATE


def test_errors_are_not_cached(client):
    """A 404/500 pinned to the edge would outlive the condition that caused it."""
    assert _cc(client, "/api/occurrences/nope") == cache.PRIVATE
    assert _cc(client, "/api/no-such-endpoint") == cache.PRIVATE


def test_writes_are_not_cached(client):
    res = client.post("/api/occurrences/r1/annotations", json={})
    assert res.headers["cache-control"] == cache.PRIVATE


def test_every_listed_route_exists(client):
    """A rename would otherwise silently drop a route out of the cache tier and
    show up only as unexplained origin load."""
    from app.main import app

    mounted = {r.path for r in app.routes}
    listed = cache.STATIC_ROUTES | cache.LIVE_ROUTES
    assert listed <= mounted, f"listed but not mounted: {sorted(listed - mounted)}"


def test_ttl_of_zero_disables_public_caching(client, monkeypatch):
    monkeypatch.setattr(settings, "cache_static_ttl", 0)
    assert _cc(client, "/api/occurrences") == cache.PRIVATE


# ── admission control ───────────────────────────────────────────────────────

def test_slow_query_is_interrupted(client, monkeypatch):
    """A query past the deadline is cancelled and reported, not left running."""
    from app import duck

    monkeypatch.setattr(settings, "duck_query_timeout", 0.2)
    with pytest.raises(duck.DuckTimeout):
        duck._run("SELECT count(*) FROM range(200000000000) t(i)", None)


@pytest.mark.parametrize("exc,status", [("DuckOverloaded", 503), ("DuckTimeout", 504)])
def test_shedding_surfaces_as_a_response(client, monkeypatch, exc, status):
    from app import duck

    async def raise_it(sql, params=None):
        raise getattr(duck, exc)("shed")

    monkeypatch.setattr(duck, "query", raise_it)
    res = client.get("/api/occurrences")
    assert res.status_code == status
    # Never cached — the edge would otherwise hold the failure past its cause.
    assert res.headers["cache-control"] == cache.PRIVATE
    if status == 503:
        assert res.headers["Retry-After"] == "30"


def test_no_slot_sheds_load_with_retry_after(client, monkeypatch):
    """With every slot taken, a request fails fast with backoff advice rather
    than queueing behind work the box cannot get through."""
    from app import duck

    monkeypatch.setattr(settings, "duck_max_concurrency", 1)
    monkeypatch.setattr(settings, "duck_queue_timeout", 0.05)
    duck._limiters.clear()  # rebuild the limiter at the patched size

    async def hog():
        # Hold the only token for longer than the queue timeout.
        limiter = duck._limiter()
        async with limiter:
            import anyio
            await anyio.sleep(0.4)

    import anyio

    async def scenario():
        async with anyio.create_task_group() as tg:
            tg.start_soon(hog)
            await anyio.sleep(0.05)
            with pytest.raises(duck.DuckOverloaded):
                await duck.query("SELECT 1")

    anyio.run(scenario)
    duck._limiters.clear()
