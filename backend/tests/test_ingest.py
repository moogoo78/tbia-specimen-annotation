"""The refresh pipeline: inspect -> (human edits registry.json) -> build -> prepare.

Everything runs against a real CSV and a real DuckDB in a tmp dir — the modules
under test are the ones production runs, and the assertions are about the store
that comes out.

The tiny export below is shaped to exercise every branch at once:

    ds-cur-1        curated, 3 rows, one with an unparseable coord/date
    ds-cur-2        curated, 2 rows under two different sourceDatasetIDs,
                    and renamed upstream (registry says "Old Name Two")
    ds-gbif         uncurated, rightsHolder=GBIF   -> kept by the GBIF rule
    ds-other        uncurated, rightsHolder=TBN    -> dropped
    ds-cur-missing  curated but absent from the export
"""

from __future__ import annotations

import csv
import json
import os

import duckdb
import pytest

from ingest import build as build_mod
from ingest import common
from ingest import inspect as inspect_mod

# basisOfRecord / typeStatus are here because prepare.py indexes them.
HEADER = [
    "id", "tbiaDatasetID", "datasetName", "sourceDatasetID", "gbifDatasetID", "rightsHolder",
    "scientificName", "taxonRank", "bioGroup", "county", "basisOfRecord", "typeStatus",
    "standardDate", "standardLatitude", "standardLongitude", "standardOrganismQuantity",
    "dataGeneralizations", "associatedMedia", "verbatimSRS",
    "class", "order", "references", "match_higher_taxon", "common_name_c",
]

CURATED_1, CURATED_2 = "ds-cur-1", "ds-cur-2"
GBIF_DS, OTHER_DS, MISSING_DS = "ds-gbif", "ds-other", "ds-cur-missing"


def _row(**kw) -> list[str]:
    base = {
        "id": "x", "tbiaDatasetID": CURATED_1, "datasetName": "Curated One",
        "sourceDatasetID": "src-1", "gbifDatasetID": "", "rightsHolder": "Inst A Holder",
        "scientificName": "Rosa canina", "taxonRank": "species", "bioGroup": "被子植物",
        "county": "南投縣", "basisOfRecord": "PreservedSpecimen", "typeStatus": "",
        "standardDate": "2019-08-14 00:00:00", "standardLatitude": "23.9",
        "standardLongitude": "120.9", "standardOrganismQuantity": "1",
        "dataGeneralizations": "false", "associatedMedia": "http://x/1.jpg",
        "verbatimSRS": "WGS84", "class": "Magnoliopsida", "order": "Rosales",
        "references": "http://x/rec/1", "match_higher_taxon": "true",
        "common_name_c": "薔薇",
    }
    base.update(kw)
    return [base[c] for c in HEADER]


ROWS = [
    _row(id="a1"),
    _row(id="a2", associatedMedia="", county="花蓮縣"),
    # Unparseable coordinate + date: TRY_CAST must NULL them, not drop the row.
    _row(id="a3", standardLatitude="not-a-number", standardDate="0000-13-45", taxonRank="genus"),
    _row(id="b1", tbiaDatasetID=CURATED_2, datasetName="Curated Two",
         sourceDatasetID="src-2a", rightsHolder="Inst B Holder"),
    _row(id="b2", tbiaDatasetID=CURATED_2, datasetName="Curated Two",
         sourceDatasetID="src-2b", rightsHolder="Inst B Holder"),
    _row(id="g1", tbiaDatasetID=GBIF_DS, datasetName="GBIF Mirror",
         sourceDatasetID="uuid-gbif", rightsHolder="GBIF"),
    _row(id="g2", tbiaDatasetID=GBIF_DS, datasetName="GBIF Mirror",
         sourceDatasetID="uuid-gbif", rightsHolder="GBIF"),
    _row(id="o1", tbiaDatasetID=OTHER_DS, datasetName="Someone Else's Survey",
         sourceDatasetID="src-o", rightsHolder="台灣生物多樣性網絡 TBN"),
    _row(id="o2", tbiaDatasetID=OTHER_DS, datasetName="Someone Else's Survey",
         sourceDatasetID="src-o", rightsHolder="台灣生物多樣性網絡 TBN"),
]

KEPT = 7  # 3 curated-1 + 2 curated-2 + 2 GBIF; the 2 TBN rows are dropped

