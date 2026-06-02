"""Pytest fixtures: a tiny hand-built DuckDB + SQLite, wired into a TestClient.

Env vars are set *before* importing the app so the settings singleton picks up
the temp paths.
"""

import os
import tempfile

import duckdb
import pytest

_tmp = tempfile.mkdtemp(prefix="tbia_test_")
DUCK = os.path.join(_tmp, "occ.duckdb")
SQLITE = os.path.join(_tmp, "ann.sqlite")
os.environ["NDB_DUCKDB_PATH"] = DUCK
os.environ["NDB_SQLITE_PATH"] = SQLITE
os.environ["NDB_JWT_SECRET"] = "test-secret"

# (id, catalog, sci, rank, group, county, locality, lat, lon, date, dataset, media)
ROWS = [
    ("r1", "C-001", "Pocillopora damicornis", "species", "魚類", "新北市", "野柳", 25.2, 121.6, "2004-09-16", "DS-A", "http://x/img1.jpg"),
    ("r2", "C-002", None, "family", "魚類", None, "Taiwan", None, None, None, "DS-A", ""),
    ("r3", "C-003", "Helianthus annuus", "species", "維管束植物", "南投縣", "Forest", 23.9, 120.9, "2019-08-14", "DS-B", ""),
    ("r4", "C-004", "Rosa canina", "species", "維管束植物", None, None, None, None, "2021-06-03", "DS-B", "http://x/img4.jpg"),
    ("r5", "C-005", None, "genus", "昆蟲", "屏東縣", "Kenting", 22.0, 120.8, None, "DS-A", ""),
]


def _build_duckdb() -> None:
    con = duckdb.connect(DUCK)
    con.execute(
        """CREATE TABLE occurrences (
            id VARCHAR, catalog_number VARCHAR, scientific_name VARCHAR, name_author VARCHAR,
            common_name_c VARCHAR, alternative_name_c VARCHAR, source_vernacular_name VARCHAR,
            family VARCHAR, genus VARCHAR, taxon_rank VARCHAR, bio_group VARCHAR, kingdom_c VARCHAR,
            county VARCHAR, municipality VARCHAR, locality VARCHAR, recorded_by VARCHAR, record_number VARCHAR,
            std_lat DOUBLE, std_lon DOUBLE, std_date DATE, event_date VARCHAR, year INTEGER,
            type_status VARCHAR, dataset_name VARCHAR, tbia_dataset_id VARCHAR, basis_of_record VARCHAR,
            rights_holder VARCHAR, resource_contacts VARCHAR, associated_media VARCHAR,
            verbatim_latitude VARCHAR, verbatim_longitude VARCHAR, source_scientific_name VARCHAR,
            has_coordinates BOOLEAN, has_date BOOLEAN, has_identification BOOLEAN, has_media BOOLEAN,
            completeness_score INTEGER
        )"""
    )
    for (rid, cat, sci, rank, grp, county, loc, lat, lon, date, ds, media) in ROWS:
        has_coord = lat is not None and lon is not None
        has_date = date is not None
        has_id = rank in ("species", "subspecies") and sci is not None
        has_media = bool(media)
        score = sum([has_coord, has_date, has_id, has_media])
        con.execute(
            "INSERT INTO occurrences (id, catalog_number, scientific_name, taxon_rank, bio_group,"
            " county, locality, std_lat, std_lon, std_date, year, dataset_name, basis_of_record,"
            " associated_media, source_scientific_name, has_coordinates, has_date, has_identification,"
            " has_media, completeness_score) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [rid, cat, sci, rank, grp, county, loc, lat, lon, date,
             int(date[:4]) if date else None, ds, "PreservedSpecimen", media,
             sci or "Genus species", has_coord, has_date, has_id, has_media, score],
        )
    # recorded_by values exercising the collector parser/seeder.
    con.execute("UPDATE occurrences SET recorded_by = 'Pi-Fong Lu (呂碧鳳)' WHERE id='r1'")
    con.execute("UPDATE occurrences SET recorded_by = '呂碧鳳' WHERE id='r2'")  # same person
    con.execute("UPDATE occurrences SET recorded_by = '亞洲蔬菜研究發展中心' WHERE id='r3'")  # org
    con.execute(
        "UPDATE occurrences SET recorded_by = 'Tian-Chuan Hsu (許天銓), Someone Else' WHERE id='r4'"
    )
    # record_number values for the numeric range filter (r4 non-numeric -> excluded)
    for rid, rn in [("r1", "100"), ("r2", "150"), ("r3", "200"), ("r4", "TAI-9"), ("r5", "250")]:
        con.execute("UPDATE occurrences SET record_number = ? WHERE id = ?", [rn, rid])
    con.execute(
        """CREATE TABLE datasets AS
           SELECT dataset_name, any_value(tbia_dataset_id) tbia_dataset_id,
                  any_value(rights_holder) rights_holder, any_value(resource_contacts) resource_contacts,
                  count(*) n_records, sum(CAST(has_identification AS INT)) n_identified,
                  sum(CAST(has_coordinates AS INT)) n_georeferenced, sum(CAST(has_date AS INT)) n_dated,
                  sum(CAST(has_media AS INT)) n_with_media, round(avg(completeness_score)/4.0,4) avg_completeness
           FROM occurrences GROUP BY dataset_name"""
    )
    con.close()


@pytest.fixture(scope="session")
def client():
    _build_duckdb()
    from fastapi.testclient import TestClient
    from app.main import app
    from app.seed import seed
    from app.seed_collectors import populate

    seed()  # demo users
    populate()  # collector table + aliases (before the app attaches the sqlite)
    with TestClient(app) as c:
        yield c


def auth_header(client, email: str) -> dict:
    res = client.post("/api/auth/login", json={"email": email, "password": "demo1234"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}
