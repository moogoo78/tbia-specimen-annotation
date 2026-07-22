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
                field="scientificName", value=str(guess), confidence=_conf(occ_id + "sci")))

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
                field="decimalLatitude", value=str(vlat), confidence=_conf(occ_id + "lat")))
            fields.append(ExtractedField(
                field="decimalLongitude", value=str(vlon), confidence=_conf(occ_id + "lon")))
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

# The fields a contributor can annotate (kept in sync with ANNOTATABLE in the
# frontend) plus a one-line description used to build the prompt.
PROMPTABLE_FIELDS: dict[str, str] = {
    "scientificName": "Full scientific name (genus + species; include author if legible)",
    "taxonRank": "Taxon rank as written (e.g. species, genus, subspecies)",
    "eventDate": "Collection date in ISO 8601 (YYYY-MM-DD; keep partial dates as written)",
    "decimalLatitude": "Latitude in decimal degrees",
    "decimalLongitude": "Longitude in decimal degrees",
    "locality": "Locality / place description exactly as written on the label",
}
PASTE_MODEL = "external (copy-paste)"
MAX_PASTE_FIELDS = 20
MAX_VALUE_LEN = 2000


def _target_fields(record: dict) -> list[str]:
    """Which fields to ask for — the record's gaps, or all promptable fields
    when nothing is flagged missing (so the button is always useful)."""
    fields: list[str] = []
    if not record.get("has_identification"):
        fields += ["scientificName", "taxonRank"]
    if not record.get("has_date"):
        fields.append("eventDate")
    if not record.get("has_coordinates"):
        fields += ["decimalLatitude", "decimalLongitude", "locality"]
    return fields or list(PROMPTABLE_FIELDS)


def build_prompt(record: dict) -> ExtractPromptResponse:
    occ_id = record.get("id", "")
    media = record.get("media") or []
    image_url = media[0] if media else None
    fields = _target_fields(record)

    field_lines = "\n".join(f"- {f}: {PROMPTABLE_FIELDS[f]}" for f in fields)
    prompt = (
        "You are transcribing a natural-history specimen label from the attached "
        "image.\n"
        "Read ONLY what is clearly legible — do not guess or infer missing text. "
        "Keep taxonomy and place names in their original language (Chinese or Latin "
        "as written on the label).\n\n"
        "Return STRICT JSON only — no explanation, no markdown code fences — using "
        "exactly this shape, with a confidence from 0.0 to 1.0 per field, and omit "
        "any field you cannot read:\n"
        '{"fields": [{"field": "<name>", "value": "<text>", "confidence": 0.0}]}\n\n'
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
    entries = _as_entries(_loads_lenient(raw))

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
        occurrence_id=occ_id, image_url=None, model=PASTE_MODEL, fields=fields,
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