REGISTRY = {
    "institutions": {
        "INST_A": {"name": "Institution A", "datasets": {
            CURATED_1: {"code": "AAA", "name": "Curated One", "groups": ["Plantae"]},
            MISSING_DS: {"name": "Gone Dataset", "groups": ["Fungi"]},
        }},
        "INST_B": {"name": "Institution B", "datasets": {
            # Deliberately stale: the export calls this one "Curated Two".
            CURATED_2: {"name": "Old Name Two", "groups": ["Zoology", "Insecta"]},
        }},
    },
    "aggregators": {"GBIF": {"name": "GBIF", "datasets": {}}},
}


# --------------------------------------------------------------------------- fixtures


def _write_csv(path, header=HEADER, rows=ROWS, ragged=False):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow(r)
        if ragged:
            fh.write("short-row,ds-cur-1,Curated One\n")
    return str(path)


@pytest.fixture
def export_csv(tmp_path):
    return _write_csv(tmp_path / "tbia_test.csv")


@pytest.fixture
def registry_path(tmp_path):
    p = tmp_path / "registry.json"
    p.write_text(json.dumps(REGISTRY, ensure_ascii=False), encoding="utf-8")
    return str(p)


@pytest.fixture
def manifest_path(tmp_path):
    """A manifest matching the fixture export, so tests never touch the real one."""
    p = tmp_path / "columns.json"
    p.write_text(json.dumps(HEADER), encoding="utf-8")
    return str(p)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "out.duckdb")


def run_inspect(monkeypatch, export, outdir, registry, manifest, db="/nonexistent.duckdb"):
    monkeypatch.setattr("sys.argv", [
        "inspect", export, "-o", str(outdir),
        "--registry", registry, "--manifest", manifest, "--db", db,
    ])
    inspect_mod.main()
    stem = os.path.splitext(os.path.basename(export))[0]
    return (open(os.path.join(outdir, f"{stem}-summary.md"), encoding="utf-8-sig").read(),
            os.path.join(outdir, f"{stem}-datasets.csv"))


def run_build(monkeypatch, csv_path, db, registry, manifest):
    monkeypatch.setattr("sys.argv", [
        "build", "--csv", csv_path, "--db", db,
        "--registry", registry, "--manifest", manifest,
    ])
    build_mod.main()
    return db


def cols(db, table="occurrence"):
    con = duckdb.connect(db, read_only=True)
    try:
        return [r[0] for r in con.execute(
            "SELECT column_name FROM duckdb_columns() WHERE table_name = ?", [table]
        ).fetchall()]
    finally:
        con.close()


def q(db, sql, params=None):
    con = duckdb.connect(db, read_only=True)
    try:
        return con.execute(sql, params or []).fetchall()
    finally:
        con.close()


# ---------------------------------------------------------------------------- inspect


def test_inspect_totals_and_inventory(monkeypatch, tmp_path, export_csv, registry_path,
                                      manifest_path):
    summary, inventory = run_inspect(monkeypatch, export_csv, tmp_path, registry_path,
                                     manifest_path)
    assert "| Rows (occurrence records) | 9 |" in summary
    assert "| Datasets (`tbiaDatasetID`) | 4 |" in summary
    assert "| Columns | 24 |" in summary
    # Rights holders with shares.
    assert "GBIF" in summary and "22.22%" in summary

    rows = {r["tbiaDatasetID"]: r for r in csv.DictReader(open(inventory, encoding="utf-8-sig"))}
    assert set(rows) == {CURATED_1, CURATED_2, GBIF_DS, OTHER_DS}
    assert rows[CURATED_1]["numOfRows"] == "3"
    assert rows[CURATED_1]["datasetName"] == "Curated One"
    assert rows[GBIF_DS]["sourceDatasetID"] == "uuid-gbif"
    assert rows[GBIF_DS]["rightsHolder"] == "GBIF"


def test_inspect_fills_identifiers_blank_on_first_row(monkeypatch, tmp_path, registry_path,
                                                      manifest_path):
    """A dataset whose first row leaves sourceDatasetID empty still reports it."""
    rows = [_row(id="z1", tbiaDatasetID="ds-late", datasetName="", sourceDatasetID=""),
            _row(id="z2", tbiaDatasetID="ds-late", datasetName="Late Name",
                 sourceDatasetID="src-late")]
    path = _write_csv(tmp_path / "late.csv", rows=rows)
    _, inventory = run_inspect(monkeypatch, path, tmp_path, registry_path, manifest_path)
    entry = {r["tbiaDatasetID"]: r for r in
             csv.DictReader(open(inventory, encoding="utf-8-sig"))}["ds-late"]
    assert entry["datasetName"] == "Late Name"
    assert entry["sourceDatasetID"] == "src-late"


