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
    # r4 carries two media URLs — the multi-image case the AI routes have to
    # read together (one specimen, several views), not just the first one.
    ("r4", "C-004", "Rosa canina", "species", "維管束植物", None, None, None, None, "2021-06-03", "DS-B", "http://x/img4.jpg;http://x/img4b.jpg"),
    ("r5", "C-005", None, "genus", "昆蟲", "屏東縣", "Kenting", 22.0, 120.8, None, "DS-A", ""),
    # r6/r7 exist for the species index: r6 is a *named* genus-rank row (r2 and
    # r5 are coarse but unnamed, so neither reaches the index), and r7 repeats
    # r3's name so one index row has to cover two records.
    ("r6", "C-006", "Begonia", "genus", "維管束植物", "南投縣", "Forest", 23.8, 120.8, "2018-05-02", "DS-B", ""),
    ("r7", "C-007", "Helianthus annuus", "species", "維管束植物", "台中市", "Farm", 24.1, 120.7, "2020-07-01", "DS-B", ""),
]


def _build_duckdb() -> None:
    """Build the two raw tables the TBIA ETL exports, then run the real
    ``ingest/prepare.py`` over them so the completeness flags under test are
    derived exactly the way production derives them."""
    from ingest.prepare import prepare

    con = duckdb.connect(DUCK)
    con.execute(
        """CREATE TABLE occurrence (
            id VARCHAR, catalog_number VARCHAR, scientific_name VARCHAR, name_author VARCHAR,
            common_name_c VARCHAR, alternative_name_c VARCHAR, source_vernacular_name VARCHAR,
            family VARCHAR, genus VARCHAR, taxon_rank VARCHAR, bio_group VARCHAR, kingdom_c VARCHAR,
            county VARCHAR, municipality VARCHAR, locality VARCHAR, recorded_by VARCHAR, record_number VARCHAR,
            standard_latitude DOUBLE, standard_longitude DOUBLE, standard_date TIMESTAMP,
            event_date VARCHAR, type_status VARCHAR, dataset_name VARCHAR, tbia_dataset_id VARCHAR,
            basis_of_record VARCHAR, rights_holder VARCHAR, resource_contacts VARCHAR,
            associated_media VARCHAR, verbatim_latitude VARCHAR, verbatim_longitude VARCHAR,
            source_scientific_name VARCHAR
        )"""
    )
    for (rid, cat, sci, rank, grp, county, loc, lat, lon, date, ds, media) in ROWS:
        con.execute(
            "INSERT INTO occurrence (id, catalog_number, scientific_name, taxon_rank, bio_group,"
            " county, locality, standard_latitude, standard_longitude, standard_date, dataset_name,"
            " tbia_dataset_id, basis_of_record, associated_media, source_scientific_name)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [rid, cat, sci, rank, grp, county, loc, lat, lon, date, ds, ds,
             "PreservedSpecimen", media, sci or "Genus species"],
        )
    # recorded_by values exercising the collector parser/seeder.
    con.execute("UPDATE occurrence SET recorded_by = 'Pi-Fong Lu (呂碧鳳)' WHERE id='r1'")
    con.execute("UPDATE occurrence SET recorded_by = '呂碧鳳' WHERE id='r2'")  # same person
    con.execute("UPDATE occurrence SET recorded_by = '亞洲蔬菜研究發展中心' WHERE id='r3'")  # org
    con.execute(
        "UPDATE occurrence SET recorded_by = 'Tian-Chuan Hsu (許天銓), Someone Else' WHERE id='r4'"
    )
    # record_number values for the numeric range filter (r4 non-numeric -> excluded)
    for rid, rn in [("r1", "100"), ("r2", "150"), ("r3", "200"), ("r4", "TAI-9"), ("r5", "250")]:
        con.execute("UPDATE occurrence SET record_number = ? WHERE id = ?", [rn, rid])
    # The ETL's per-dataset table. Neither test dataset is in registry.json, so
    # both reach /api/registry through the DB-discovery path.
    con.execute(
        """CREATE TABLE dataset AS
           SELECT tbia_dataset_id, any_value(dataset_name) dataset_name,
                  'src-' || tbia_dataset_id AS source_dataset_id,
                  NULL::VARCHAR AS gbif_dataset_id, any_value(rights_holder) rights_holder,
                  'TEST' AS institution_code, 'Test Institution' AS institution_name,
                  NULL::VARCHAR AS dataset_code, ['Plantae'] AS groups,
                  FALSE AS in_registry, count(*) AS num_of_rows
           FROM occurrence GROUP BY tbia_dataset_id"""
    )
    con.close()
    prepare(DUCK)



