def test_total_and_completeness_facets(client):
    res = client.get("/api/occurrences").json()
    assert res["total"] == 7

    f = client.get("/api/occurrences/facets").json()
    c = f["completeness"]
    assert c["total"] == 7
    # r6 is named but only to genus, so it counts as unidentified — the flag is
    # rank-aware (`ingest.common.SPECIES_RANKS`), not merely "has a name".
    assert c["missing_identification"] == 3   # r2, r5, r6
    assert c["missing_coordinates"] == 2      # r2, r4
    assert c["missing_date"] == 2             # r2, r5
    assert c["has_media"] == 2                # r1, r4


def test_missing_identification_filter(client):
    res = client.get("/api/occurrences?missing_identification=true").json()
    ids = {r["id"] for r in res["items"]}
    assert ids == {"r2", "r5", "r6"}


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


def test_record_number_text(client):
    """r4 is 'TAI-9' — non-numeric, so no range can ever reach it."""
    res = client.get("/api/occurrences", params={"record_number": "TAI-9"}).json()
    assert {r["id"] for r in res["items"]} == {"r4"}

    # substring, case-insensitive
    for term in ("tai", "AI-", "9"):
        hit = client.get("/api/occurrences", params={"record_number": term}).json()
        assert "r4" in {r["id"] for r in hit["items"]}, term

    # a numeric record number is still reachable as text
    num = client.get("/api/occurrences", params={"record_number": "150"}).json()
    assert {r["id"] for r in num["items"]} == {"r2"}

    # blank/whitespace is not a filter
    blank = client.get("/api/occurrences", params={"record_number": "   "}).json()
    assert blank["total"] == client.get("/api/occurrences").json()["total"]

    # combines with the range as AND — TAI-9 is not in 100–200, so nothing matches
    both = client.get("/api/occurrences", params={
        "record_number": "TAI-9", "record_number_from": 100, "record_number_to": 200}).json()
    assert both["total"] == 0

    # and with other facets
    with_group = client.get("/api/occurrences", params={
        "record_number": "tai", "bio_group": "維管束植物"}).json()
    assert {r["id"] for r in with_group["items"]} == {"r4"}


def test_free_text_search(client):
    res = client.get("/api/occurrences?q=Helianthus").json()
    assert res["total"] == 2 and {r["id"] for r in res["items"]} == {"r3", "r7"}


def test_scientific_name_filter_is_exact(client):
    """The species index links through this filter, so it has to be exact —
    free-text `q` is substring across eleven columns and cannot be used."""
    res = client.get("/api/occurrences", params={"scientific_name": "Helianthus annuus"}).json()
    assert {r["id"] for r in res["items"]} == {"r3", "r7"}

    # a prefix is not a match, though the same string as free text finds both
    assert client.get("/api/occurrences", params={"scientific_name": "Helianthus"}).json()["total"] == 0
    assert client.get("/api/occurrences", params={"q": "Helianthus"}).json()["total"] == 2

    # multi-valued, like the other IN filters
    both = client.get(
        "/api/occurrences?scientific_name=Helianthus annuus&scientific_name=Rosa canina").json()
    assert {r["id"] for r in both["items"]} == {"r3", "r7", "r4"}

    # and it composes with the rest of the filter set
    with_group = client.get("/api/occurrences", params={
        "scientific_name": "Helianthus annuus", "bio_group": "魚類"}).json()
    assert with_group["total"] == 0


def test_species_row_count_agrees_with_explore(client):
    """A row's count and the record search behind it are the same number — the
    species page links with has_media cleared for exactly this reason."""
    for row in client.get("/api/species?scope=all&limit=500").json()["items"]:
        found = client.get("/api/occurrences", params={"scientific_name": row["name"]}).json()
        assert found["total"] == row["n_records"], row["name"]


def test_default_sort_surfaces_gaps_first(client):
    # default sort = completeness_score asc -> least complete record first
    res = client.get("/api/occurrences").json()
    assert res["items"][0]["completeness_score"] == 0


def test_facet_bio_group_counts(client):
    f = client.get("/api/occurrences/facets").json()
    counts = {x["value"]: x["count"] for x in f["bio_group"]}
    assert counts["魚類"] == 2 and counts["維管束植物"] == 4 and counts["昆蟲"] == 1


def test_detail_and_media_parse(client):
    r = client.get("/api/occurrences/r1").json()
    assert r["scientific_name"] == "Pocillopora damicornis"
    assert r["media"] == ["http://x/img1.jpg"]
    assert r["annotations"] == []


def test_datasets_summary(client):
    ds = {d["dataset_name"]: d for d in client.get("/api/datasets").json()}
    assert ds["DS-A"]["n_records"] == 3


def test_standard_date_is_a_plain_date(client):
    """standard_date is a TIMESTAMP in the store; both reads narrow it to a day."""
    detail = client.get("/api/occurrences/r1").json()
    assert detail["standard_date"] == "2004-09-16"
    row = next(x for x in client.get("/api/occurrences").json()["items"] if x["id"] == "r1")
    assert row["standard_date"] == "2004-09-16"


def test_registry_merges_datasets_from_the_db(client):
    """Datasets not curated in registry.json are discovered from the `dataset`
    table and grouped under aggregators by institution_code."""
    reg = client.get("/api/registry").json()
    ent = reg["aggregators"]["TEST"]
    assert set(ent["datasets"]) == {"DS-A", "DS-B"}
    # the aggregator uuid is referenced from the DB, never pinned in the file
    assert ent["datasets"]["DS-A"]["gbif"] == "src-DS-A"
    # curated institutions still come from the file
    assert reg["institutions"]
