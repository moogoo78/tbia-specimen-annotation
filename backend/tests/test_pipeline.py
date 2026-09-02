"""The transcription pipeline's request shape, with Claude stubbed out.

The point of interest is multi-image records: a record's media are several views
of ONE specimen (sheet, label close-up, determination slip), so every image has
to reach the model in the same request, and the prompt has to say they are one
specimen — otherwise the reply is either about one image or four competing
answers per field.
"""

import base64
import ssl

import httpx
import pytest

from app import extract, pipeline

RECORD = {
    "id": "r4",
    "media": ["http://x/img4.jpg", "http://x/img4b.jpg"],
    "has_identification": True,
    "has_date": True,
    "has_coordinates": False,
    "dataset_name": "DS-B",
}

_REPLY = '{"fields":[{"field":"locality","value":"野柳","confidence":0.9}]}'
_OCR_REPLY = "--- image 1 ---\n野柳\n\n--- image 2 ---\n[no text]"


class _Block:
    def __init__(self, text: str) -> None:
        self.type, self.text = "text", text


class _Resp:
    def __init__(self, text: str) -> None:
        self.content, self.model = [_Block(text)], "stub-model"


class _Messages:
    def __init__(self, calls: list[dict]) -> None:
        self._calls = calls

    def create(self, **kwargs):
        self._calls.append(kwargs)
        # Answer in the shape the stage asked for: a JSON field list where the
        # prompt demands JSON, verbatim transcript otherwise (the OCR stage).
        asked_for_json = "STRICT JSON" in _text(kwargs)
        return _Resp(_REPLY if asked_for_json else _OCR_REPLY)


class _Client:
    def __init__(self, calls: list[dict]) -> None:
        self.messages = _Messages(calls)


class _Fetched:
    """A fetched image whose bytes ARE its URL, behind a JPEG magic number — so
    a test can read back which image ended up in the request now that the block
    carries pixels rather than a URL."""

    def __init__(self, url: str) -> None:
        self.content = b"\xff\xd8\xff" + url.encode()

    def raise_for_status(self) -> "_Fetched":
        return self


class _HTTP:
    def __init__(self, fail: str | None = None) -> None:
        self._fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url: str) -> _Fetched:
        if self._fail is not None and url == self._fail:
            raise httpx.ConnectError("unreachable")
        return _Fetched(url)


@pytest.fixture
def calls(monkeypatch):
    """Records every messages.create() the pipeline makes."""
    recorded: list[dict] = []
    # `pipeline._client()` checks the key before constructing the client, so the
    # stub needs one — otherwise these tests would depend on the .env of
    # whatever machine runs them.
    monkeypatch.setattr(pipeline.settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(
        pipeline.anthropic, "Anthropic", lambda *a, **k: _Client(recorded),
    )
    # No network in the suite: every image "downloads" as its own URL.
    monkeypatch.setattr(pipeline.httpx, "Client", lambda **kw: _HTTP())
    return recorded


def _content(call: dict) -> list[dict]:
    """Blocks of the single user message. Stage 2 is text-only, and the SDK takes
    a bare string there — normalize it to one text block."""
    content = call["messages"][0]["content"]
    return [{"type": "text", "text": content}] if isinstance(content, str) else content


def _images(call: dict) -> list[str]:
    """Which images the request carried. The bytes are the URL they came from
    (see `_Fetched`), past the three-byte JPEG magic."""
    return [
        base64.standard_b64decode(b["source"]["data"])[3:].decode()
        for b in _content(call) if b["type"] == "image"
    ]


def _text(call: dict) -> str:
    return "".join(b["text"] for b in _content(call) if b["type"] == "text")


def test_single_mode_sends_every_image_in_one_request(calls, monkeypatch):
    monkeypatch.setattr(pipeline.settings, "transcribe_mode", "single")
    out = pipeline.transcribe_record(RECORD, mode="single")

    assert len(calls) == 1
    assert _images(calls[0]) == RECORD["media"]
    assert "SAME specimen" in _text(calls[0])
    assert out.image_urls == RECORD["media"]


def test_two_stage_ocrs_all_images_then_merges_the_transcripts(calls):
    out = pipeline.transcribe_record(RECORD, mode="two_stage",
                                     ocr_model="ocr-m", field_model="field-m")

    assert len(calls) == 2
    # Stage 1 sees the images; stage 2 is text-only.
    assert _images(calls[0]) == RECORD["media"]
    assert "2 images" in _text(calls[0])
    assert _images(calls[1]) == []
    assert "--- image N ---" in _text(calls[1])
    # The verbatim transcript of both images survives as full_text.
    full_text = next(f.value for f in out.fields if f.field == "full_text")
    assert "--- image 2 ---" in full_text
    assert out.model == "ocr-m + field-m"


def test_single_image_keeps_the_single_image_prompt(calls, monkeypatch):
    monkeypatch.setattr(pipeline.settings, "transcribe_max_images", 1)
    pipeline.transcribe_record(RECORD, mode="two_stage")

    assert _images(calls[0]) == RECORD["media"][:1]
    assert "SAME specimen" not in _text(calls[0])
    assert "--- image N ---" not in _text(calls[1])


def test_record_without_media_still_raises():
    with pytest.raises(ValueError):
        pipeline.transcribe_record({"id": "r2", "media": []})


def test_images_dedupes_and_caps(monkeypatch):
    monkeypatch.setattr(extract.settings, "transcribe_max_images", 2)
    record = {"media": ["a", "a", "b", "c"]}
    assert extract.images(record) == ["a", "b"]


def test_images_travel_as_bytes_not_as_urls(calls):
    """The API can fetch a URL itself, but NMNS's media host defeats that twice
    over — a 302 it will not follow, and a JPEG labelled `image/jpg` — each
    answering with the same opaque 400. So the pixels go in the request, under a
    media type we determine rather than one the server claimed."""
    pipeline.transcribe_record(RECORD, mode="two_stage")

    blocks = [b for b in _content(calls[0]) if b["type"] == "image"]
    assert [b["source"]["type"] for b in blocks] == ["base64", "base64"]
    assert [b["source"]["media_type"] for b in blocks] == ["image/jpeg", "image/jpeg"]


def test_an_unfetchable_image_fails_the_request_by_name(calls, monkeypatch):
    """Loudly, on purpose. The failure this replaces was a 400 that named
    nothing; `process_one` stores whatever is raised here as the request's
    error, so a dead media URL says so."""
    monkeypatch.setattr(
        pipeline.httpx, "Client", lambda **kw: _HTTP(fail=RECORD["media"][1]),
    )
    with pytest.raises(httpx.ConnectError):
        pipeline.transcribe_record(RECORD, mode="two_stage")


def test_tls_stays_verified_minus_the_strict_x509_checks():
    """The one concession NMNS's host needs, and no more: chain, expiry and
    hostname are still checked — only OpenSSL's RFC 5280 formatting audit is
    dropped, which is what Python 3.13 turned on by default and what rejects
    that host's CA for a missing Subject Key Identifier."""
    assert not pipeline._SSL.verify_flags & ssl.VERIFY_X509_STRICT
    assert pipeline._SSL.verify_mode == ssl.CERT_REQUIRED
    assert pipeline._SSL.check_hostname is True
