from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    display_name: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


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


# ── AI extraction stub ─────────────────────────────────────────────────────
class ExtractedField(BaseModel):
    field: str
    value: str
    confidence: float


class ExtractResponse(BaseModel):
    occurrence_id: str
    image_url: str | None
    model: str
    fields: list[ExtractedField]
