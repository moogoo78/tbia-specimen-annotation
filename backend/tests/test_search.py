def test_total_and_completeness_facets(client):
    res = client.get("/api/occurrences").json()
    assert res["total"] == 5

    f = client.get("/api/occurrences/facets").json()
    c = f["completeness"]
    assert c["total"] == 5
    assert c["missing_identification"] == 2   # r2, r5
    assert c["missing_coordinates"] == 2      # r2, r4
    assert c["missing_date"] == 2             # r2, r5
    assert c["has_media"] == 2                # r1, r4


def test_missing_identification_filter(client):
    res = client.get("/api/occurrences?missing_identification=true").json()
    ids = {r["id"] for r in res["items"]}
    assert ids == {"r2", "r5"}


def test_combined_filters(client):
    # fish + missing coordinates -> only r2
    res = client.get("/api/occurrences?bio_group=魚類&missing_coordinates=true").json()
    assert [r["id"] for r in res["items"]] == ["r2"]


def test_record_number_range(client):
    # 100-200 matches r1(100), r2(150), r3(200); excludes r5(250) and r4(non-numeric)
    res = client.get("/api/occurrences", params={"record_number_from": 100, "record_number_to": 200}).json()
    assert {r["id"] for r in res["items"]} == {"r1", "r2", "r3"}
    # open-ended lower bound
    hi = client.get("/api/occurrences", params={"record_number_from": 200}).json()
    assert {r["id"] for r in hi["items"]} == {"r3", "r5"}


def test_free_text_search(client):
    res = client.get("/api/occurrences?q=Helianthus").json()
    assert res["total"] == 1 and res["items"][0]["id"] == "r3"


def test_default_sort_surfaces_gaps_first(client):
    # default sort = completeness_score asc -> least complete record first
    res = client.get("/api/occurrences").json()
    assert res["items"][0]["completeness_score"] == 0


def test_facet_bio_group_counts(client):
    f = client.get("/api/occurrences/facets").json()
    counts = {x["value"]: x["count"] for x in f["bio_group"]}
    assert counts["魚類"] == 2 and counts["維管束植物"] == 2 and counts["昆蟲"] == 1


def test_detail_and_media_parse(client):
    r = client.get("/api/occurrences/r1").json()
    assert r["scientific_name"] == "Pocillopora damicornis"
    assert r["media"] == ["http://x/img1.jpg"]
    assert r["annotations"] == []


def test_datasets_summary(client):
    ds = {d["dataset_name"]: d for d in client.get("/api/datasets").json()}
    assert ds["DS-A"]["n_records"] == 3