def test_inspect_missing_column_aborts(monkeypatch, tmp_path, registry_path, manifest_path):
    header = [c for c in HEADER if c != "rightsHolder"]
    rows = [[v for c, v in zip(HEADER, r) if c != "rightsHolder"] for r in ROWS]
    path = _write_csv(tmp_path / "broken.csv", header=header, rows=rows)
    with pytest.raises(SystemExit) as exc:
        run_inspect(monkeypatch, path, tmp_path, registry_path, manifest_path)
    assert "rightsHolder" in str(exc.value)
    assert not os.path.exists(tmp_path / "broken-summary.md")


def test_inspect_pads_ragged_rows(monkeypatch, tmp_path, registry_path, manifest_path):
    path = _write_csv(tmp_path / "ragged.csv", ragged=True)
    summary, _ = run_inspect(monkeypatch, path, tmp_path, registry_path, manifest_path)
    assert "| Rows (occurrence records) | 10 |" in summary
    assert "1 row(s) had fewer fields" in summary


def test_inspect_reconciles_against_the_registry(monkeypatch, tmp_path, export_csv,
                                                 registry_path, manifest_path):
    summary, _ = run_inspect(monkeypatch, export_csv, tmp_path, registry_path, manifest_path)

    missing = summary.split("### Curated but missing from this export")[1].split("###")[0]
    assert MISSING_DS in missing and "Gone Dataset" in missing

    new = summary.split("### In this export but not in the registry")[1].split("###")[0]
    assert OTHER_DS in new and "Someone Else's Survey" in new
    # GBIF is counted, not enumerated among the actionable rows.
    assert GBIF_DS not in new
    assert "GBIF-held datasets in this export: **1**" in summary

    renamed = summary.split("### Renamed upstream")[1].split("##")[0]
    assert "Old Name Two" in renamed and "Curated Two" in renamed


def test_inspect_without_a_registry(monkeypatch, tmp_path, export_csv, manifest_path):
    summary, inventory = run_inspect(monkeypatch, export_csv, tmp_path,
                                     str(tmp_path / "no-such-registry.json"), manifest_path)
    assert "not found" in summary
    assert os.path.exists(inventory)


def test_inspect_reports_column_drift_but_still_succeeds(monkeypatch, tmp_path, export_csv,
                                                         registry_path):
    stale = tmp_path / "stale-columns.json"
    stale.write_text(json.dumps([c for c in HEADER if c != "county"] + ["retiredField"]),
                     encoding="utf-8")
    summary, inventory = run_inspect(monkeypatch, export_csv, tmp_path, registry_path, str(stale))
    assert "`county`" in summary and "`retiredField`" in summary
    assert "will abort" in summary
    assert os.path.exists(inventory)  # reporting only — exits 0


def test_inspect_reports_matching_columns(monkeypatch, tmp_path, export_csv, registry_path,
                                          manifest_path):
    summary, _ = run_inspect(monkeypatch, export_csv, tmp_path, registry_path, manifest_path)
    assert "Matches the baseline." in summary


def test_inspect_without_a_baseline(monkeypatch, tmp_path, export_csv, registry_path):
    summary, _ = run_inspect(monkeypatch, export_csv, tmp_path, registry_path,
                             str(tmp_path / "no-such-manifest.json"))
    assert "No column baseline found" in summary
    assert "tbiaDatasetID" in summary  # lists what the export has


def test_inspect_leaves_the_registry_alone(monkeypatch, tmp_path, export_csv, registry_path,
                                           manifest_path):
    before = open(registry_path, encoding="utf-8").read()
    run_inspect(monkeypatch, export_csv, tmp_path, registry_path, manifest_path)
    assert open(registry_path, encoding="utf-8").read() == before


# ------------------------------------------------------------------------------ build


