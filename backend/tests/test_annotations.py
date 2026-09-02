from tests.conftest import auth_header

CURATOR = "curator@tbia.test"
REVIEWER = "reviewer@tbia.test"


def test_ai_extract_stub(client):
    h = auth_header(client, CURATOR)
    res = client.post("/api/occurrences/r2/extract", headers=h)
    assert res.status_code == 200
    data = res.json()
    # r2 lacks identification -> stub proposes annotationScientificName from source name
    fields = {f["field"] for f in data["fields"]}
    assert "annotationScientificName" in fields
    assert data["model"]


def test_annotation_lifecycle_and_role_gating(client):
    cur = auth_header(client, CURATOR)
    rev = auth_header(client, REVIEWER)

    # contributor creates an annotation
    create = client.post("/api/occurrences/r2/annotations", headers=cur, json={
        "field": "scientificName", "proposed_value": "Chilodontia laevis",
        "original_value": None, "note": "from label", "status": "submitted",
    })
    assert create.status_code == 200, create.text
    ann_id = create.json()["id"]
    assert create.json()["dataset_name"] == "DS-A"

    # contributor cannot accept (reviewer-only)
    forbidden = client.patch(f"/api/annotations/{ann_id}", headers=cur, json={"status": "accepted"})
    assert forbidden.status_code == 403

    # reviewer accepts
    accept = client.patch(f"/api/annotations/{ann_id}", headers=rev, json={"status": "accepted"})
    assert accept.status_code == 200
    assert accept.json()["status"] == "accepted"
    assert accept.json()["reviewed_by"] is not None

    # appears on the occurrence detail
    detail = client.get("/api/occurrences/r2").json()
    assert any(a["id"] == ann_id and a["status"] == "accepted" for a in detail["annotations"])


def test_a_correction_keeps_what_the_ai_said(client):
    """The point of storing `ai_value`: an edited AI value is the one measurement
    of how well the transcription reads a label, and it is only visible as a pair
    — what the model proposed next to what the person actually sent."""
    cur = auth_header(client, CURATOR)

    corrected = client.post("/api/occurrences/r2/annotations", headers=cur, json={
        "field": "locality", "proposed_value": "野柳", "source": "mixed",
        "ai_value": "野柳村", "ai_confidence": 0.72, "ai_model": "stub-model",
        "status": "submitted",
    }).json()
    assert corrected["source"] == "mixed"
    assert corrected["ai_value"] == "野柳村" and corrected["proposed_value"] == "野柳"
    assert corrected["ai_confidence"] == 0.72 and corrected["ai_model"] == "stub-model"

    # Agreement is stored the same way: `ai_value` equal to the submitted value
    # says a person read it and kept it, which is not the same fact as "no AI".
    kept = client.post("/api/occurrences/r2/annotations", headers=cur, json={
        "field": "recordNumber", "proposed_value": "1234", "source": "ai",
        "ai_value": "1234", "ai_confidence": 0.95, "ai_model": "stub-model",
        "status": "submitted",
    }).json()
    assert kept["source"] == "ai" and kept["ai_value"] == kept["proposed_value"]

    # ...and a typed value carries none of it.
    typed = client.post("/api/occurrences/r2/annotations", headers=cur, json={
        "field": "catalogNumber", "proposed_value": "HAST-1", "status": "submitted",
    }).json()
    assert typed["source"] == "manual"
    assert typed["ai_value"] is None and typed["ai_model"] is None


def test_transcribe_config_reports_resolved_models(client):
    """The "auto" preset sends no overrides, so the UI reads the resolved models
    from here rather than showing an opaque "Auto"."""
    cfg = client.get("/api/transcribe/config")
    assert cfg.status_code == 200, cfg.text
    body = cfg.json()
    assert body["mode"] in ("single", "two_stage")
    assert body["field_model"]
    # two_stage runs an OCR pass first; single does the whole job in one call.
    assert (body["ocr_model"] is not None) == (body["mode"] == "two_stage")


