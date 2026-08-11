"""The taxonomic index over the fixture store.

Fixture names: r1 Pocillopora damicornis (species), r3 + r7 Helianthus annuus
(species, two records), r4 Rosa canina (species), r6 Begonia (genus, named),
r2 + r5 unnamed. So five distinct names, four of them identified to species.
"""


def test_one_row_per_distinct_name(client):
    res = client.get("/api/species?scope=all").json()
    names = [r["name"] for r in res["items"]]
    assert names == sorted(set(names), key=names.index)  # no name twice
    assert set(names) == {
        "Pocillopora damicornis", "Helianthus annuus", "Rosa canina", "Begonia",
    }
    assert res["total"] == 4


def test_unnamed_records_are_not_a_row(client):
    """r2 and r5 have no scientific_name — they name no taxon, so no row."""
    res = client.get("/api/species?scope=all&limit=500").json()
    assert all(r["name"] for r in res["items"])
    # 7 occurrence rows, 2 of them unnamed
    assert res["totals"]["records"] == 5
    assert sum(r["n_records"] for r in res["items"]) == 5


def test_counts_match_the_store(client):
    res = client.get("/api/species?scope=all&limit=500").json()
    by_name = {r["name"]: r for r in res["items"]}
    assert by_name["Helianthus annuus"]["n_records"] == 2   # r3 + r7
    assert by_name["Rosa canina"]["n_records"] == 1

    for name, row in by_name.items():
        direct = client.get("/api/occurrences", params={"scientific_name": name}).json()
        assert direct["total"] == row["n_records"], name


def test_default_scope_is_species_or_below(client):
    """`Begonia` is named but identified only to genus, so the default scope
    leaves it out and the widened scope brings it back."""
    default = client.get("/api/species").json()
    assert default["scope"] == "species"
    assert "Begonia" not in {r["name"] for r in default["items"]}
    assert default["total"] == 3

    widened = client.get("/api/species?scope=all").json()
    begonia = next(r for r in widened["items"] if r["name"] == "Begonia")
    assert begonia["taxon_rank"] == "genus"
    assert begonia["n_identified"] == 0


def test_search_is_case_insensitive_over_both_names(client):
    for term in ("helianthus", "HELIANTHUS", "anthus ann"):
        res = client.get("/api/species", params={"q": term}).json()
        assert [r["name"] for r in res["items"]] == ["Helianthus annuus"], term
        assert res["total"] == 1, term

    # total reflects the search, not the page
    none = client.get("/api/species", params={"q": "no-such-name"}).json()
    assert none["total"] == 0 and none["items"] == []

    # totals describe the whole index regardless of the search
    assert none["totals"]["names"] == 4


def test_sorting_both_keys_and_directions(client):
    def names(**params):
        return [r["name"] for r in client.get("/api/species", params={"scope": "all", **params}).json()["items"]]

    # Helianthus annuus (2 records) leads; the three singletons tie and are
    # broken by name, which is what makes paging deterministic.
    assert names(sort="records", order="desc")[0] == "Helianthus annuus"
    assert names(sort="records", order="asc")[-1] == "Helianthus annuus"
    assert names(sort="name", order="asc") == sorted(names(sort="name", order="asc"))
    assert names(sort="name", order="desc") == sorted(names(sort="name", order="desc"), reverse=True)


def test_paging_neither_repeats_nor_skips(client):
    seen = []
    for offset in (0, 2, 4):
        page = client.get("/api/species", params={
            "scope": "all", "limit": 2, "offset": offset, "sort": "records", "order": "desc",
        }).json()
        seen.extend(r["name"] for r in page["items"])
        assert page["total"] == 4
    assert len(seen) == len(set(seen)) == 4


def test_scope_and_sort_are_validated(client):
    assert client.get("/api/species?scope=genus").status_code == 422
    assert client.get("/api/species?sort=family").status_code == 422


def test_rollup_is_cached_across_requests(client, monkeypatch):
    """The scan is the expensive part — a second request must not repeat it."""
    from app.api import species

    calls = {"n": 0}
    real = species.duck.query

    async def counting(sql, params=None):
        if "GROUP BY scientific_name" in sql:
            calls["n"] += 1
        return await real(sql, params) if params is not None else await real(sql)

    species._ROLLUP = None      # drop whatever earlier tests warmed
    monkeypatch.setattr(species.duck, "query", counting)

    client.get("/api/species")
    client.get("/api/species?scope=all&sort=name")
    assert calls["n"] == 1
