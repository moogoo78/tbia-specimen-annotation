"""AI transcription pipeline — the batch worker's core.

A contributor schedules a record (``TranscribeRequest``, status ``pending``);
this module drains the queue: for each request it fetches the occurrence, sends
the specimen image + the label-transcription prompt to Claude vision, and stores
what comes back on the request itself (``result_json``). Runs from ``app.worker``
(cron / ``make transcribe``).

**It writes no annotations.** A transcription is a proposal, not a contribution:
it reaches the person who asked for it as prefilled values in the record's
annotation form, and their submit is what creates rows — carrying the AI's own
value alongside theirs, so a correction is recorded rather than lost in the edit.

The transcription itself reuses ``extract.build_prompt`` (the field list the
copy-paste flow already uses) and ``extract.parse_pasted`` (the defensive JSON
parser), so the pipeline and the manual flow stay in lockstep.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import ssl
from datetime import datetime, timezone

import anthropic
import certifi
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import extract, media, search
from .config import settings
from .models import TranscribeRequest
from .schemas import ExtractedField, ExtractResponse

log = logging.getLogger("pipeline")

_OCR_PROMPT = (
    "Transcribe the natural-history specimen label in this image verbatim.\n"
    "Output ONLY the transcribed text — every line in reading order, preserving "
    "the original language (Chinese or Latin as written). Do not translate, "
    "interpret, summarize, or add commentary. Mark unreadable parts as [illegible]."
)

# Stage 1 with several images. They are views of one specimen, so the output is
# one transcript per image in order — stage 2 then reads the lot as a whole.
_OCR_PROMPT_MULTI = (
    "Transcribe the natural-history specimen labels in these {n} images verbatim. "
    "The images all show the SAME specimen from different angles or at different "
    "zoom levels; some may carry no text at all.\n"
    "Output ONLY the transcribed text, one block per image in the order given, "
    "each block starting with its own header line — '--- image 1 ---', "
    "'--- image 2 ---', and so on. Preserve the original "
    "language (Chinese or Latin as written). Do not translate, interpret, "
    "summarize, or add commentary. Mark unreadable parts as [illegible]; write "
    "[no text] for an image that carries none."
)

class MissingAPIKey(RuntimeError):
    """No Anthropic credentials on this deployment. Its own type so a caller can
    tell "the operator has not finished configuring this box" apart from a
    transcription that genuinely failed."""


def _client() -> anthropic.Anthropic:
    """The Anthropic client, with the key passed explicitly.

    Explicitly, because the SDK's own fallback reads ``os.environ`` and nothing
    here calls load_dotenv: the key had to be in the *process* environment,
    while every other setting in this app comes from a .env file. The two
    disagreed exactly where it is most expensive to find out — a host
    ``make transcribe`` and a production container each missing it for a
    different reason.

    The check ahead of it turns the SDK's "Could not resolve authentication
    method. Expected one of api_key, auth_token, or credentials to be set" —
    raised at *request* time, in the middle of a transcription, and surfaced to
    whoever clicked — into a sentence naming what to do about it. It is a
    deployment fault, not a per-record one, but it still fails only this
    request: ``process_one`` records it as the failure reason, exactly as it
    would any other."""
    if not settings.anthropic_api_key:
        raise MissingAPIKey(
            "ANTHROPIC_API_KEY is not set on this deployment, so AI transcription "
            "cannot run. Set it in backend/.env (or the repo-root .env) and restart "
            "the API — under Docker, `up -d backend`, since `restart` does not "
            "re-read env_file."
        )
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def transcribe_record(
    record: dict, *, mode: str | None = None,
    ocr_model: str | None = None, field_model: str | None = None,
) -> ExtractResponse:
    """Read a specimen label into proposed annotation fields. mode/models default
    to the global settings when not overridden. Raises ValueError when the record
    has no image.

    All of the record's images (up to `settings.transcribe_max_images`) go into
    the request together — they are views of one specimen, and the label text is
    often legible in only one of them."""
    image_urls = _image_urls(record)
    mode = mode or settings.transcribe_mode
    field_model = field_model or (settings.anthropic_model if mode == "single" else settings.field_model)
    if mode == "single":
        return _transcribe_single(record, image_urls, field_model)
    return _transcribe_two_stage(record, image_urls, ocr_model or settings.ocr_model, field_model)


def _transcribe_single(record: dict, image_urls: list[str], model: str) -> ExtractResponse:
    """One Claude vision call: OCR + field extraction together. The model sees the
    images while assigning fields, so it can disambiguate hard-to-read values
    against the pixels — and, with several images, cross-check one against
    another (`extract.MERGE_RULE` is what tells it to answer once, not per image).

    Unlike the OCR stage, thinking is left on (the default on current models):
    reading a hard label and mapping it onto Darwin Core fields is the judgement
    this mode exists for. max_tokens is sized to cover thinking *plus* the JSON,
    and effort is capped so that headroom doesn't become the usual spend; it grows
    with the image count because full_text spans every image that carries text."""
    prompt = extract.build_prompt(record).prompt
    client = _client()
    resp = client.messages.create(
        model=model,
        max_tokens=min(8192 + 2048 * (len(image_urls) - 1), 16000),
        output_config={"effort": "medium"},
        messages=[{
            "role": "user",
            "content": [*_image_blocks(image_urls), {"type": "text", "text": prompt}],
        }],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    out = extract.parse_pasted(record.get("id", ""), text)  # validates + clamps
    out.image_urls = image_urls
    out.model = resp.model
    out.service = "anthropic"
    return out


def _transcribe_two_stage(record: dict, image_urls: list[str], ocr_model: str, field_model: str) -> ExtractResponse:
    """Two calls: ocr_model (vision) transcribes the label(s) to verbatim text,
    then field_model (text-only) structures that text into fields. Cheaper — image
    tokens land on the OCR model — but the field model can't re-read the pixels,
    so OCR errors propagate. The verbatim text itself is kept as full_text.

    With several images the OCR stage sees all of them in one call and returns
    one transcript per image; stage 2 reads that as a single document, which is
    what lets a value present on only one image reach the fields."""
    client = _client()
    full_text = _ocr_label(client, image_urls, ocr_model)
    out = _fields_from_text(client, record, full_text, field_model, n_images=len(image_urls))
    if not any(f.field == "full_text" for f in out.fields):
        out.fields.append(ExtractedField(field="full_text", value=full_text, confidence=0.9))
    out.image_urls = image_urls
    out.service = "anthropic (2-stage)"
    out.model = f"{ocr_model} + {field_model}"
    return out


def _ocr_label(client: anthropic.Anthropic, image_urls: list[str], ocr_model: str) -> str:
    """Stage 1 — vision OCR to verbatim label text.

    Thinking is disabled explicitly: this stage only transcribes what is on the
    label, so reasoning buys nothing but billed output tokens — and since
    max_tokens caps thinking *plus* text, a chatty thinking pass on a dense
    bilingual label can crowd out the transcript itself (empty/truncated text ->
    the ValueError below). Some models default to adaptive thinking when the
    parameter is omitted, so leaving it off is not the same as not setting it.
    max_tokens therefore scales with the number of images: one budget sized for a
    single label truncates the moment a second transcript has to fit in it."""
    prompt = _OCR_PROMPT if len(image_urls) == 1 else _OCR_PROMPT_MULTI.format(n=len(image_urls))
    resp = client.messages.create(
        model=ocr_model,
        max_tokens=min(2048 * len(image_urls), 8192),
        thinking={"type": "disabled"},
        messages=[{
            "role": "user",
            "content": [*_image_blocks(image_urls), {"type": "text", "text": prompt}],
        }],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        raise ValueError("OCR stage returned no text")
    return text


def _fields_from_text(
    client: anthropic.Anthropic, record: dict, full_text: str, field_model: str,
    *, n_images: int = 1,
) -> ExtractResponse:
    """Stage 2 — text-only structuring of the OCR transcript into fields.

    Thinking stays on here rather than being disabled as in stage 1: the reply is
    parsed as JSON, and on some models turning thinking off makes stray
    `<thinking>` tags leak into the visible text, which `parse_pasted` would
    choke on. Cost is controlled with low effort instead — the transcript is
    already extracted by this point, so this stage is mostly mapping."""
    fields = [f for f in extract._target_fields(record) if f != "full_text"]
    field_lines = "\n".join(f"- {f}: {extract.PROMPTABLE_FIELDS[f]}" for f in fields)
    merge_rule = (
        "" if n_images == 1 else
        f"The text holds one block per image ('--- image N ---' headers), {n_images} "
        "in all, transcribed from different views of the SAME specimen. Merge them "
        "into ONE set of fields, not one per block: take each value from whichever "
        "block states it most clearly, and prefer a later determination slip over "
        "an older label where they disagree.\n"
    )
    prompt = (
        "You are extracting structured fields from a transcribed natural-history "
        "specimen label.\n\nVerbatim label text:\n---\n"
        f"{full_text}\n---\n\n"
        f"{merge_rule}"
        "Use ONLY what the text supports — do not invent values. Keep taxonomy and "
        "place names in their original language.\n"
        "Return STRICT JSON only — no explanation, no markdown code fences — using "
        "exactly this shape, with a confidence from 0.0 to 1.0 per field, and omit "
        "any field the text does not support:\n"
        '{"fields": [{"field": "<name>", "value": "<text>", "confidence": 0.0}]}\n\n'
        "Fields to extract (use these exact field names):\n"
        f"{field_lines}"
    )
    resp = client.messages.create(
        model=field_model, max_tokens=6144,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    return extract.parse_pasted(record.get("id", ""), text)


def _image_urls(record: dict) -> list[str]:
    """Which images this transcription reads, at the size it reads them.

    `extract.images` decides *which* — the shared definition, so the prompt
    builder, the importer and this module cannot disagree. `media.at_size` then
    asks for the rendition the models should actually see: the export's URL is a
    1024px derivative for HAST, legible as a sheet and not as a label. Sources
    without a rule come back unchanged.

    The rewrite happens here, at the single definition, rather than at the two
    call sites that build image blocks — so `out.image_urls` records the images
    that were really read, and a stored draft points at the same pixels the model
    was looking at."""
    urls = extract.images(record)
    if not urls:
        raise ValueError("record has no image to transcribe")
    return [media.at_size(u, settings.ocr_image_size) for u in urls]


# collections.culture.tw (NMNS, 157k records) presents a CA chain that Python
# 3.13's default strict X.509 check rejects, for a missing Subject Key
# Identifier — a formatting defect in a government CA, not evidence about who we
# are talking to. Chain, expiry and hostname are still verified, here and
# everywhere else; curl and every browser accept the same chain.
_SSL = ssl.create_default_context(cafile=certifi.where())
_SSL.verify_flags &= ~ssl.VERIFY_X509_STRICT


def _image_blocks(image_urls: list[str]) -> list[dict]:
    """One `image` content block per URL, in order, carrying the bytes we read.

    The API takes several in a single user message, and the prompt that follows
    them explains that they are one specimen.

    An `image` block can name a URL for the API to fetch instead, which costs us
    no bandwidth — but it is only as reliable as the least cooperative media
    host, and NMNS's defeats it twice: the export's `ShowGalImage.aspx` URL 302s
    to an extensionless path, and the JPEG comes back labelled
    `Content-Type: image/jpg`, which is not one of the four media types the API
    accepts. Either alone answers with the same opaque
    *"Unable to connect to the remote server"* 400, after the call is billed.

    Fetching here settles both: we follow the redirect, and we say what the
    bytes are rather than repeating what the server claimed. A fetch that fails
    raises, and `process_one` records the real reason on the request — which is
    the point, since the failure it replaces named nothing at all."""
    blocks = []
    with httpx.Client(follow_redirects=True, timeout=30.0, verify=_SSL) as client:
        for url in image_urls:
            data = client.get(url).raise_for_status().content
            blocks.append({"type": "image", "source": {
                "type": "base64",
                # The export is JPEG throughout; PNG is the only other thing a
                # source has any business serving here.
                "media_type": "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg",
                "data": base64.standard_b64encode(data).decode("ascii"),
            }})
    return blocks


async def process_one(db: Session, req: TranscribeRequest) -> int:
    """Transcribe one pending request; returns how many fields it read.

    The result is stored on the request (``result_json``) rather than written out
    as annotations: it is what the model proposes, and the person who asked for
    it decides what to do with it in the annotation form. Storing it whole also
    keeps the fields nobody submits, which a correction rate has to be measured
    against.

    Marks the request done/failed and commits. Never raises — a bad request fails
    just itself, not the batch (and not the HTTP request, on the run-now route).

    The Anthropic SDK is synchronous and a transcription takes tens of seconds,
    so the call goes to a thread: in the worker that costs nothing, and on the
    run-now route it is what keeps one admin's transcription from stalling every
    other request the API is serving."""
    try:
        record = await search.get_detail(req.occurrence_id)
        if record is None:
            raise ValueError("occurrence not found")
        result = await asyncio.to_thread(
            transcribe_record,
            record, mode=req.mode, ocr_model=req.ocr_model, field_model=req.field_model,
        )

        req.result_json = result.model_dump_json()
        req.status = "done"
        req.processed_at = datetime.now(timezone.utc)
        req.error = None
        db.commit()
        return len(result.fields)
    except Exception as exc:  # noqa: BLE001 - isolate one request's failure
        db.rollback()
        req.status = "failed"
        req.processed_at = datetime.now(timezone.utc)
        req.error = str(exc)[:500]
        db.commit()
        log.warning("transcribe request %s failed: %s", req.id, exc)
        return 0


async def process_pending(db: Session, limit: int | None = None) -> dict:
    """Drain up to `limit` pending requests (default settings.transcribe_batch)."""
    limit = limit or settings.transcribe_batch
    pending = db.execute(
        select(TranscribeRequest)
        .where(TranscribeRequest.status == "pending")
        .order_by(TranscribeRequest.created)
        .limit(limit)
    ).scalars().all()

    fields = 0
    done = 0
    for req in pending:
        n = await process_one(db, req)
        fields += n
        if req.status == "done":
            done += 1
    return {
        "requests": len(pending),
        "done": done,
        "failed": len(pending) - done,
        "fields": fields,
    }