def test_build_keeps_registry_and_gbif_rows_only(monkeypatch, export_csv, db_path,
                                                 registry_path, manifest_path):
    run_build(monkeypatch, export_csv, db_path, registry_path, manifest_path)
    kept = {r[0] for r in q(db_path, "SELECT DISTINCT tbia_dataset_id FROM occurrence")}
    assert kept == {CURATED_1, CURATED_2, GBIF_DS}
    assert q(db_path, "SELECT count(*) FROM occurrence")[0][0] == KEPT


def test_build_drops_a_dataset_removed_from_the_registry(monkeypatch, tmp_path, export_csv,
                                                         db_path, manifest_path):
    trimmed = json.loads(json.dumps(REGISTRY))
    del trimmed["institutions"]["INST_B"]["datasets"][CURATED_2]
    reg = tmp_path / "trimmed.json"
    reg.write_text(json.dumps(trimmed, ensure_ascii=False), encoding="utf-8")

    run_build(monkeypatch, export_csv, db_path, str(reg), manifest_path)
    kept = {r[0] for r in q(db_path, "SELECT DISTINCT tbia_dataset_id FROM occurrence")}
    assert CURATED_2 not in kept
    assert q(db_path, "SELECT count(*) FROM occurrence")[0][0] == KEPT - 2


def test_build_mirrors_the_export_columns(monkeypatch, export_csv, db_path, registry_path,
                                          manifest_path):
    run_build(monkeypatch, export_csv, db_path, registry_path, manifest_path)
    have = cols(db_path)
    for raw in HEADER:
        assert common.camel_to_snake(raw) in have, raw
    # The mechanical transformation, including the awkward ones.
    for expected in ("tbia_dataset_id", "verbatim_srs", "bio_group", "match_higher_taxon",
                     "common_name_c", "class", "order", "references"):
        assert expected in have
    # Plus exactly the four the build adds.
    assert set(have) - {common.camel_to_snake(c) for c in HEADER} == set(common.BUILD_ADDED)


def test_build_types_and_try_cast(monkeypatch, export_csv, db_path, registry_path,
                                  manifest_path):
    run_build(monkeypatch, export_csv, db_path, registry_path, manifest_path)
    types = dict(q(db_path, """SELECT column_name, data_type FROM duckdb_columns()
                               WHERE table_name = 'occurrence'"""))
    assert types["standard_latitude"] == "DOUBLE"
    assert types["standard_longitude"] == "DOUBLE"
    assert types["standard_organism_quantity"] == "DOUBLE"
    assert types["standard_date"] == "TIMESTAMP"
    assert types["data_generalizations"] == "BOOLEAN"
    assert types["match_higher_taxon"] == "BOOLEAN"
    assert types["county"] == "VARCHAR"
    assert types["references"] == "VARCHAR"

    # The bad row survives; only its unparseable fields are NULL.
    row = q(db_path, """SELECT standard_latitude, standard_date, standard_longitude, county
                        FROM occurrence WHERE id = 'a3'""")
    assert len(row) == 1
    lat, date, lon, county = row[0]
    assert lat is None and date is None
    assert lon == 120.9 and county == "南投縣"


def test_build_attributes_rows_from_the_registry(monkeypatch, export_csv, db_path,
                                                 registry_path, manifest_path):
    run_build(monkeypatch, export_csv, db_path, registry_path, manifest_path)
    code, name, ds_code, groups = q(db_path, """SELECT institution_code, institution_name,
                                                       dataset_code, groups
                                                FROM occurrence WHERE id = 'a1'""")[0]
    assert (code, name, ds_code) == ("INST_A", "Institution A", "AAA")
    assert list(groups) == ["Plantae"]

    code, name, ds_code, groups = q(db_path, """SELECT institution_code, institution_name,
                                                       dataset_code, groups
                                                FROM occurrence WHERE id = 'g1'""")[0]
    assert (code, name, ds_code, groups) == ("GBIF", "GBIF", None, None)

    groups = q(db_path, "SELECT groups FROM occurrence WHERE id = 'b1'")[0][0]
    assert list(groups) == ["Zoology", "Insecta"]


