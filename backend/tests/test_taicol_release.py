"""The TaiCOL release behind the identification name picker: seeding derives a
tree from a CSV that has no parent ids, and search / taxon / tree answer from it."""

import csv

import pytest

COLS = ["taxon_id", "name_id", "simple_name", "name_author", "rank", "common_name_c",
        "alternative_name_c", "updated_at", "kingdom", "phylum", "class", "order",
        "family", "family_c", "genus"]
PATH = dict(kingdom="Plantae", phylum="Tracheophyta", **{"class": "Magnoliopsida"},
            order="Cucurbitales", family="Begoniaceae", family_c="秋海棠科", genus="Begonia")
ROWS = [
    ("t0000003", 1, "Plantae", "Haeckel", "Kingdom", "植物界", "", {"kingdom": "Plantae"}),
    ("t0000043", 2, "Tracheophyta", "", "Phylum", "維管束植物門", "", {"kingdom": "Plantae", "phylum": "Tracheophyta"}),
    ("t0000213", 3, "Magnoliopsida", "", "Class", "木蘭綱", "", {**{k: PATH[k] for k in ("kingdom", "phylum", "class")}}),
    ("t0000819", 4, "Cucurbitales", "", "Order", "葫蘆目", "", {**{k: PATH[k] for k in ("kingdom", "phylum", "class", "order")}}),
    ("t0002395", 5, "Begoniaceae", "", "Family", "秋海棠科", "", {**{k: PATH[k] for k in ("kingdom", "phylum", "class", "order", "family", "family_c")}}),
    ("t0099999", 6, "Begonioideae", "", "Subfamily", "", "", {**{k: PATH[k] for k in ("kingdom", "phylum", "class", "order", "family", "family_c")}}),
    ("t0023271", 771, "Begonia", "L.", "Genus", "秋海棠屬", "", PATH),
    ("t0040360", 26079, "Begonia formosana", "(Hayata) Masam.", "Species", "白斑水鴨腳", "水鴨腳", PATH),
    ("t0087756", 9, "Begonia formosana fo. albomaculata", "", "Form", "白斑水鴨腳", "", PATH),
    ("t0052701", 20942, "Begonia grandis", "Dryand.", "Species", "秋海棠", "", PATH),
]


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    from app.seed_taicol import populate

    path = tmp_path_factory.mktemp("taicol") / "TaiCOL_taxon_20261030.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        for tid, nid, name, author, rank, cn, alt, higher in ROWS:
            w.writerow({"taxon_id": tid, "name_id": nid, "simple_name": name, "name_author": author,
                        "rank": rank, "common_name_c": cn, "alternative_name_c": alt,
                        "updated_at": "2026-08-19", **higher})
    return populate(path)


def test_seed_derives_a_tree(client, seeded):
    assert seeded["version"] == "2026-10-30"          # from the filename
    assert seeded["n_taxa"] == len(ROWS)
    assert seeded["orphans"] == 0
    assert client.get("/api/taicol/release").json()["version"] == "2026-10-30"

    roots = client.get("/api/taicol/tree").json()
    assert [r["name"] for r in roots] == ["Plantae"]
    assert roots[0]["n_species"] == 3                   # 2 species + 1 forma

    # A family's children are its genera: the subfamily is searchable, not a node.
    fam = client.get("/api/taicol/tree?parent=t0002395").json()
    assert [n["name"] for n in fam] == ["Begonia"]
    genus = client.get("/api/taicol/tree?parent=t0023271").json()
    assert [n["name"] for n in genus] == ["Begonia formosana", "Begonia grandis"]
    # The forma hangs off its species (the binomial), not the genus.
    sp = client.get("/api/taicol/tree?parent=t0040360").json()
    assert [n["name"] for n in sp] == ["Begonia formosana fo. albomaculata"]
    assert [p["italic"] for p in sp[0]["name_parts"]] == [True, False, True]


def test_suggest_and_taxon_answer_from_the_release(client, seeded):
    hits = client.get("/api/taicol/suggest", params={"q": "秋海棠"}).json()
    assert hits[0]["name"] == "Begonia grandis"         # exact Chinese name first
    hits = client.get("/api/taicol/suggest", params={"q": "begonia form"}).json()
    assert hits[0]["name"] == "Begonia formosana"
    assert "水鴨腳" in hits[0]["common_names"]           # alternative names searchable too
    assert client.get("/api/taicol/suggest", params={"q": "100%"}).json() == []

    t = client.get("/api/taicol/taxon/t0040360").json()
    assert t["scientific_name_id"] == "https://taicol.tw/name/26079"
    assert t["name_according_to"].endswith("https://taicol.tw/taxon/t0040360, version 2026-10-30")
    assert t["path"] == ["t0000003", "t0000043", "t0000213", "t0000819", "t0002395", "t0023271"]
    assert client.get("/api/taicol/taxon/t0000001").status_code == 404


def test_reseeding_replaces_the_release(client, seeded, tmp_path):
    from app.seed_taicol import populate

    path = tmp_path / "TaiCOL_taxon_20270101.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerow({"taxon_id": "t0000003", "name_id": 1, "simple_name": "Plantae", "rank": "Kingdom", "kingdom": "Plantae"})
    # Runs last in this module (it replaces the fixture's release).
    populate(path)
    assert client.get("/api/taicol/release").json()["version"] == "2027-01-01"
    assert client.get("/api/taicol/taxon/t0040360").status_code == 404