def test_transcribe_request_shows_on_detail(client):
    """The record detail carries the latest queue state, so the UI can show
    "queued / done / failed" after a reload instead of nothing."""
    cur = auth_header(client, CURATOR)
    assert client.get("/api/occurrences/r2").json()["transcribe"] is None

    req = client.post("/api/occurrences/r2/transcribe-request", headers=cur)
    assert req.status_code == 200, req.text

    state = client.get("/api/occurrences/r2").json()["transcribe"]
    assert state["status"] == "pending"
    # Detail is public, and the demo user has not opted in to being named, so
    # the queue line gets the id to render "Unnamed contributor #<id>" from.
    assert state["requested_by"] is None
    assert state["requested_by_id"]
    assert state["processed_at"] is None


def test_contributor_named_only_when_opted_in(client):
    """`users.show_in_ranking` governs every surface that says who contributed,
    not just the ranking. The record detail is unauthenticated and edge-cached,
    so a name left on it there is published to everyone."""
    cur = auth_header(client, CURATOR)
    ann = client.post("/api/occurrences/r2/annotations", headers=cur, json={
        "field": "locality", "proposed_value": "Hualien", "status": "submitted",
    })
    assert ann.status_code == 200, ann.text
    ann_id = ann.json()["id"]

    def named() -> str | None:
        detail = client.get("/api/occurrences/r2").json()
        row = next(a for a in detail["annotations"] if a["id"] == ann_id)
        assert row["contributor_id"]          # the id is never withheld
        return row["contributor_name"]

    assert named() is None                    # off by default
    assert ann.json()["contributor_name"] is None   # and on the create response
    listed = client.get("/api/annotations", headers=cur).json()["items"]
    assert next(a for a in listed if a["id"] == ann_id)["contributor_name"] is None

    client.patch("/api/auth/me", headers=cur, json={"show_in_ranking": True})
    assert named() == "Ada Curator"
    client.patch("/api/auth/me", headers=cur, json={"show_in_ranking": False})
    assert named() is None


def test_contributor_publishes_under_a_chosen_name(client):
    """Being named and being named *as what* are separate settings. The chosen
    name replaces the ORCID one everywhere the site names a contributor —
    including on work already contributed — while the provider export keeps the
    ORCID name, which is what makes the CC-BY attribution checkable."""
    cur = auth_header(client, CURATOR)
    rev = auth_header(client, REVIEWER)
    ann = client.post("/api/occurrences/r2/annotations", headers=cur, json={
        "field": "county", "proposed_value": "花蓮縣", "status": "submitted",
    })
    ann_id = ann.json()["id"]

    def named() -> str | None:
        detail = client.get("/api/occurrences/r2").json()
        return next(a for a in detail["annotations"] if a["id"] == ann_id)["contributor_name"]

    # A chosen name alone publishes nothing — the opt-in still governs.
    me = client.patch("/api/auth/me", headers=cur, json={"public_display_name": "  蘇  阿達 "})
    assert me.status_code == 200, me.text
    assert me.json()["public_display_name"] == "蘇 阿達"   # whitespace collapsed
    assert named() is None

    client.patch("/api/auth/me", headers=cur, json={"show_in_ranking": True})
    assert named() == "蘇 阿達"
    board = client.get("/api/volunteers").json()["items"]
    assert any(v["name"] == "蘇 阿達" for v in board)

    # The provider hand-off is deliberately not one of those surfaces.
    deltas = client.get("/api/export/provider?dataset_name=DS-A", headers=rev).json()["deltas"]
    assert {d["contributor"] for d in deltas} == {"Ada Curator"}

    # Too long is refused rather than silently truncated.
    assert client.patch("/api/auth/me", headers=cur,
                        json={"public_display_name": "x" * 61}).status_code == 400

    # Blank is the way back to the ORCID name, not a nameless byline.
    assert client.patch("/api/auth/me", headers=cur,
                        json={"public_display_name": "   "}).json()["public_display_name"] is None
    assert named() == "Ada Curator"
    client.patch("/api/auth/me", headers=cur, json={"show_in_ranking": False})


def test_anonymous_cannot_annotate(client):
    res = client.post("/api/occurrences/r2/annotations", json={
        "field": "scientificName", "proposed_value": "x", "status": "submitted"})
    assert res.status_code == 401


def test_provider_export_reviewer_only(client):
    cur = auth_header(client, CURATOR)
    rev = auth_header(client, REVIEWER)
    # contributor forbidden
    assert client.get("/api/export/provider?dataset_name=DS-A", headers=cur).status_code == 403
    # reviewer gets deltas (accepted annotation from previous test)
    res = client.get("/api/export/provider?dataset_name=DS-A", headers=rev)
    assert res.status_code == 200
    body = res.json()
    assert body["count"] >= 1
    assert body["deltas"][0]["proposed_value"] == "Chilodontia laevis"


