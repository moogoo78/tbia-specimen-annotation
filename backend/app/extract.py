"""AI-assisted label transcription — STUB.

Shaped exactly like a real vision-model call so it can be swapped for a Claude
vision request later (read the specimen image at ``image_url``, return proposed
values for the missing fields with per-field confidence). For now it returns
deterministic mock drafts derived from the record's existing values, only for
the fields that are actually missing.
"""

from __future__ import annotations

import hashlib

from .schemas import ExtractResponse, ExtractedField

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
