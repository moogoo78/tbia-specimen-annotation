from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

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

# Which base a table inherits decides which file it lives in: `Base` is the
# annotation store (user work, backed up), `RefBase` the reference store (seeded,
# disposable). See db.py. Nothing may declare a ForeignKey across the two.
from .db import Base, RefBase

# Annotation workflow states.
STATUSES = ("draft", "submitted", "accepted", "rejected", "merged")
ROLES = ("contributor", "reviewer", "admin")

# Licences a contributor may release their annotation under. Stored as SPDX
# identifiers, which carry the *version* — "CC-BY" without one names four
# incompatible licences, and this value travels to data providers in the export,
# where the ambiguity would be theirs to resolve.
#
# These three and no more because the platform exists to hand enrichment back to
# data providers: GBIF ingests CC0 / CC BY / CC BY-NC and nothing else, so an
# all-rights-reserved annotation — which iNaturalist offers, hosting content for
# its own sake — would be a contribution that could never be delivered.
#
# The default is the most restrictive of the three on purpose, and it is the one
# iNaturalist defaults to: a contributor who never looks at the picker grants the
# least, and widening later is their decision to make rather than one the form
# made silently on their behalf.
LICENSES = ("CC0-1.0", "CC-BY-4.0", "CC-BY-NC-4.0")
DEFAULT_LICENSE = "CC-BY-NC-4.0"

# The canonical deed URI per identifier. DwC's `license` recommends a URI, so
# the export carries both — the id is what the UI and the DB speak, the URI is
# what a provider's own metadata wants. Anything not listed has no URI rather
# than a guessed one.
LICENSE_URIS = {
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-NC-4.0": "https://creativecommons.org/licenses/by-nc/4.0/",
}


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
    # The name ORCID gives us. Refreshed from the token response on **every**
    # sign-in (api/auth.py), so it is theirs to change, not ours — which is why
    # a chosen public name is a separate column rather than an edit to this one.
    display_name: Mapped[str] = mapped_column(String(255))
    # What to publish instead, when the user has picked something. Null means
    # "use `display_name`" — the ORCID name — so an untouched account behaves
    # exactly as before. Only ever read through `public_name`.
    public_display_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="contributor")
    pw_hash: Mapped[str | None] = mapped_column(String(255))
    # Opt-in to being named *anywhere the site says who contributed* — the
    # ranking, the dashboard's annotation list, a record's history, the
    # transcription queue line. Off by default; until a user turns it on every
    # one of those reads "Unnamed contributor #<id>". See `public_name`.
    show_in_ranking: Mapped[bool] = mapped_column(Boolean, default=False)
    # Terms new annotations are created under (LICENSES). A *default*, not a
    # policy: it seeds the picker on each submission and changing it never
    # touches work already contributed, which stays on the terms it was
    # submitted with until its contributor changes it there.
    default_license: Mapped[str] = mapped_column(String(32), default=DEFAULT_LICENSE)
    created: Mapped[datetime] = mapped_column(DateTime, default=_now)

    annotations: Mapped[list["Annotation"]] = relationship(
        back_populates="contributor", foreign_keys="Annotation.contributor_id"
    )


class _Nameable(Protocol):
    """A `User`, or any query row carrying the three columns the rule reads."""

    display_name: str
    public_display_name: str | None
    show_in_ranking: bool


