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


def test_organizations_are_skipped():
    """Every one of these is in the 2026-08-05 export as a 'collector'."""
    for org in ("台南區農業改良場", "種苗改良繁殖場", "美國農部", "嘉義農專",
                "保加利亞植物種原庫", "美國北部中區植物引種站", "駐厄瓜多農技團",
                "台東鳥會", "連江縣建設局", "三峽五寮派出所", "北市動檢所",
                "中研院植物所", "和欣動物醫院許醫師", "亞典企業集團", "光榮漁場",
                "武漢師範學院", "北海道大学", "台灣銀行公館分行", "Shinyo Koeki Co., Ltd."):
        assert parse_collector(org) is None, org
    # collectives and roles standing in for a name
    for role in ("水雉教育園區人員", "安檢所官兵", "生態池志工", "職業獵人",
                 "建築工人", "陳秀惠老師的學生", "機場人員", "fishermen",
                 "COMMERCIAL FISHERMEN/H.-K. MOK"):
        assert parse_collector(role) is None, role
    # a bare country is provenance, not a collector
    assert parse_collector("印度，國際熱帶半乾旱作物研究所") is None
    assert parse_collector("China And Taiwan Union Investigation Team") is None


def test_org_keywords_do_not_eat_real_names():
    """The reason every Chinese token is at least two characters."""
    assert parse_collector("Li-Yaung Kuo (郭立園)") == ("郭立園", "Li-Yaung Kuo")
    assert parse_collector("Yen-Hsueh Tseng (曾彥學)") == ("曾彥學", "Yen-Hsueh Tseng")
    assert parse_collector("Ke Xiong (熊科)") == ("熊科", "Ke Xiong")
    assert parse_collector("Cheng-Hsueh Tsai (蔡政學)") == ("蔡政學", "Cheng-Hsueh Tsai")


def test_affiliation_glued_to_the_name_is_stripped():
    # underscore: the romanization sits *after* the institution
    assert parse_collector("張玉珍_林試所 Y. C. Chang") == ("張玉珍", "Y. C. Chang")
    assert parse_collector("陳宗憲-中研院植物所") == ("陳宗憲", "")
    # spaced dash, latin institution -> the whole tail goes
    assert parse_collector("W H. Chou - National Museum of Natural Science") == (
        "", "W H. Chou")
    # a hyphenated given name is not an affiliation
    assert parse_collector("Wen-Liang Chiou (邱文良)") == ("邱文良", "Wen-Liang Chiou")


def test_a_later_organization_does_not_discard_the_first_person():
    """Orgs are judged on the segment kept; unknown markers on the whole value."""
    assert parse_collector("Jenn-Che Wang (王震哲), Summer collection team") == (
        "王震哲", "Jenn-Che Wang")
    assert parse_collector("HK Mok, Nat'l Sun-Yat Sen Univ., Taiwan") == ("", "HK Mok")
    # but "s.n." / "illegible" mean the attribution itself is unusable, so a
    # surname fragment must not become a collector
    assert parse_collector("Lu,S.-Y. s.n. [2009-05-18]") is None
    assert parse_collector("Huang, Chien-I; illegible,") is None


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
