from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    orcid: str | None = None
    email: str | None = None
    display_name: str
    role: str
    show_in_ranking: bool = False


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ── ORCID OAuth ────────────────────────────────────────────────────────────
class OrcidConfig(BaseModel):
    """Public parameters the frontend needs to build the ORCID authorize URL.
    The client *secret* never leaves the backend."""
    authorize_endpoint: str
    client_id: str
    redirect_uri: str
    scope: str


class OrcidCallback(BaseModel):
    code: str


# ── Dev-only sign-in (NDB_DEV_LOGIN) ───────────────────────────────────────
class DevUser(BaseModel):
    email: str
    display_name: str
    role: str


class DevLoginConfig(BaseModel):
    enabled: bool
    users: list[DevUser]


class DevLoginRequest(BaseModel):
    email: str


class AnnotationCreate(BaseModel):
    field: str
    proposed_value: str | None = None
    original_value: str | None = None
    note: str | None = None
    source: str = "manual"
    ai_confidence: float | None = None
    ai_raw: str | None = None
    status: str = "submitted"  # contributors may save "draft" or "submitted"


class AnnotationUpdate(BaseModel):
    proposed_value: str | None = None
    note: str | None = None
    status: str | None = None  # submit / accept / reject / merge transitions


class AnnotationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    occurrence_id: str
    dataset_name: str | None
    field: str
    original_value: str | None
    proposed_value: str | None
    source: str
    ai_confidence: float | None
    note: str | None
    status: str
    contributor_id: int
    contributor_name: str | None = None
    reviewed_by: int | None
    reviewed_at: datetime | None
    created: datetime
    modified: datetime


# ── AI extraction ──────────────────────────────────────────────────────────
class ExtractedField(BaseModel):
    field: str
    value: str
    confidence: float


class ExtractResponse(BaseModel):
    occurrence_id: str
    # Every image the transcription was made from — a record's media are views
    # of one specimen (sheet, label close-up, determination slip), so they are
    # read together into one set of fields rather than one per image.
    image_urls: list[str] = []
    model: str
    service: str | None = None       # AI service the contributor used (e.g. ChatGPT)
    extracted_at: str | None = None  # date of the extraction (YYYY-MM-DD)
    fields: list[ExtractedField]


# ── AI copy-paste flow ─────────────────────────────────────────────────────
# The platform hands the user a ready prompt (+ image URL) to paste into their
# own AI chat, then parses the JSON they paste back into an ExtractResponse.
class ExtractPromptResponse(BaseModel):
    occurrence_id: str
    image_urls: list[str] = []
    target_fields: list[str]
    prompt: str


class ExtractPaste(BaseModel):
    raw: str


class TranscribeOptions(BaseModel):
    """Per-request pipeline overrides (all optional -> global settings)."""
    mode: str | None = None          # "single" | "two_stage"
    ocr_model: str | None = None     # two_stage stage-1 vision model
    field_model: str | None = None   # primary field model (both modes)


class TranscribeConfig(BaseModel):
    """What the server's "auto" preset actually resolves to, so the UI can name
    the models instead of showing an opaque "Auto". Resolved from the settings at
    request time — a queued request with no overrides picks up whatever these are
    when the worker eventually runs it, not when it was queued."""

    mode: str                  # "single" | "two_stage"
    ocr_model: str | None      # stage-1 vision model (two_stage only)
    field_model: str           # primary field model (both modes)
    # System-wide, admin-set: which route a transcribe click takes for *everyone*
    # ("queue" | "now"). Read by every signed-in user so the AI panel can label
    # the button it is about to run; only an admin may PUT it.
    route: str


class TranscribeConfigUpdate(BaseModel):
    """Admin write to the runtime policy. Only the route is settable — the model
    chain stays deployment config (env), because changing it is a restart-level
    decision, not one made mid-session."""

    route: str                 # "queue" | "now"


class TranscribeRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurrence_id: str
    contributor_id: int
    created: datetime
    notified: bool = False  # whether a Discord ping was actually sent
    # Filled in by the run-now route, which has already processed the request by
    # the time it answers. Queued requests come back pending / 0 — the worker is
    # what moves them, and the record detail is where their outcome shows up.
    status: str = "pending"
    processed_at: datetime | None = None
    error: str | None = None
    n_annotations: int = 0