def test_build_dataset_rollup(monkeypatch, export_csv, db_path, registry_path, manifest_path):
    run_build(monkeypatch, export_csv, db_path, registry_path, manifest_path)
    rolled = q(db_path, "SELECT coalesce(sum(num_of_rows), 0) FROM dataset")[0][0]
    assert rolled == q(db_path, "SELECT count(*) FROM occurrence")[0][0] == KEPT

    by_id = {r[0]: r for r in q(db_path, """SELECT tbia_dataset_id, in_registry, num_of_rows,
                                                   n_source_dataset_ids, dataset_name
                                            FROM dataset""")}
    assert set(by_id) == {CURATED_1, CURATED_2, GBIF_DS}
    assert by_id[CURATED_1][1] is True and by_id[CURATED_1][2] == 3
    assert by_id[GBIF_DS][1] is False and by_id[GBIF_DS][2] == 2
    # ds-cur-2 carries two distinct sourceDatasetIDs.
    assert by_id[CURATED_2][3] == 2
    assert by_id[CURATED_1][3] == 1
    # The name comes from the export, not the stale registry entry.
    assert by_id[CURATED_2][4] == "Curated Two"


def test_build_replaces_an_existing_store(monkeypatch, tmp_path, export_csv, db_path,
                                          registry_path, manifest_path):
    run_build(monkeypatch, export_csv, db_path, registry_path, manifest_path)
    smaller = _write_csv(tmp_path / "smaller.csv", rows=ROWS[:1])
    run_build(monkeypatch, smaller, db_path, registry_path, manifest_path)
    assert q(db_path, "SELECT count(*) FROM occurrence")[0][0] == 1


