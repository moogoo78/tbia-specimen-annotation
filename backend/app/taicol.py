"""TaiCOL (Catalogue of Life in Taiwan) lookups for the identification form.

**Source: a dated TaiCOL release, loaded locally.** ``make seed-taicol`` loads
TaiCOL's taxon export (``TaiCOL_taxon_YYYYMMDD.csv``) into the reference store
(``taicol_taxon``, ``app/seed_taicol.py``); search, the picked record and the
browse tree are all answered from it. That gives the form three things the live
service could not: a type-ahead that does not depend on TaiCOL's undocumented
autocomplete, a tree (the export has every taxon's kingdom…genus), and a real
**release version** — the file's date — for ``nameAccordingTo``.

**Fallback: live TaiCOL**, only while nothing is seeded (a fresh checkout, a
deploy that has not run the seeder). Suggestions then come from the endpoint
TaiCOL's own catalogue page calls (``/get_autocomplete_taxon_by_solr``,
undocumented) and the picked record from the documented ``/v2/taxon?taxon_id=``;
the version is that record's ``updated_at``, the best TaiCOL publishes live.
A failure raises ``TaicolUnavailable`` → 502, and the form falls back to typing.
The tree is local-only.
"""

from __future__ import annotations

import asyncio
import html
import re
import threading
import time
from typing import Any

import httpx
from sqlalchemy import or_, select

from .db import RefSessionLocal
from .models import TaicolRelease, TaicolTaxon

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


async def _remote_suggest(q: str, lang: str = "zh-hant") -> list[dict[str, Any]]:
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


async def _remote_taxon(taxon_id: str) -> dict[str, Any] | None:
    """The picked taxon from live TaiCOL, shaped like `_local_taxon`."""
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
        "path": [],          # the tree is local-only
        "source": "live",
    }
    return _store(key, out)


def according_to(taxon_id: str, version: str) -> str:
    v = f", version {version}" if version else ""
    return f"TaiCOL (Catalogue of Life in Taiwan), {TAXON_URI.format(taxon_id)}{v}"


# ── local release ──────────────────────────────────────────────────────────
# Ranks whose names are italicised (ICN/ICZN: genus and below). Connecting
# terms inside an infraspecific name ("subsp.", "var.", "fo.") stay upright.
_ITALIC_RANKS = {"genus", "subgenus", "section", "subsection", "species", "subspecies",
                 "variety", "form", "special form", "hybrid formula"}
_CONNECTORS = {"subsp.", "var.", "fo.", "f.", "subvar.", "×", "x", "sect.", "subg.", "nothosubsp.", "nothovar."}


def name_parts(name: str, rank: str) -> list[dict[str, Any]]:
    if rank not in _ITALIC_RANKS:
        return [{"text": name, "italic": False}]
    parts: list[dict[str, Any]] = []
    for i, word in enumerate(name.split(" ")):
        italic = word not in _CONNECTORS
        text = (" " if i else "") + word
        if parts and parts[-1]["italic"] == italic:
            parts[-1]["text"] += text
        else:
            parts.append({"text": text, "italic": italic})
    return parts


def release() -> dict[str, Any] | None:
    """The loaded release, or None when nothing is seeded (→ live fallback)."""
    try:
        with RefSessionLocal() as db:
            r = db.execute(select(TaicolRelease)).scalars().first()
    except Exception:  # noqa: BLE001 - table missing on an old store: "not loaded"
        return None
    return None if r is None else {"version": r.version, "source_file": r.source_file, "n_taxa": r.n_taxa}


def _common(t: TaicolTaxon) -> list[str]:
    names = [t.common_name_c] + re.split(r"[,，、]", t.alternative_name_c or "")
    return [n.strip() for n in names if n and n.strip()]


def _node(t: TaicolTaxon) -> dict[str, Any]:
    return {
        "taxon_id": t.taxon_id, "name": t.simple_name, "rank": t.rank,
        "name_parts": name_parts(t.simple_name, t.rank), "common_names": _common(t),
        "family": t.family, "family_c": t.family_c,
        "n_children": t.n_children, "n_species": t.n_species,
    }


def _local_suggest(q: str, limit: int = 20) -> list[dict[str, Any]]:
    ql = q.strip().lower()
    like = ql.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with RefSessionLocal() as db:
        rows = db.execute(
            select(TaicolTaxon)
            .where(TaicolTaxon.search.like(f"%{like}%", escape="\\"))
            .order_by(
                # Exact, then prefix on the Latin name, then exact Chinese name, then
                # anything containing the query; tree ranks before minor ones; shorter first.
                (TaicolTaxon.simple_name == q.strip()).desc(),
                TaicolTaxon.simple_name.like(f"{like}%", escape="\\").desc(),
                (TaicolTaxon.common_name_c == q.strip()).desc(),
                TaicolTaxon.in_tree.desc(),
                TaicolTaxon.simple_name,
            )
            .limit(limit)
        ).scalars().all()
        return [_node(t) for t in rows]


def _path(db, t: TaicolTaxon) -> list[str]:
    """Ancestor ids, root first — so the tree can open onto a picked name."""
    path, pid = [], t.parent_id
    while pid and pid not in path and len(path) < 20:
        path.append(pid)
        parent = db.get(TaicolTaxon, pid)
        pid = parent.parent_id if parent else None
    return list(reversed(path))


def _local_taxon(taxon_id: str, version: str) -> dict[str, Any] | None:
    with RefSessionLocal() as db:
        t = db.get(TaicolTaxon, taxon_id)
        if t is None:
            return None
        return {
            "taxon_id": t.taxon_id, "name_id": t.name_id,
            "scientific_name": t.simple_name, "name_author": t.name_author,
            "taxon_rank": t.rank or None, "kingdom": t.kingdom,
            "common_name_c": t.common_name_c or None, "taxon_status": "accepted",
            "version": version,
            "scientific_name_id": NAME_URI.format(t.name_id) if t.name_id else None,
            "name_according_to": according_to(t.taxon_id, version),
            "taxon_uri": TAXON_URI.format(t.taxon_id),
            "path": _path(db, t),
            "source": "release",
        }


def tree(parent_id: str | None) -> list[dict[str, Any]] | None:
    """Children of a tree node (roots when None). None when nothing is seeded."""
    if release() is None:
        return None
    with RefSessionLocal() as db:
        cond = (TaicolTaxon.parent_id == parent_id) if parent_id else TaicolTaxon.parent_id.is_(None)
        rows = db.execute(
            select(TaicolTaxon).where(TaicolTaxon.in_tree, cond)
            .order_by(TaicolTaxon.n_species.desc() if not parent_id else TaicolTaxon.simple_name)
        ).scalars().all()
        return [_node(t) for t in rows]


async def suggest(q: str, lang: str = "zh-hant") -> list[dict[str, Any]]:
    if len(q.strip()) < 2:
        return []
    if release() is not None:
        return await asyncio.to_thread(_local_suggest, q)
    return await _remote_suggest(q, lang)


async def taxon(taxon_id: str) -> dict[str, Any] | None:
    """The picked taxon, shaped for the form. None when there is no such id."""
    if not _TAXON_ID.match(taxon_id):
        return None
    rel = release()
    if rel is not None:
        return await asyncio.to_thread(_local_taxon, taxon_id, rel["version"])
    return await _remote_taxon(taxon_id)
