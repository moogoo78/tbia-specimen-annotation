from app.collectors_parse import parse_collector


def test_parse_collector_rules():
    assert parse_collector("Pi-Fong Lu (呂碧鳳)") == ("呂碧鳳", "Pi-Fong Lu")
    assert parse_collector("范義彬 Y. B. Fan") == ("范義彬", "Y. B. Fan")
    assert parse_collector("陶錫珍（Hsi-Jen Tao）") == ("陶錫珍", "Hsi-Jen Tao")
    assert parse_collector("陳邦傑等") == ("陳邦傑", "")          # 等 stripped
    assert parse_collector("Knapp, R.") == ("", "R. Knapp")       # Last, First
    # first of several collectors
    assert parse_collector("Zhi-Jiang Zhang (張志江), Wen-Qi Liu (劉文奇)") == (
        "張志江", "Zhi-Jiang Zhang")
    # radical-decomposition glyph stays attached
    assert parse_collector("Hsiu-Jung Wu (吳(糸秀)容)") == ("吳(糸秀)容", "Hsiu-Jung Wu")
    # non-people
    assert parse_collector("亞洲蔬菜研究發展中心") is None
    assert parse_collector("(unknown 採集者不明)") is None
    assert parse_collector("") is None


def test_collectors_endpoint(client):
    data = client.get("/api/collectors").json()
    by_name = {d["name"]: d for d in data}

    # org excluded
    assert all("中心" not in d["name"] for d in data)
    # "呂碧鳳" + "Pi-Fong Lu (呂碧鳳)" fold to one collector, n_records summed, en backfilled
    lu = by_name["呂碧鳳"]
    assert lu["name_en"] == "Pi-Fong Lu"
    assert lu["label"] == "呂碧鳳 Pi-Fong Lu"
    assert lu["n_records"] == 2
    # first-of-many kept
    assert "許天銓" in by_name


def test_collectors_search_and_detail(client):
    hits = client.get("/api/collectors", params={"q": "Pi-Fong"}).json()
    assert any(d["name"] == "呂碧鳳" for d in hits)

    cid = next(d["id"] for d in client.get("/api/collectors").json() if d["name"] == "呂碧鳳")
    detail = client.get(f"/api/collectors/{cid}").json()
    assert set(detail["aliases"]) == {"Pi-Fong Lu (呂碧鳳)", "呂碧鳳"}

    assert client.get("/api/collectors/999999").status_code == 404


def test_resolve_collector(client):
    # exact raw recorded_by -> canonical collector (powers the record-detail link)
    r = client.get("/api/collectors/resolve", params={"recorded_by": "Pi-Fong Lu (呂碧鳳)"}).json()
    assert r["name"] == "呂碧鳳" and r["name_en"] == "Pi-Fong Lu"
    # the zh-only variant resolves to the same collector
    r2 = client.get("/api/collectors/resolve", params={"recorded_by": "呂碧鳳"}).json()
    assert r2["id"] == r["id"]
    # an organization value is unmapped -> null
    assert client.get(
        "/api/collectors/resolve", params={"recorded_by": "亞洲蔬菜研究發展中心"}
    ).json() is None


def test_collector_id_filter(client):
    cid = next(d["id"] for d in client.get("/api/collectors").json() if d["name"] == "呂碧鳳")
    # r1 ('Pi-Fong Lu (呂碧鳳)') + r2 ('呂碧鳳') both map to this collector
    res = client.get("/api/occurrences", params={"collector_id": cid}).json()
    assert res["total"] == 2
    assert {r["id"] for r in res["items"]} == {"r1", "r2"}

    # facets honor the same filter
    f = client.get("/api/occurrences/facets", params={"collector_id": cid}).json()
    assert f["completeness"]["total"] == 2