def public_name(user: _Nameable | None) -> str | None:
    """The name to publish for a contributor, or None if they have not opted in.

    One rule for every surface that says who contributed — the volunteer
    ranking, the dashboard's annotation list, a record's annotation history,
    the transcription queue line. Each of those used to read `display_name`
    directly, so opting out of the ranking left the name on show everywhere
    else. None means "not for publication": the caller already carries
    `contributor_id`, and the UI renders "Unnamed contributor #<id>" from it.

    Opting in publishes `public_display_name` when the user has set one, and
    their ORCID `display_name` when they have not — two questions, asked
    separately because they are separate: *whether* to be named, and *as what*.
    An account that never answers the second is named exactly as ORCID has it.

    The provider export is deliberately *not* one of these surfaces
    (`api/export.py` ships `display_name` unconditionally): CC-BY attribution
    is a licence term the contributor themselves chose, not site chrome, and it
    is the ORCID-verified name that makes the attribution checkable.
    """
    if user is None or not user.show_in_ranking:
        return None
    return user.public_display_name or user.display_name


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

    # How this value came to be: typed by hand, kept from an AI proposal
    # verbatim, or an AI proposal the contributor edited. Nothing but a person
    # submitting the form writes a row here at all — an AI run produces a
    # *proposal* (TranscribeRequest.result_json), never a contribution.
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | ai | mixed
    # What the AI proposed for this field, and how sure it was, when the value
    # was seeded from a proposal. `ai_value` is kept even when it equals
    # `proposed_value`, because "the human agreed" and "no AI was involved" are
    # different facts: with `source`, `ai_value != proposed_value` is the record
    # of what a person corrected, which is the only way to measure how well the
    # transcription actually reads a label. Null on a manual row.
    ai_value: Mapped[str | None] = mapped_column(Text)
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    # Which model said it (the chain, for two-stage), so accuracy can be read
    # per model rather than as one undifferentiated average.
    ai_model: Mapped[str | None] = mapped_column(String(128))
    ai_raw: Mapped[str | None] = mapped_column(Text)  # JSON payload from extractor

    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="submitted", index=True)

    # The terms this contribution is released under (see LICENSES above). Chosen
    # per annotation rather than per user, because it is a grant attached to the
    # work, not a profile preference: a row exported to a provider has to state
    # the terms that were in force when it was written.
    license: Mapped[str] = mapped_column(String(32), default=DEFAULT_LICENSE)

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
    """A contributor scheduling a record for (AI) transcription — and, once it
    has run, the transcription itself.

    The result lives here rather than in `annotations` because a machine reading
    a label is not a contribution: it is a *proposal* the person who asked for it
    decides about. It reaches them through the record's annotation form, and only
    their submit creates an `Annotation` (which then records what the AI said
    beside what they sent — see `Annotation.ai_value`)."""

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
    # The run's own output: a serialized `schemas.ExtractResponse` (fields +
    # confidences + model + service + the image URLs it actually read). Kept
    # whether or not anyone ever acts on it — an unused transcription is still
    # evidence of what the model reads off a label, and is the corpus a
    # correction rate is measured against. Null while pending, and on a failure.
    result_json: Mapped[str | None] = mapped_column(Text)


class AppSetting(Base):
    """One runtime policy value: set by an admin, applying to everyone.

    ``config.py`` holds the *deployment's* settings — env vars, changed by
    whoever can restart the process. This holds the half an admin changes from
    the UI while it runs. It lives in the annotation store rather than the
    reference store because nothing re-seeds it: on the disposable file, a
    rebuild would silently revert an operator's decision.

    Key/value rather than a column per setting, so adding one is a write rather
    than a migration — there is no Alembic here.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), default="")
    updated: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Collector(RefBase):
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


class CollectorAlias(RefBase):
    """Maps one raw ``recorded_by`` value to a collector (the first listed person).

    Keyed on the raw string -- intrinsic to the occurrence data, not a DuckDB row
    id -- so re-ingesting the TBIA zip never invalidates the mapping."""

    __tablename__ = "collector_alias"

    recorded_by: Mapped[str] = mapped_column(Text, primary_key=True)
    collector_id: Mapped[int] = mapped_column(ForeignKey("collectors.id"), index=True)
    source: Mapped[str] = mapped_column(String(16), default="auto")  # auto | curator

    collector: Mapped[Collector] = relationship(back_populates="aliases")


class SamplingEvent(RefBase):
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


class SamplingEventActor(RefBase):
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
