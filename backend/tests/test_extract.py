import pytest

from app.extract import parse_pasted
from tests.conftest import auth_header

CURATOR = "curator@tbia.test"


# ── parse_pasted unit tests (the defensive JSON parser) ─────────────────────
def _fields(raw: str) -> dict[str, tuple[str, float]]:
    res = parse_pasted("r2", raw)
    return {f.field: (f.value, f.confidence) for f in res.fields}


def test_parse_plain_json():
    out = _fields('{"fields":[{"field":"annotationScientificName","value":"Rana latouchii","confidence":0.9}]}')
    assert out == {"annotationScientificName": ("Rana latouchii", 0.9)}


def test_parse_strips_markdown_fence():
    raw = '```json\n{"fields":[{"field":"eventDate","value":"2019-06","confidence":0.8}]}\n```'
    assert _fields(raw) == {"eventDate": ("2019-06", 0.8)}


def test_parse_recovers_json_from_surrounding_prose():
    raw = 'Here is the result:\n{"fields":[{"field":"locality","value":"野柳","confidence":0.7}]}\nHope this helps!'
    assert _fields(raw) == {"locality": ("野柳", 0.7)}


def test_parse_accepts_bare_list_and_scales_0_100_confidence():
    # value coerced to string; confidence 95 (0–100 scale) → 0.95
    assert _fields('[{"field":"verbatimLatitude","value":25.03,"confidence":95}]') == {
        "verbatimLatitude": ("25.03", 0.95)
    }


def test_parse_accepts_flat_object_with_default_confidence():
    out = _fields('{"annotationScientificName":"Bufo bankorensis","eventDate":"2020-01-01"}')
    assert out == {"annotationScientificName": ("Bufo bankorensis", 0.0), "eventDate": ("2020-01-01", 0.0)}


def test_parse_drops_unknown_fields_and_duplicates():
    # kingdom is not annotatable; the first annotationScientificName wins over the dup
    raw = ('{"fields":[{"field":"kingdom","value":"X"},'
           '{"field":"annotationScientificName","value":"A"},'
           '{"field":"annotationScientificName","value":"B"}]}')
    assert _fields(raw) == {"annotationScientificName": ("A", 0.0)}


def test_parse_skips_empty_and_null_values():
    raw = '{"fields":[{"field":"locality","value":""},{"field":"eventDate","value":null}]}'
    with pytest.raises(ValueError):
        parse_pasted("r2", raw)


@pytest.mark.parametrize("raw", ["not json at all", "   ", "", "{}", "[]"])
def test_parse_rejects_unusable_input(raw):
    with pytest.raises(ValueError):
        parse_pasted("r2", raw)


# ── endpoint tests ──────────────────────────────────────────────────────────
def test_extract_prompt_targets_gap_fields(client):
    # r2 lacks identification / date / coordinates → prompt should target them
    res = client.get("/api/occurrences/r2/extract-prompt", headers=auth_header(client, CURATOR))
    assert res.status_code == 200
    data = res.json()
    assert "annotationScientificName" in data["target_fields"]
    assert "annotationScientificName" in data["prompt"]
    assert data["image_urls"] == []  # r2 has no media


def test_extract_prompt_lists_every_image(client):
    """r4 has two media URLs. Both must reach the prompt, with the rule that says
    they are one specimen — otherwise a value legible only on the second image is
    silently unreachable."""
    res = client.get("/api/occurrences/r4/extract-prompt", headers=auth_header(client, CURATOR))
    assert res.status_code == 200
    data = res.json()
    assert data["image_urls"] == ["http://x/img4.jpg", "http://x/img4b.jpg"]
    for url in data["image_urls"]:
        assert url in data["prompt"]
    assert "SAME specimen" in data["prompt"]


def test_extract_prompt_caps_images(client, monkeypatch):
    """The cap bounds what one record can cost; images dominate the token bill."""
    from app.config import settings

    monkeypatch.setattr(settings, "transcribe_max_images", 1)
    data = client.get("/api/occurrences/r4/extract-prompt",
                      headers=auth_header(client, CURATOR)).json()
    assert data["image_urls"] == ["http://x/img4.jpg"]
    assert "http://x/img4b.jpg" not in data["prompt"]


def test_extract_prompt_404_for_unknown_record(client):
    res = client.get("/api/occurrences/nope/extract-prompt", headers=auth_header(client, CURATOR))
    assert res.status_code == 404


def test_extract_paste_happy_path(client):
    body = {"raw": '{"fields":[{"field":"annotationScientificName","value":"Chilodontia laevis","confidence":0.88}]}'}
    res = client.post("/api/occurrences/r2/extract-paste", headers=auth_header(client, CURATOR), json=body)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["fields"] == [
        {"field": "annotationScientificName", "value": "Chilodontia laevis", "confidence": 0.88}
    ]
    assert data["model"]


def test_extract_paste_400_on_garbage(client):
    res = client.post("/api/occurrences/r2/extract-paste",
                      headers=auth_header(client, CURATOR), json={"raw": "not json"})
    assert res.status_code == 400


def test_extract_paste_requires_auth(client):
    res = client.post("/api/occurrences/r2/extract-paste", json={"raw": "{}"})
    assert res.status_code == 401