# ── licensing ──────────────────────────────────────────────────────────────
# What a contributor releases their work under, following iNaturalist's rules:
# CC BY-NC by default, changeable at any time by its contributor, and never
# retroactive — an export already delivered keeps the terms it was delivered
# with. It reaches data providers, so nobody else may restate someone's terms.

def test_license_defaults_to_cc_by_nc(client):
    """A client that says nothing about licensing gets the narrowest of the
    three, not an unlicensed row — including the older client that predates the
    picker and never sends the field."""
    cur = auth_header(client, CURATOR)
    res = client.post("/api/occurrences/r2/annotations", headers=cur, json={
        "field": "locality", "proposed_value": "Nantou", "status": "draft",
    })
    assert res.status_code == 200, res.text
    assert res.json()["license"] == "CC-BY-NC-4.0"


def test_absent_license_follows_the_users_default(client):
    """The user's default is what an unstated licence means — not the platform
    fallback. Changing the default is prospective: the annotation written before
    it keeps what it was contributed under."""
    cur = auth_header(client, CURATOR)
    before = client.post("/api/occurrences/r2/annotations", headers=cur, json={
        "field": "locality", "proposed_value": "Miaoli", "status": "draft",
    }).json()
    assert before["license"] == "CC-BY-NC-4.0"

    me = client.patch("/api/auth/me", headers=cur, json={"default_license": "CC-BY-4.0"})
    assert me.status_code == 200, me.text
    assert me.json()["default_license"] == "CC-BY-4.0"

    after = client.post("/api/occurrences/r2/annotations", headers=cur, json={
        "field": "locality", "proposed_value": "Yunlin", "status": "draft",
    }).json()
    assert after["license"] == "CC-BY-4.0"

    detail = client.get("/api/occurrences/r2").json()
    kept = next(a for a in detail["annotations"] if a["id"] == before["id"])
    assert kept["license"] == "CC-BY-NC-4.0", "changing the default relicensed past work"

    # leave the shared session DB as the other tests expect it
    client.patch("/api/auth/me", headers=cur, json={"default_license": "CC-BY-NC-4.0"})


def test_unknown_default_license_rejected(client):
    cur = auth_header(client, CURATOR)
    res = client.patch("/api/auth/me", headers=cur, json={"default_license": "CC-BY-SA-4.0"})
    assert res.status_code == 400
    assert client.get("/api/auth/me", headers=cur).json()["default_license"] == "CC-BY-NC-4.0"


def test_me_patch_fields_are_independent(client):
    """One setting per request: sending a licence must not silently reset the
    ranking opt-in to false, which is what a required field would have done."""
    cur = auth_header(client, CURATOR)
    client.patch("/api/auth/me", headers=cur, json={"show_in_ranking": True})
    res = client.patch("/api/auth/me", headers=cur, json={"default_license": "CC0-1.0"})
    assert res.status_code == 200, res.text
    assert res.json()["show_in_ranking"] is True
    assert res.json()["default_license"] == "CC0-1.0"
    client.patch("/api/auth/me", headers=cur,
                 json={"show_in_ranking": False, "default_license": "CC-BY-NC-4.0"})


def test_license_is_stored_as_chosen(client):
    cur = auth_header(client, CURATOR)
    res = client.post("/api/occurrences/r2/annotations", headers=cur, json={
        "field": "locality", "proposed_value": "Hualien", "status": "draft",
        "license": "CC0-1.0",
    })
    assert res.status_code == 200, res.text
    assert res.json()["license"] == "CC0-1.0"

    detail = client.get("/api/occurrences/r2").json()
    stored = next(a for a in detail["annotations"] if a["id"] == res.json()["id"])
    assert stored["license"] == "CC0-1.0"


def test_unknown_license_rejected(client):
    """Free text here would end up in a provider's metadata as a licence nobody
    can resolve, so the vocabulary is closed."""
    cur = auth_header(client, CURATOR)
    res = client.post("/api/occurrences/r2/annotations", headers=cur, json={
        "field": "locality", "proposed_value": "x", "status": "draft",
        "license": "WTFPL",
    })
    assert res.status_code == 400
    assert "license" in res.json()["detail"]