def test_build_rejects_a_dataset_claimed_twice(monkeypatch, tmp_path, export_csv, db_path,
                                               manifest_path):
    dupe = json.loads(json.dumps(REGISTRY))
    dupe["institutions"]["INST_B"]["datasets"][CURATED_1] = {"name": "Also Mine"}
    reg = tmp_path / "dupe.json"
    reg.write_text(json.dumps(dupe, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        run_build(monkeypatch, export_csv, db_path, str(reg), manifest_path)
    assert CURATED_1 in str(exc.value)
    assert not os.path.exists(db_path)


@pytest.mark.parametrize("content", [None, "{not json"])
def test_build_rejects_a_bad_registry_without_touching_the_store(
        monkeypatch, tmp_path, export_csv, db_path, registry_path, manifest_path, content):
    run_build(monkeypatch, export_csv, db_path, registry_path, manifest_path)
    before = q(db_path, "SELECT count(*) FROM occurrence")[0][0]

    bad = tmp_path / "bad.json"
    if content is not None:
        bad.write_text(content, encoding="utf-8")
    with pytest.raises(SystemExit):
        run_build(monkeypatch, export_csv, db_path, str(bad), manifest_path)
    assert q(db_path, "SELECT count(*) FROM occurrence")[0][0] == before


# ----------------------------------------------------------------------- column guard


def _csv_with_columns(tmp_path, name, rename=None, drop=None, reorder=False):
    header = list(HEADER)
    rows = [list(r) for r in ROWS]
    if rename:
        header[header.index(rename[0])] = rename[1]
    if drop:
        i = header.index(drop)
        header.pop(i)
        rows = [r[:i] + r[i + 1:] for r in rows]
    if reorder:
        order = list(range(len(header)))[::-1]
        header = [header[i] for i in order]
        rows = [[r[i] for i in order] for r in rows]
    return _write_csv(tmp_path / name, header=header, rows=rows)


def test_build_aborts_on_an_added_column(monkeypatch, tmp_path, db_path, registry_path,
                                         manifest_path):
    path = _csv_with_columns(tmp_path, "added.csv", rename=("county", "newField"))
    with pytest.raises(SystemExit) as exc:
        run_build(monkeypatch, path, db_path, registry_path, manifest_path)
    assert "Refusing to build" in str(exc.value)
    assert not os.path.exists(db_path)


def test_build_aborts_on_a_removed_column(monkeypatch, tmp_path, db_path, registry_path,
                                          manifest_path):
    path = _csv_with_columns(tmp_path, "removed.csv", drop="county")
    with pytest.raises(SystemExit):
        run_build(monkeypatch, path, db_path, registry_path, manifest_path)
    assert not os.path.exists(db_path)


def test_rename_reports_one_added_and_one_removed(capsys, tmp_path, monkeypatch, db_path,
                                                  registry_path, manifest_path):
    path = _csv_with_columns(tmp_path, "renamed.csv", rename=("standardDate", "collectionDate"))
    with pytest.raises(SystemExit):
        run_build(monkeypatch, path, db_path, registry_path, manifest_path)
    err = capsys.readouterr().err
    assert "+ collectionDate" in err
    assert "- standardDate" in err


def test_reordered_columns_still_build(monkeypatch, tmp_path, db_path, registry_path,
                                       manifest_path):
    path = _csv_with_columns(tmp_path, "reordered.csv", reorder=True)
    run_build(monkeypatch, path, db_path, registry_path, manifest_path)
    assert q(db_path, "SELECT count(*) FROM occurrence")[0][0] == KEPT
    assert q(db_path, "SELECT county FROM occurrence WHERE id = 'a1'")[0][0] == "南投縣"


def test_an_abort_leaves_the_existing_store_servable(monkeypatch, tmp_path, export_csv,
                                                     db_path, registry_path, manifest_path):
    run_build(monkeypatch, export_csv, db_path, registry_path, manifest_path)
    before = q(db_path, "SELECT count(*) FROM occurrence")[0][0]

    path = _csv_with_columns(tmp_path, "drifted.csv", rename=("county", "newField"))
    with pytest.raises(SystemExit):
        run_build(monkeypatch, path, db_path, registry_path, manifest_path)
    assert q(db_path, "SELECT count(*) FROM occurrence")[0][0] == before


def test_editing_the_manifest_accepts_the_change(monkeypatch, tmp_path, db_path,
                                                 registry_path, manifest_path):
    path = _csv_with_columns(tmp_path, "accepted.csv", rename=("county", "newField"))
    with pytest.raises(SystemExit):
        run_build(monkeypatch, path, db_path, registry_path, manifest_path)

    accepted = [("newField" if c == "county" else c) for c in HEADER]
    open(manifest_path, "w", encoding="utf-8").write(json.dumps(accepted))
    run_build(monkeypatch, path, db_path, registry_path, manifest_path)
    assert "new_field" in cols(db_path)


def test_baseline_falls_back_to_the_existing_store(monkeypatch, tmp_path, export_csv, db_path,
                                                   registry_path, manifest_path):
    """With no manifest, the store's own occurrence columns are the baseline."""
    run_build(monkeypatch, export_csv, db_path, registry_path, manifest_path)
    os.remove(manifest_path)

    drifted = _csv_with_columns(tmp_path, "drift2.csv", rename=("county", "newField"))
    with pytest.raises(SystemExit):
        run_build(monkeypatch, drifted, db_path, registry_path, manifest_path)
    assert not os.path.exists(manifest_path)  # the fallback never records one

    # The unchanged export still matches that same fallback baseline.
    run_build(monkeypatch, export_csv, db_path, registry_path, manifest_path)
    assert q(db_path, "SELECT count(*) FROM occurrence")[0][0] == KEPT


def test_first_build_records_the_baseline(monkeypatch, tmp_path, export_csv, db_path,
                                          registry_path):
    manifest = str(tmp_path / "fresh-columns.json")
    run_build(monkeypatch, export_csv, db_path, registry_path, manifest)
    assert json.load(open(manifest, encoding="utf-8")) == HEADER


# ---------------------------------------------------------------------------- prepare


def test_built_store_needs_prepare_before_it_can_be_served(monkeypatch, export_csv, db_path,
                                                           registry_path, manifest_path):
    from ingest.prepare import prepare

    run_build(monkeypatch, export_csv, db_path, registry_path, manifest_path)
    assert not (set(common.PREPARE_ADDED) & set(cols(db_path)))

    prepare(db_path)
    assert set(common.PREPARE_ADDED) <= set(cols(db_path))

    # a1 is complete on all four axes. a3 lost its coordinate and date to TRY_CAST
    # and is only identified to genus, so media is all it has left.
    scores = dict(q(db_path, "SELECT id, completeness_score FROM occurrence"))
    assert scores["a1"] == 4
    assert scores["a3"] == 1
    assert scores["a2"] == 3  # everything but media
    assert dict(q(db_path, "SELECT id, year FROM occurrence"))["a1"] == 2019

    # And the per-dataset roll-ups the dashboard reads.
    rollup = q(db_path, """SELECT n_identified, n_georeferenced, n_dated, n_with_media,
                                  avg_completeness
                           FROM dataset WHERE tbia_dataset_id = ?""", [CURATED_1])[0]
    assert rollup[0] == 2  # a3 is rank 'genus' — not identified to species
    assert rollup[1] == 2 and rollup[2] == 2 and rollup[3] == 2
    assert 0 < rollup[4] <= 1