# A miniature chronology, shaped like data/sampling_events.json. Covers the cases
# the real transcription exercises: a single year, a year range, an elided
# century, a multi-actor party, and actors that do and do not resolve to a
# collector. The two resolving names are the fixture's own collectors (r1/r2 map
# to 呂碧鳳, r4 to 許天銓).
SAMPLING_EVENTS = {
    "source": {"citation": "測試來源, 1975; 測試, 1983"},
    "events": [
        {
            "seq": 1, "source_page": 1,
            "verbatim_event_date": "1901", "event_date": "1901",
            "year_start": 1901, "year_end": 1901,
            "verbatim_locality": "淡水", "event_remarks": "英國",
            "narrative": "採集於淡水。",
            "actors": [{"recorded_by": "呂碧鳳", "nationality": "中", "position": 0}],
        },
        {
            "seq": 2, "source_page": 1,
            "verbatim_event_date": "1905-1910", "event_date": "1905/1910",
            "year_start": 1905, "year_end": 1910,
            "verbatim_locality": "基隆", "event_remarks": "",
            "narrative": "遠征高山。",
            # A party: one actor resolves, one does not. 許天銓 is deliberately
            # left out of the whole chronology so tests have a collector that
            # the literature never names.
            "actors": [
                {"recorded_by": "呂碧鳳", "nationality": "中", "position": 0},
                {"recorded_by": "Ghost Collector", "nationality": "英", "position": 1},
            ],
        },
        {
            "seq": 3, "source_page": 2,
            "verbatim_event_date": "1960-62", "event_date": "1960/1962",
            "year_start": 1960, "year_end": 1962,
            "verbatim_locality": "", "event_remarks": "林業部",
            "narrative": "台灣木本植物圖誌出版",
            # Deliberately per-row, overriding source.citation.
            "location_according_to": "另一來源, 1990",
            "actors": [{"recorded_by": "群體計劃", "nationality": "中", "position": 0}],
        },
    ],
}

SAMPLING_JSON = os.path.join(_tmp, "sampling_events.json")


def write_sampling_events(doc=None) -> str:
    """Write the fixture chronology to the temp dir; return its path."""
    import json
    with open(SAMPLING_JSON, "w", encoding="utf-8") as fh:
        json.dump(doc if doc is not None else SAMPLING_EVENTS, fh, ensure_ascii=False)
    return SAMPLING_JSON


@pytest.fixture(scope="session")
def client():
    _build_duckdb()
    from fastapi.testclient import TestClient
    from app.main import app
    from app.seed import seed
    from app.seed_collectors import populate

    from app.seed_sampling_events import populate as populate_events

    seed()  # demo users
    populate()  # collector table + aliases (before the app attaches the sqlite)
    populate_events(write_sampling_events())  # curated chronology (needs collectors)
    with TestClient(app) as c:
        yield c


def auth_header(client, email: str) -> dict:
    """Mint a JWT for a seeded user directly (sign-in is ORCID-only, so there is
    no password endpoint to exercise here)."""
    from sqlalchemy import select

    from app import auth
    from app.db import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one()
        token = auth.create_token(user)
    return {"Authorization": f"Bearer {token}"}
