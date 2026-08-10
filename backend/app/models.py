from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# Annotation workflow states.
STATUSES = ("draft", "submitted", "accepted", "rejected", "merged")
ROLES = ("contributor", "reviewer", "admin")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # ORCID iD (0000-0000-0000-0000) — the stable identity for sign-in.
    orcid: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    # ORCID's /authenticate scope doesn't return an email, and ORCID users have
    # no local password — both are nullable (only legacy/seed rows may set them).
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="contributor")
    pw_hash: Mapped[str | None] = mapped_column(String(255))
    # Opt-in to being named on the public volunteer ranking. Off by default —
    # the board shows "Contributor #<id>" until a user turns this on.
    show_in_ranking: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[datetime] = mapped_column(DateTime, default=_now)

    annotations: Mapped[list["Annotation"]] = relationship(
        back_populates="contributor", foreign_keys="Annotation.contributor_id"
    )


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # TBIA occurrence id (lives in DuckDB; not an FK here).
    occurrence_id: Mapped[str] = mapped_column(String(64), index=True)
    dataset_name: Mapped[str | None] = mapped_column(String(512), index=True)

    # Which DwC field this annotation proposes a value for.
    field: Mapped[str] = mapped_column(String(64))
    original_value: Mapped[str | None] = mapped_column(Text)
    proposed_value: Mapped[str | None] = mapped_column(Text)

    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | ai | mixed
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    ai_raw: Mapped[str | None] = mapped_column(Text)  # JSON payload from extractor

    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="submitted", index=True)

    contributor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    contributor: Mapped[User] = relationship(
        back_populates="annotations", foreign_keys=[contributor_id]
    )

    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)

    created: Mapped[datetime] = mapped_column(DateTime, default=_now)
    modified: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


Index("idx_ann_occ_status", Annotation.occurrence_id, Annotation.status)


class TranscribeRequest(Base):
    """A contributor scheduling a record for (AI) transcription. Deliberately
    minimal — just the TBIA occurrence id and who scheduled it (+ when)."""

    __tablename__ = "transcribe_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(String(64), index=True)
    contributor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created: Mapped[datetime] = mapped_column(DateTime, default=_now)
    # Worker lifecycle: pending -> done | failed.
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error: Mapped[str | None] = mapped_column(Text)
    # Per-request overrides (null -> fall back to the global settings). mode is
    # "single" | "two_stage"; field_model is the primary model in both modes,
    # ocr_model is the stage-1 vision model (two_stage only).
    mode: Mapped[str | None] = mapped_column(String(16))
    ocr_model: Mapped[str | None] = mapped_column(String(64))
    field_model: Mapped[str | None] = mapped_column(String(64))


class Collector(Base):
    """A canonical collector (person). Enrichment over the read-only occurrence
    store: occurrences map in via ``CollectorAlias.recorded_by`` (the raw string),
    so this survives a fresh ``make ingest`` of the DuckDB occurrences."""

    __tablename__ = "collectors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="", index=True)     # 中文
    name_en: Mapped[str] = mapped_column(String(255), default="", index=True)  # romanized
    # Occurrence rows reachable through this collector's aliases (precomputed at
    # seed/sync time so the dropdown can rank/show counts without a 2M-row join).
    n_records: Mapped[int] = mapped_column(Integer, default=0)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[datetime] = mapped_column(DateTime, default=_now)

    aliases: Mapped[list["CollectorAlias"]] = relationship(back_populates="collector")


class CollectorAlias(Base):
    """Maps one raw ``recorded_by`` value to a collector (the first listed person).

    Keyed on the raw string -- intrinsic to the occurrence data, not a DuckDB row
    id -- so re-ingesting the TBIA zip never invalidates the mapping."""

    __tablename__ = "collector_alias"

    recorded_by: Mapped[str] = mapped_column(Text, primary_key=True)
    collector_id: Mapped[int] = mapped_column(ForeignKey("collectors.id"), index=True)
    source: Mapped[str] = mapped_column(String(16), default="auto")  # auto | curator

    collector: Mapped[Collector] = relationship(back_populates="aliases")


class SamplingEvent(Base):
    """One documented collecting event from a published chronology.

    The *upper* half of the platform's two trip concepts. Trips on a collector's
    career page are derived bottom-up by sessionizing occurrence dates
    (``api/collectors.trips_sql``); a sampling event is the top-down counterpart,
    transcribed from the literature, and it knows the things the specimen rows
    cannot say -- why a collector was somewhere and where the material ended up.

    Curated reference data: loaded from ``data/sampling_events.json`` by
    ``app.seed_sampling_events``, never user-submitted, and asserting no link to
    any occurrence row (see the change's proposal -- Non-Goals)."""

    __tablename__ = "sampling_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    # DwC eventDate: a year, or an ISO 8601 interval ("1861/1866").
    event_date: Mapped[str] = mapped_column(String(64), default="")
    # DwC verbatimEventDate: the 年代 cell exactly as printed ("1960-62").
    verbatim_event_date: Mapped[str] = mapped_column(String(64), default="")
    # Derived from event_date at seed time so range overlap is integer maths.
    year_start: Mapped[int] = mapped_column(Integer, index=True)
    year_end: Mapped[int] = mapped_column(Integer, index=True)
    # DwC verbatimLocality: places pulled out of the 主要記事 column.
    verbatim_locality: Mapped[str] = mapped_column(Text, default="")
    # DwC eventRemarks: the 標本存放處 (specimen repository) column. Free text
    # because the source holds countries ("歐、美、日") as often as institutions.
    event_remarks: Mapped[str] = mapped_column(Text, default="")
    # DwC locationAccordingTo: the chronology's own citation. Per-row, so a
    # second source can be transcribed later without a code change.
    location_according_to: Mapped[str] = mapped_column(Text, default="")
    # The full 主要記事 text. Kept whole so the locality extraction above stays
    # a convenience index over the source rather than a replacement for it.
    narrative: Mapped[str] = mapped_column(Text, default="")
    # Provenance back to the scan, for correcting a transcription by hand.
    source_page: Mapped[int] = mapped_column(Integer, default=0)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[datetime] = mapped_column(DateTime, default=_now)

    actors: Mapped[list["SamplingEventActor"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", order_by="SamplingEventActor.position"
    )


class SamplingEventActor(Base):
    """One participant in a sampling event.

    A separate table because a chronology row is often a party rather than a
    person -- the 1905-1908 entry names fifteen -- and because each participant
    carries their own nationality (1898-1902 pairs 松村任三 (日) with V. Faurie
    (英)) and resolves to its own collector."""

    __tablename__ = "sampling_event_actor"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("sampling_event.id"), index=True)
    # DwC recordedBy, verbatim from 植物分類學者.
    recorded_by: Mapped[str] = mapped_column(String(255), index=True)
    # Null when the name matches no collector -- the expected outcome for most
    # 19th-century botanists, who hold no records in the TBIA export at all.
    collector_id: Mapped[int | None] = mapped_column(
        ForeignKey("collectors.id"), nullable=True, index=True
    )
    nationality: Mapped[str] = mapped_column(String(32), default="")  # 國籍, verbatim
    position: Mapped[int] = mapped_column(Integer, default=0)  # source order

    event: Mapped[SamplingEvent] = relationship(back_populates="actors")
