"""The two server-side transcription routes.

Both land in the same place — a `transcribe_requests` row plus `ai` annotation
drafts — and differ only in who waits and who pays: the queue hands the record
to the batch worker and pings Discord, run-now spends the API call inside the
request, which is why it is admin-only.
"""

import pytest

from app import pipeline
from tests.conftest import auth_header

CURATOR = "curator@tbia.test"
REVIEWER = "reviewer@tbia.test"
ADMIN = "admin@tbia.test"

_REPLY = '{"fields":[{"field":"locality","value":"野柳","confidence":0.88}]}'


class _Block:
    def __init__(self, text: str) -> None:
        self.type, self.text = "text", text


class _Resp:
    def __init__(self, text: str) -> None:
        self.content, self.model = [_Block(text)], "stub-model"


class _Messages:
    def create(self, **kwargs):
        return _Resp(_REPLY)


class _Client:
    messages = _Messages()


@pytest.fixture
def stub_claude(monkeypatch):
    monkeypatch.setattr(pipeline.anthropic, "Anthropic", lambda *a, **k: _Client())


def test_run_now_is_admin_only(client, stub_claude):
    for who in (CURATOR, REVIEWER):
        res = client.post("/api/occurrences/r4/transcribe-now", headers=auth_header(client, who))
        assert res.status_code == 403, who
    assert client.post("/api/occurrences/r4/transcribe-now").status_code == 401


def test_run_now_writes_drafts_in_the_request(client, stub_claude):
    res = client.post("/api/occurrences/r4/transcribe-now", headers=auth_header(client, ADMIN))
    assert res.status_code == 200
    data = res.json()
    # Already processed by the time it answers — that is the whole point.
    assert data["status"] == "done"
    assert data["n_annotations"] >= 1
    assert data["error"] is None

    # Same destination as the queue: the record carries the request and the
    # drafts, so a reload shows what the worker would have produced.
    detail = client.get("/api/occurrences/r4").json()
    assert detail["transcribe"]["status"] == "done"
    ai = [a for a in detail["annotations"] if a["source"] == "ai"]
    assert {a["field"] for a in ai} >= {"locality"}
    assert all(a["status"] == "submitted" for a in ai)


def test_run_now_reports_pipeline_failure_in_band(client, monkeypatch):
    """A missing API key or an unreadable image is an outcome, not a 500 — the
    admin needs the reason, and the row has to record the attempt either way."""
    def _boom(*a, **k):
        raise RuntimeError("no ANTHROPIC_API_KEY")

    monkeypatch.setattr(pipeline, "transcribe_record", _boom)
    res = client.post("/api/occurrences/r4/transcribe-now", headers=auth_header(client, ADMIN))
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "failed"
    assert data["n_annotations"] == 0
    assert "ANTHROPIC_API_KEY" in data["error"]


def test_run_now_drains_a_queued_request_instead_of_adding_one(client, stub_claude):
    """Otherwise the pending row survives the run and the worker transcribes the
    same record again later, writing a second set of drafts."""
    cur = auth_header(client, CURATOR)
    queued = client.post("/api/occurrences/r1/transcribe-request", headers=cur).json()

    ran = client.post("/api/occurrences/r1/transcribe-now",
                      headers=auth_header(client, ADMIN)).json()
    assert ran["id"] == queued["id"]          # the queued row, now processed
    assert ran["status"] == "done"
    assert ran["contributor_id"] == queued["contributor_id"]  # credited to the asker

    # Nothing left for the worker to pick up.
    from app.db import SessionLocal
    from app.models import TranscribeRequest

    with SessionLocal() as db:
        pending = [r for r in db.query(TranscribeRequest)
                   .filter_by(occurrence_id="r1", status="pending")]
    assert pending == []


def test_run_now_404_for_unknown_record(client, stub_claude):
    res = client.post("/api/occurrences/nope/transcribe-now", headers=auth_header(client, ADMIN))
    assert res.status_code == 404


def test_queue_route_stays_open_to_contributors_and_does_not_transcribe(client, monkeypatch):
    """The queue must not call the API — that is the worker's job, later."""
    def _boom(*a, **k):
        raise AssertionError("queueing must not call the model")

    monkeypatch.setattr(pipeline, "transcribe_record", _boom)
    res = client.post("/api/occurrences/r4/transcribe-request",
                      headers=auth_header(client, CURATOR))
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "pending"
    assert data["n_annotations"] == 0
