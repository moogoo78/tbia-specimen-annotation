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
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="contributor")
    pw_hash: Mapped[str] = mapped_column(String(255))
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

    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | ai
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
