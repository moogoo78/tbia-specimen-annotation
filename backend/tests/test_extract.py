import pytest

from app.extract import parse_pasted
from tests.conftest import auth_header

CURATOR = "curator@tbia.test"


# ── parse_pasted unit tests (the defensive JSON parser) ─────────────────────
def _fields(raw: str) -> dict[str, tuple[str, float]]:
    res = parse_pasted("r2", raw)
    return {f.field: (f.value, f.confidence) for f in res.fields}


def test_parse_plain_json():
    out = _fields('{"fields":[{"field":"scientificName","value":"Rana latouchii","confidence":0.9}]}')
    assert out == {"scientificName": ("Rana latouchii", 0.9)}


def test_parse_strips_markdown_fence():
    raw = '```json\n{"fields":[{"field":"eventDate","value":"2019-06","confidence":0.8}]}\n```'
    assert _fields(raw) == {"eventDate": ("2019-06", 0.8)}


def test_parse_recovers_json_from_surrounding_prose():
    raw = 'Here is the result:\n{"fields":[{"field":"locality","value":"野柳","confidence":0.7}]}\nHope this helps!'
    assert _fields(raw) == {"locality": ("野柳", 0.7)}


def test_parse_accepts_bare_list_and_scales_0_100_confidence():
    # value coerced to string; confidence 95 (0–100 scale) → 0.95
    assert _fields('[{"field":"decimalLatitude","value":25.03,"confidence":95}]') == {
        "decimalLatitude": ("25.03", 0.95)
    }


def test_parse_accepts_flat_object_with_default_confidence():
    out = _fields('{"scientificName":"Bufo bankorensis","eventDate":"2020-01-01"}')
    assert out == {"scientificName": ("Bufo bankorensis", 0.0), "eventDate": ("2020-01-01", 0.0)}


def test_parse_drops_unknown_fields_and_duplicates():
    # recordedBy is not annotatable; the first scientificName wins over the dup
    raw = ('{"fields":[{"field":"recordedBy","value":"X"},'
           '{"field":"scientificName","value":"A"},'
           '{"field":"scientificName","value":"B"}]}')
    assert _fields(raw) == {"scientificName": ("A", 0.0)}


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
    assert "scientificName" in data["target_fields"]
    assert "scientificName" in data["prompt"]
    assert data["image_url"] is None  # r2 has no media


def test_extract_prompt_404_for_unknown_record(client):
    res = client.get("/api/occurrences/nope/extract-prompt", headers=auth_header(client, CURATOR))
    assert res.status_code == 404


def test_extract_paste_happy_path(client):
    body = {"raw": '{"fields":[{"field":"scientificName","value":"Chilodontia laevis","confidence":0.88}]}'}
    res = client.post("/api/occurrences/r2/extract-paste", headers=auth_header(client, CURATOR), json=body)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["fields"] == [
        {"field": "scientificName", "value": "Chilodontia laevis", "confidence": 0.88}
    ]
    assert data["model"]


def test_extract_paste_400_on_garbage(client):
    res = client.post("/api/occurrences/r2/extract-paste",
                      headers=auth_header(client, CURATOR), json={"raw": "not json"})
    assert res.status_code == 400


def test_extract_paste_requires_auth(client):
    res = client.post("/api/occurrences/r2/extract-paste", json={"raw": "{}"})
    assert res.status_code == 401
