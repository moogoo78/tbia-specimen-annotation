"""The taxon tree and taxon filter (app/taxa.py).

Fixture: Plantae > Tracheophyta > Magnoliopsida > {Asterales > Asteraceae >
Helianthus (r3, r7), Rosales > Rosaceae > Rosa (r4), Cucurbitales > Begoniaceae >
Begonia (r6, genus-rank)}; Animalia > Cnidaria > … > Pocillopora (r1), and r5 in
Animalia with nothing below. r2 has no kingdom at all.
"""

import duckdb
import pytest

from app import taxa


@pytest.fixture(autouse=True)
def _fresh_tree():
    taxa.reset_cache()
    yield
    taxa.reset_cache()


def _children(client, key=None):
    return client.get("/api/taxa/children", params={"key": key} if key else {}).json()


def _total(client, *values):
    return client.get("/api/occurrences", params={"taxon": list(values)}).json()["total"]


def test_parse_taxon():
    assert taxa.parse_taxon("Plantae/genus/Arenaria") == ("Plantae", "genus", "Arenaria")
    assert taxa.parse_taxon("Plantae") == ("Plantae", "kingdom", "Plantae")
    # The name keeps any further slashes; an unknown rank is rejected.
    assert taxa.parse_taxon("Plantae/species/A b/c") == ("Plantae", "species", "A b/c")
    assert taxa.parse_taxon("Plantae/tribe/X") is None
    assert taxa.parse_taxon("Plantae/genus/") is None


def test_kingdoms_are_the_roots_largest_first(client):
    res = _children(client)
    assert [(i["key"], i["n"]) for i in res["items"]] == [("Plantae", 4), ("Animalia", 2)]
    assert all(i["has_children"] for i in res["items"])


def test_children_and_unplaced(client):
    orders = _children(client, "Plantae/class/Magnoliopsida")["items"]
    # Largest first, name breaks the tie.
    assert [(i["name"], i["n"]) for i in orders] == [
        ("Asterales", 2), ("Cucurbitales", 1), ("Rosales", 1)]
    # r5 is Animalia and nothing below: counted under the kingdom, not drawn.
    animalia = _children(client, "Animalia")
    assert [i["name"] for i in animalia["items"]] == ["Cnidaria"]
    assert animalia["n_unplaced"] == 1
    # Begonia is a genus-rank record: the genus has no species under it.
    begonia = _children(client, "Plantae/genus/Begonia")
    assert begonia["items"] == [] and begonia["n_unplaced"] == 1
    assert _children(client, "Plantae/genus/Nope") == {"items": [], "n_unplaced": 0}


def test_every_node_count_is_what_its_filter_returns(client):
    """The tree prints a count and selecting the node must reproduce it —
    walked over the whole fixture tree."""
    stack = [None]
    while stack:
        for item in _children(client, stack.pop())["items"]:
            assert _total(client, item["key"]) == item["n"], item["key"]
            stack.append(item["key"])


def test_filter_is_kingdom_qualified_and_ored(client):
    assert _total(client, "Plantae/family/Rosaceae") == 1
    assert _total(client, "Animalia/family/Rosaceae") == 0
    assert _total(client, "Plantae/family/Rosaceae", "Plantae/genus/Helianthus") == 3
    # Unparseable means nothing, not everything.
    assert _total(client, "Plantae/tribe/X") == 0
    # And it ANDs with the other filters like any facet.
    res = client.get("/api/occurrences", params={
        "taxon": "Plantae", "missing_identification": "true"}).json()
    assert {r["id"] for r in res["items"]} == {"r6"}


def test_search_over_latin_and_chinese(client):
    def hits(q):
        return [(h["rank"], h["name"]) for h in client.get("/api/taxa/search", params={"q": q}).json()]

    # Exact before prefix, so the genus heads its own species.
    assert hits("helianthus")[:2] == [("genus", "Helianthus"), ("species", "Helianthus annuus")]
    assert ("family", "Rosaceae") in hits("薔薇")
    assert hits("向日葵") == [("species", "Helianthus annuus")]
    assert hits("   ") == []
    one = client.get("/api/taxa/search", params={"q": "Rosa"}).json()[0]
    assert one["key"] == "Plantae/genus/Rosa"
    assert one["lineage"][:2] == ["Rosaceae", "Rosales"]


def test_species_step_folds_infraspecific_names():
    """A variety belongs to its species: both the rollup's binomial and the
    filter's prefix match say so. Subgenus and hybrid sign are kept."""
    con = duckdb.connect()
    con.execute("CREATE TABLE occurrence (scientific_name VARCHAR, kingdom VARCHAR)")
    names = ["Rosa canina", "Rosa canina var. dumalis", "Rosa caninae",
             "Alpinia × formosana", "Ula (Ula) superelegans", "Rosa"]
    con.executemany("INSERT INTO occurrence VALUES (?, 'Plantae')", [[n] for n in names])
    got = con.execute(f"SELECT scientific_name, {taxa.BINOMIAL} FROM occurrence").fetchall()
    assert dict(got) == {
        "Rosa canina": "Rosa canina", "Rosa canina var. dumalis": "Rosa canina",
        "Rosa caninae": "Rosa caninae", "Alpinia × formosana": "Alpinia × formosana",
        "Ula (Ula) superelegans": "Ula (Ula) superelegans", "Rosa": None,
    }
    sql, params = taxa.taxon_condition("Plantae/species/Rosa canina")
    matched = {r[0] for r in con.execute(f"SELECT scientific_name FROM occurrence WHERE {sql}", params).fetchall()}
    # "Rosa caninae" shares the prefix but is another species.
    assert matched == {"Rosa canina", "Rosa canina var. dumalis"}
