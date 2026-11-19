"""TaiCOL (Catalogue of Life in Taiwan) lookups for the identification form.

Two calls, both read-only and both proxied through us rather than made from the
browser, so the page never depends on a third party's CORS policy, responses
are cached in one place, and the upstream quirks below stay in this file:

- **suggest(q)** — partial Latin or Chinese names → accepted taxa. TaiCOL's
  documented API (`api.taicol.tw/v2`) only matches *exact* names, which cannot
  drive a type-ahead, so this uses the endpoint TaiCOL's own catalogue page
  autocompletes with (`/get_autocomplete_taxon_by_solr`). It is undocumented and
  may change; a failure raises `TaicolUnavailable` and the form degrades to a
  plain text field, which is what it was before.
- **taxon(taxon_id)** — the documented `GET /v2/taxon?taxon_id=` for the record
  a person picked: its name id, simple name, author, rank, kingdom, and the date
  TaiCOL last changed it.

**Version.** TaiCOL publishes no release number — there is no version endpoint
and the download page names none. What it does publish is each taxon record's
`updated_at`, and that is the version of the name this identification was made
against, so it is what `name_according_to` carries.
"""

from __future__ import annotations

import html
import re
import threading
import time
from typing import Any

import httpx

SITE = "https://taicol.tw"
API = "https://api.taicol.tw/v2"
TIMEOUT = 8.0
TTL = 6 * 3600  # names change rarely; a day-old suggestion is still right

# Locale-free public URLs (both resolve), so a stored id does not depend on the
# UI language of whoever made the identification.
NAME_URI = SITE + "/name/{}"
TAXON_URI = SITE + "/taxon/{}"
NAME_URI_PREFIX = SITE + "/name/"

_TAXON_ID = re.compile(r"^t\d{7}$")
_CJK = re.compile(r"[㐀-鿿豈-﫿]")


class TaicolUnavailable(RuntimeError):
    """Upstream unreachable or answered something we cannot read."""


_cache: dict[tuple[str, str], tuple[float, Any]] = {}
_lock = threading.Lock()


def _cached(key: tuple[str, str]):
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < TTL:
            return hit[1]
    return None


def _store(key: tuple[str, str], value: Any) -> Any:
    with _lock:
        if len(_cache) > 2000:
            _cache.clear()
        _cache[key] = (time.monotonic(), value)
    return value


async def _get_json(url: str, params: dict[str, str]) -> Any:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True,
                                     headers={"User-Agent": "ISLAND-annotation"}) as c:
            r = await c.get(url, params=params)
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise TaicolUnavailable(f"TaiCOL: {e.__class__.__name__}") from e


def parse_label(text: str) -> dict[str, Any]:
    """Split a suggestion's HTML label into safe parts.

    The label arrives as markup — ``<i>Begonia formosana</i> fo.
    <i>albomaculata</i> 白斑水鴨腳,水鴨腳`` — and is never rendered as HTML here.
    It becomes the Latin name as italic/roman runs (so "fo." stays upright) and
    the Chinese common names after it."""
    runs = [(bool(i), html.unescape(i or r)) for i, r in re.findall(r"<i>(.*?)</i>|([^<]+)", text)]
    plain = "".join(t for _, t in runs)
    m = _CJK.search(plain)
    cut = m.start() if m else len(plain)

    parts, pos = [], 0
    for italic, chunk in runs:
        if pos >= cut:
            break
        piece = chunk[: cut - pos]
        pos += len(chunk)
        if piece:
            parts.append({"text": piece, "italic": italic})
    if parts:  # trailing space before the common names
        parts[-1]["text"] = parts[-1]["text"].rstrip()
    return {
        "name": plain[:cut].strip(),
        "name_parts": [p for p in parts if p["text"]],
        "common_names": [c.strip() for c in plain[cut:].split(",") if c.strip()],
    }


async def suggest(q: str, lang: str = "zh-hant") -> list[dict[str, Any]]:
    q = q.strip()
    if len(q) < 2:
        return []
    key = ("suggest", f"{lang}:{q.lower()}")
    if (hit := _cached(key)) is not None:
        return hit
    data = await _get_json(f"{SITE}/get_autocomplete_taxon_by_solr",
                           {"keyword": q, "from_tree": "false", "lang": lang})
    if not isinstance(data, list):
        raise TaicolUnavailable("TaiCOL: unexpected suggestion payload")
    out = []
    for item in data[:20]:
        tid = str(item.get("id") or "")
        if not _TAXON_ID.match(tid):
            continue
        out.append({"taxon_id": tid, **parse_label(str(item.get("text") or ""))})
    return _store(key, out)


async def taxon(taxon_id: str) -> dict[str, Any] | None:
    """The picked taxon, shaped for the form. None when TaiCOL has no such id."""
    if not _TAXON_ID.match(taxon_id):
        return None
    key = ("taxon", taxon_id)
    if (hit := _cached(key)) is not None:
        return hit
    body = await _get_json(f"{API}/taxon", {"taxon_id": taxon_id})
    rows = (body or {}).get("data") or []
    if not rows:
        return None
    t = rows[0]
    name_id = t.get("name_id")
    version = t.get("updated_at") or ""
    out = {
        "taxon_id": t.get("taxon_id"),
        "name_id": name_id,
        "scientific_name": t.get("simple_name") or "",
        "name_author": t.get("name_author") or "",
        # TaiCOL capitalises ranks ("Species"); the form's vocabulary is DwC's lower case.
        "taxon_rank": (t.get("rank") or "").lower() or None,
        "kingdom": t.get("kingdom"),
        "common_name_c": t.get("common_name_c"),
        "taxon_status": t.get("taxon_status"),
        "version": version,
        # The two DwC terms the identification stores. Built here, once, so
        # the form, the API and the export cannot spell them differently.
        "scientific_name_id": NAME_URI.format(name_id) if name_id else None,
        "name_according_to": according_to(taxon_id, version),
        "taxon_uri": TAXON_URI.format(taxon_id),
    }
    return _store(key, out)


def according_to(taxon_id: str, version: str) -> str:
    v = f", version {version}" if version else ""
    return f"TaiCOL (Catalogue of Life in Taiwan), {TAXON_URI.format(taxon_id)}{v}"