def test_only_the_contributor_relicenses(client):
    """A reviewer may edit a *value* in any status — that is the job — but the
    terms are the contributor's statement, and nobody inherits the right to
    restate them."""
    cur = auth_header(client, CURATOR)
    rev = auth_header(client, REVIEWER)
    ann_id = client.post("/api/occurrences/r2/annotations", headers=cur, json={
        "field": "locality", "proposed_value": "Taitung", "status": "submitted",
    }).json()["id"]

    ok = client.patch(f"/api/annotations/{ann_id}", headers=cur, json={"license": "CC-BY-4.0"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["license"] == "CC-BY-4.0"

    edit = client.patch(f"/api/annotations/{ann_id}", headers=rev, json={"proposed_value": "Taitung County"})
    assert edit.status_code == 200
    denied = client.patch(f"/api/annotations/{ann_id}", headers=rev, json={"license": "CC0-1.0"})
    assert denied.status_code == 403
    assert denied.json()["detail"]


def test_contributor_may_relicense_after_review(client):
    """iNaturalist's rule, and ours: what cannot be revoked is the copy a
    provider already took, not the record. So there is no status past which the
    contributor stops being able to change their own terms — the export they
    were already sent keeps what it said, and the next one carries the change."""
    cur = auth_header(client, CURATOR)
    rev = auth_header(client, REVIEWER)
    ann_id = client.post("/api/occurrences/r2/annotations", headers=cur, json={
        "field": "locality", "proposed_value": "Penghu", "status": "submitted",
    }).json()["id"]
    client.patch(f"/api/annotations/{ann_id}", headers=rev, json={"status": "accepted"})

    after = client.patch(f"/api/annotations/{ann_id}", headers=cur, json={"license": "CC0-1.0"})
    assert after.status_code == 200, after.text
    assert after.json()["license"] == "CC0-1.0"
    assert after.json()["status"] == "accepted", "relicensing must not disturb review state"

    client.patch(f"/api/annotations/{ann_id}", headers=rev, json={"status": "merged"})
    merged = client.patch(f"/api/annotations/{ann_id}", headers=cur, json={"license": "CC-BY-4.0"})
    assert merged.status_code == 200, merged.text
    assert merged.json()["license"] == "CC-BY-4.0"


def test_relicensing_shows_in_the_next_export(client):
    """The other half of non-retroactivity: a change has to actually reach the
    next export, or the contributor's decision stops at our own database."""
    cur = auth_header(client, CURATOR)
    rev = auth_header(client, REVIEWER)
    ann_id = client.post("/api/occurrences/r2/annotations", headers=cur, json={
        "field": "locality", "proposed_value": "Kinmen", "status": "submitted",
        "license": "CC-BY-NC-4.0",
    }).json()["id"]
    client.patch(f"/api/annotations/{ann_id}", headers=rev, json={"status": "accepted"})

    def exported():
        body = client.get("/api/export/provider?dataset_name=DS-A", headers=rev).json()
        return next(d for d in body["deltas"] if d["annotation_id"] == ann_id)

    assert exported()["license"] == "CC-BY-NC-4.0"
    client.patch(f"/api/annotations/{ann_id}", headers=cur, json={"license": "CC0-1.0"})
    row = exported()
    assert row["license"] == "CC0-1.0"
    assert row["license_uri"] == "https://creativecommons.org/publicdomain/zero/1.0/"


def test_export_carries_license_and_uri(client):
    """A provider deciding whether it may republish a value needs the terms in
    the same row — both the id we store and the URI DwC's `license` wants. Terms
    vary row by row, so every row states its own; none may be blank."""
    rev = auth_header(client, REVIEWER)
    body = client.get("/api/export/provider?dataset_name=DS-A", headers=rev).json()
    assert body["count"] >= 1
    for row in body["deltas"]:
        assert row["license"] in ("CC0-1.0", "CC-BY-4.0", "CC-BY-NC-4.0"), row
        assert row["license_uri"].startswith("https://creativecommons.org/"), row

    csv_res = client.get("/api/export/provider?dataset_name=DS-A&format=csv", headers=rev)
    assert csv_res.status_code == 200
    header = csv_res.text.splitlines()[0]
    assert "license" in header and "license_uri" in header
