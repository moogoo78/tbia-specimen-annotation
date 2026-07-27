"""AI-assisted label transcription — STUB.

Shaped exactly like a real vision-model call so it can be swapped for a Claude
vision request later (read the specimen image at ``image_url``, return proposed
values for the missing fields with per-field confidence). For now it returns
deterministic mock drafts derived from the record's existing values, only for
the fields that are actually missing.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any

from .schemas import ExtractPromptResponse, ExtractResponse, ExtractedField

STUB_MODEL = "stub-vision-0 (replace with claude vision)"


def _conf(seed: str) -> float:
    """Deterministic pseudo-confidence in [0.70, 0.98] so the UI looks alive."""
    h = int(hashlib.sha1(seed.encode()).hexdigest()[:6], 16)
    return round(0.70 + (h % 28) / 100, 2)


def extract(record: dict) -> ExtractResponse:
    occ_id = record.get("id", "")
    media = record.get("media") or []
    image_url = media[0] if media else None

    fields: list[ExtractedField] = []

    # Identification gap → suggest from any source/original name we have.
    if not record.get("has_identification"):
        guess = record.get("source_scientific_name") or record.get("original_scientific_name")
        if guess:
            fields.append(ExtractedField(
                field="annotationScientificName", value=str(guess), confidence=_conf(occ_id + "sci")))

    # Date gap → surface the raw verbatim eventDate for the contributor to confirm.
    if not record.get("has_date") and record.get("event_date"):
        fields.append(ExtractedField(
            field="eventDate", value=str(record["event_date"]),
            confidence=_conf(occ_id + "date")))

    # Coordinate gap → echo any verbatim coordinates present on the label.
    if not record.get("has_coordinates"):
        vlat = record.get("verbatim_latitude")
        vlon = record.get("verbatim_longitude")
        if vlat and vlon:
            fields.append(ExtractedField(
                field="verbatimLatitude", value=str(vlat), confidence=_conf(occ_id + "lat")))
            fields.append(ExtractedField(
                field="verbatimLongitude", value=str(vlon), confidence=_conf(occ_id + "lon")))
        elif record.get("locality"):
            # No verbatim coords; nudge the user with the locality string.
            fields.append(ExtractedField(
                field="locality", value=str(record["locality"]),
                confidence=_conf(occ_id + "loc")))

    return ExtractResponse(
        occurrence_id=occ_id, image_url=image_url, model=STUB_MODEL, fields=fields,
    )


# ── Copy-paste flow ────────────────────────────────────────────────────────
# Instead of the platform paying for an API vision call, hand the user a ready
# prompt to run in their own AI chat, then parse the JSON they paste back. The
# result is the same ExtractResponse shape the annotation UI already consumes.

# The fields a contributor can annotate (kept in sync with ANNOTATABLE_GROUPS
# in the frontend / docs/annotation-schema.md) plus a one-line description used
# to build the prompt. Only label-transcribable fields are requested — derived
# fields (decimal coords, county/municipality) are computed, not read off a label.
PROMPTABLE_FIELDS: dict[str, str] = {
    # 典藏資訊 (Collection)
    "catalogNumber": "Catalog / accession number (館號) as written on the label",
    "typeStatus": "Type status only if the label states one (e.g. HOLOTYPE, ISOTYPE, PARATYPE); omit otherwise",
    # 採集事件 (Sampling event)
    "recordedBy": "Collector name(s) (採集者) exactly as written",
    "recordNumber": "Collector's field / collection number (採集號)",
    "eventDate": "Collection date in ISO 8601 (YYYY-MM-DD; keep partial dates as written)",
    # 生物分類 (Taxonomy)
    "annotationScientificName": "Full scientific name (genus + species; include author if legible)",
    "annotationVernacularName": "Chinese / common name (中文名) if present on the label",
    "taxonRank": "Taxon rank as written (e.g. species, genus, subspecies)",
    # 地點 (Locality)
    "locality": "Locality / place description exactly as written on the label",
    "verbatimCoordinateSystem": "Coordinate/datum system if stated (e.g. TWD67, TWD97, WGS84)",
    "verbatimLatitude": "Latitude exactly as written on the label (DMS or decimal, any format)",
    "verbatimLongitude": "Longitude exactly as written on the label (DMS or decimal, any format)",
    # 標註專用 (Annotation-only)
    "full_text": (
        "The ENTIRE label transcribed verbatim as one block of text — every "
        "line in reading order, including content that also maps to the fields "
        "above. Preserve the original language and line order."
    ),
}
# Requested on every prompt regardless of which gaps a record has.
ALWAYS_FIELDS = ("full_text",)
PASTE_MODEL = "external (copy-paste)"
MAX_PASTE_FIELDS = 20
MAX_VALUE_LEN = 2000


def _target_fields(record: dict) -> list[str]:
    """The record's gap fields (or all source fields when nothing is missing),
    always followed by the always-on fields (e.g. the full label transcription)."""
    gaps: list[str] = []
    if not record.get("has_identification"):
        gaps += ["annotationScientificName", "annotationVernacularName", "taxonRank"]
    if not record.get("has_date"):
        gaps.append("eventDate")
    if not record.get("has_coordinates"):
        gaps += ["verbatimLatitude", "verbatimLongitude", "verbatimCoordinateSystem", "locality"]
    source = gaps or [f for f in PROMPTABLE_FIELDS if f not in ALWAYS_FIELDS]
    return source + [f for f in ALWAYS_FIELDS if f not in source]


def build_prompt(record: dict) -> ExtractPromptResponse:
    occ_id = record.get("id", "")
    media = record.get("media") or []
    image_url = media[0] if media else None
    fields = _target_fields(record)

    field_lines = "\n".join(f"- {f}: {PROMPTABLE_FIELDS[f]}" for f in fields)
    # Embed the image URL in the prompt so an AI chat can fetch it directly;
    # fall back to "the attached image" when the record has no media.
    image_line = (
        f"Specimen label image (open/fetch this URL and read it): {image_url}\n\n"
        if image_url else
        ""
    )
    source_phrase = "the specimen label image below" if image_url else "the attached image"
    prompt = (
        f"You are transcribing a natural-history specimen label from {source_phrase}.\n"
        f"{image_line}"
        "Read ONLY what is clearly legible — do not guess or infer missing text. "
        "Keep taxonomy and place names in their original language (Chinese or Latin "
        "as written on the label).\n\n"
        "Return STRICT JSON only — no explanation, no markdown code fences — using "
        "exactly this shape, with a confidence from 0.0 to 1.0 per field, and omit "
        "any field you cannot read:\n"
        '{"meta": {"service": "<the AI service you are, e.g. ChatGPT / Claude / Gemini>", '
        '"model": "<your model name and version>", "date": "<today\'s date, YYYY-MM-DD>"}, '
        '"fields": [{"field": "<name>", "value": "<text>", "confidence": 0.0}]}\n\n'
        "In \"meta\", state which AI service and model you are and today's date.\n"
        "Fields to look for (use these exact field names):\n"
        f"{field_lines}"
    )
    return ExtractPromptResponse(
        occurrence_id=occ_id, image_url=image_url, target_fields=fields, prompt=prompt,
    )


def parse_pasted(occ_id: str, raw: str) -> ExtractResponse:
    """Parse the JSON a user pastes back from their AI chat. Defensive: the
    input is untrusted external-model output, so we strip code fences, allow a
    few shapes, keep only known fields, coerce values to strings, and clamp
    confidence. The drafts are still reviewed by the user before submission."""
    payload = _loads_lenient(raw)
    service, model, when = _meta(payload)
    entries = _as_entries(payload)

    fields: list[ExtractedField] = []
    seen: set[str] = set()
    for entry in entries:
        if len(fields) >= MAX_PASTE_FIELDS:
            break
        name = entry.get("field")
        if name not in PROMPTABLE_FIELDS or name in seen:
            continue
        value = entry.get("value")
        if value is None or isinstance(value, (list, dict)):
            continue
        text = str(value).strip()[:MAX_VALUE_LEN]
        if not text:
            continue
        seen.add(name)
        fields.append(ExtractedField(
            field=name, value=text, confidence=_clamp_conf(entry.get("confidence")),
        ))

    if not fields:
        raise ValueError("No usable fields found in the pasted response.")
    return ExtractResponse(
        occurrence_id=occ_id, image_url=None,
        model=model or PASTE_MODEL, service=service, extracted_at=when,
        fields=fields,
    )


def _loads_lenient(raw: str) -> Any:
    text = (raw or "").strip()
    if not text:
        raise ValueError("Pasted response is empty.")
    # Strip a surrounding ```json ... ``` markdown fence if present.
    fence = re.match(r"^```[a-zA-Z]*\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost JSON object/array substring in the pasted text.
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start, end = text.find(open_ch), text.rfind(close_ch)
        if 0 <= start < end:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("Could not parse JSON from the pasted response.")


def _meta(payload: Any) -> tuple[str | None, str | None, str]:
    """Provenance from the optional top-level "meta" block: which AI service and
    model the contributor used, and the date (server date if the model omits it)."""
    meta = payload.get("meta") if isinstance(payload, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    when = _meta_str(meta.get("date")) or date.today().isoformat()
    return _meta_str(meta.get("service")), _meta_str(meta.get("model")), when


def _meta_str(value: Any) -> str | None:
    if value is None or isinstance(value, (list, dict)):
        return None
    text = str(value).strip()[:120]
    return text or None


def _as_entries(payload: Any) -> list[dict]:
    """Normalize the accepted shapes to a list of {field, value, confidence?}."""
    if isinstance(payload, dict):
        if isinstance(payload.get("fields"), list):
            items = payload["fields"]
        else:
            # Accept a flat {field: value} object too.
            return [{"field": k, "value": v} for k, v in payload.items()]
    elif isinstance(payload, list):
        items = payload
    else:
        raise ValueError("Unexpected JSON shape in the pasted response.")
    return [e for e in items if isinstance(e, dict)]


def _clamp_conf(value: Any) -> float:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.0
    if 1.0 < c <= 100.0:  # some models report confidence on a 0–100 scale
        c /= 100.0
    return max(0.0, min(1.0, c))
