"""Other sizes of the same image.

The export ships **one** URL per image, and for several sources that URL is a
downscaled derivative: HAST's ``…/S_138530-l.jpg`` is 683x1024, which is enough
to see that a herbarium sheet has a label and not enough to read it. The larger
renditions sit on the same bucket under a different filename suffix (``-x`` at
2048px, ``-o`` at 4096px), and nothing in the export mentions them.

``data/media_variants.json`` is where that knowledge lives — one rule per source,
hand-curated and tracked in git like ``registry.json``, re-read when its mtime
changes. This module is the only thing that reads it, so the pipeline, the API
and the UI cannot disagree about what a size name means.

**A size is a request, never a promise.** ``at_size`` returns the original URL
whenever no rule matches, the size is unknown, or the URL is not in the shape the
rule describes. A record from a source with no rule therefore behaves exactly as
it did before this file existed, and a mis-typed size degrades to the image the
export shipped rather than to a 404.

Which size the AI reads is a **cost** decision, not a quality one, because the
vision API downscales anything past 2576px on the long edge (~3.75MP): ``-x``
lands under that ceiling and is read at full detail, while ``-o`` is scaled back
down to roughly ``-x``'s detail after being paid for in bandwidth. Hence
``settings.ocr_image_size`` (default ``x``) applies to the calls that carry
images, and stage 2 — which is text-only — is unaffected.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger("media")

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "..", "..", "data", "media_variants.json")

_cache: tuple[float, list[dict]] | None = None


def _rules() -> list[dict]:
    """The parsed rules, re-read when the file changes.

    A missing or malformed file is not an error: it means no source has variants,
    which is the same answer this module gave before any rule was written. It is
    logged once per change rather than raised, because a broken config here must
    not take down record pages that only ever needed the export's own URL.
    """
    global _cache
    try:
        mtime = os.path.getmtime(CONFIG_PATH)
    except OSError:
        _cache = None
        return []
    if _cache is None or _cache[0] != mtime:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                doc = json.load(fh)
            rules = [r for r in doc.get("rules", []) if r.get("url_prefix") and r.get("sizes")]
        except (OSError, ValueError) as exc:
            log.warning("media_variants.json unreadable (%s); no variants offered", exc)
            rules = []
        _cache = (mtime, rules)
    return _cache[1]


def _rule_for(url: str) -> dict | None:
    lowered = url.lower()
    for rule in _rules():
        if lowered.startswith(str(rule["url_prefix"]).lower()):
            return rule
    return None


def _parts(url: str, rule: dict) -> tuple[str, str] | None:
    """Split `url` into (stem, suffix) per the rule's pattern, or None when the
    URL does not actually carry one of the rule's suffixes — a same-bucket URL
    in a shape we don't recognise, which must be left alone."""
    pattern = str(rule.get("pattern") or "-{suffix}.jpg")
    for size in rule["sizes"]:
        tail = pattern.replace("{suffix}", str(size["suffix"]))
        if url.lower().endswith(tail.lower()):
            return url[: -len(tail)], str(size["suffix"])
    return None


def at_size(url: str, size: str | None) -> str:
    """`url` rewritten to `size`, or `url` unchanged when that isn't possible.

    Every failure mode lands on the original URL by design: no rule, an unknown
    size, or a filename the rule doesn't describe. The caller gets an image
    either way, which is what lets the pipeline ask for a bigger one
    unconditionally instead of branching per source."""
    if not size or not url:
        return url
    rule = _rule_for(url)
    if rule is None:
        return url
    if not any(str(s["suffix"]) == size for s in rule["sizes"]):
        return url
    split = _parts(url, rule)
    if split is None:
        return url
    stem, _ = split
    pattern = str(rule.get("pattern") or "-{suffix}.jpg")
    return stem + pattern.replace("{suffix}", size)


def sizes_for(urls: list[str]) -> list[dict[str, Any]]:
    """The size ladder offered for a whole gallery, largest last.

    Per gallery rather than per image because the UI picks one size for the set:
    a control that could leave two images of the same specimen at different
    resolutions would be describing the file layout, not the specimen. Returns
    `[]` unless **every** URL resolves under the same rule — a mixed record falls
    back to the URLs the export shipped.

    Each entry carries `urls` already rewritten, so the frontend never builds an
    image URL itself; `long_edge` travels with it so the picker can say what the
    sizes mean, and `canonical` marks the one the export shipped.
    """
    if not urls:
        return []
    rule = _rule_for(urls[0])
    if rule is None:
        return []
    for url in urls:
        if _rule_for(url) is not rule or _parts(url, rule) is None:
            return []

    canonical = str(rule.get("canonical") or "")
    out: list[dict[str, Any]] = []
    for size in sorted(rule["sizes"], key=lambda s: int(s.get("long_edge") or 0)):
        suffix = str(size["suffix"])
        out.append({
            "size": suffix,
            "long_edge": int(size.get("long_edge") or 0),
            "canonical": suffix == canonical,
            "urls": [at_size(u, suffix) for u in urls],
        })
    return out
