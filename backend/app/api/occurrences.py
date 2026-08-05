import json
import os

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import duck, search
from ..config import DATA
from ..search import Filters

router = APIRouter(prefix="/api", tags=["occurrences"])


def _registry_file() -> dict:
    path = os.path.join(DATA, "registry.json")
    if not os.path.exists(path):
        return {"institutions": {}, "aggregators": {}}
    with open(path, encoding="utf-8") as f:
        reg = json.load(f)
    reg.setdefault("institutions", {})
    reg.setdefault("aggregators", {})
    return reg


async def _datasets_from_db(known: set[str]) -> dict[str, dict]:
    """Datasets present in the store but not curated in registry.json, grouped
    by institution_code — in practice the GBIF mirrors, whose ids and uuids
    change with every TBIA export. Shaped like a registry.json entry."""
    rows = await duck.query(
        """SELECT institution_code, institution_name, tbia_dataset_id, dataset_name,
                  dataset_code, source_dataset_id, groups
           FROM dataset ORDER BY num_of_rows DESC"""
    )
    out: dict[str, dict] = {}
    for r in rows:
        did = r["tbia_dataset_id"]
        if did in known:
            continue
        code = r["institution_code"] or "OTHER"
        ent = out.setdefault(code, {"name": r["institution_name"] or code, "datasets": {}})
        ds = {"name": r["dataset_name"], "groups": list(r["groups"] or [])}
        if r["dataset_code"]:
            ds["code"] = r["dataset_code"]
        # The GBIF uuid lives in source_dataset_id now — referenced, never pinned.
        if r["source_dataset_id"]:
            ds["gbif"] = r["source_dataset_id"]
        ent["datasets"][did] = ds
    return out


@router.get("/registry")
async def registry():
    """Institution / aggregator → dataset registry.

    registry.json is hand-curated and lists only the *stable* institution
    datasets. Aggregated (GBIF) datasets turn over with every TBIA export, so
    their ids are not stored in the file — they are read from the `dataset`
    table at request time and merged in under `aggregators`. A curated entry
    always wins: anything registry.json already lists is left untouched.
    """
    reg = _registry_file()
    known = {
        did
        for section in ("institutions", "aggregators")
        for src in reg[section].values()
        for did in src.get("datasets", {})
    }
    try:
        discovered = await _datasets_from_db(known)
    except Exception as exc:  # store not ready — serve the curated file alone
        print(f"[registry] could not read datasets from DuckDB: {exc}")
        return reg

    for code, ent in discovered.items():
        target = reg["aggregators"].setdefault(code, {"name": ent["name"], "datasets": {}})
        target.setdefault("datasets", {}).update(ent["datasets"])
    return reg


def filters_dep(
    q: str | None = None,
    bio_group: list[str] = Query(default=[]),
    kingdom_c: list[str] = Query(default=[]),
    county: list[str] = Query(default=[]),
    taxon_rank: list[str] = Query(default=[]),
    basis_of_record: list[str] = Query(default=[]),
    type_status: list[str] = Query(default=[]),
    dataset_name: list[str] = Query(default=[]),
    tbia_dataset_id: list[str] = Query(default=[]),
    collector_id: list[int] = Query(default=[]),
    record_number_from: int | None = None,
    record_number_to: int | None = None,
    record_number: str | None = None,
    missing_coordinates: bool = False,
    missing_date: bool = False,
    missing_identification: bool = False,
    has_media: bool = False,
    year_from: int | None = None,
    year_to: int | None = None,
    bbox: str | None = None,
) -> Filters:
    return Filters(
        q=q, bio_group=bio_group, kingdom_c=kingdom_c, county=county,
        taxon_rank=taxon_rank, basis_of_record=basis_of_record, type_status=type_status,
        dataset_name=dataset_name, tbia_dataset_id=tbia_dataset_id, collector_id=collector_id,
        record_number_from=record_number_from, record_number_to=record_number_to,
        record_number=record_number,
        missing_coordinates=missing_coordinates, missing_date=missing_date,
        missing_identification=missing_identification, has_media=has_media,
        year_from=year_from, year_to=year_to, bbox=bbox,
    )


@router.get("/occurrences")
async def list_occurrences(
    f: Filters = Depends(filters_dep),
    sort: str = "completeness_score",
    order: str = "asc",
    limit: int = Query(default=50, le=500),
    offset: int = 0,
):
    return await search.search(f, sort=sort, order=order, limit=limit, offset=offset)


@router.get("/occurrences/facets")
async def occurrence_facets(f: Filters = Depends(filters_dep)):
    return await search.facets(f)


@router.get("/occurrences/{occ_id}")
async def occurrence_detail(occ_id: str):
    record = await search.get_detail(occ_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Occurrence not found")
    try:
        from ..annotations_store import latest_transcribe_request, list_for_occurrence
        record["annotations"] = list_for_occurrence(occ_id)
        record["transcribe"] = latest_transcribe_request(occ_id)
    except Exception:
        record["annotations"] = []
        record["transcribe"] = None
    return record


@router.get("/datasets")
async def list_datasets(limit: int = Query(default=100, le=1000)):
    """Per-dataset record counts + completeness roll-ups (`ingest/prepare.py`).
    `num_of_rows` keeps its API name `n_records` — the field the UI reads."""
    return await duck.query(
        """SELECT dataset_name, tbia_dataset_id, rights_holder, institution_code,
                  num_of_rows AS n_records, n_identified, n_georeferenced,
                  n_dated, n_with_media, avg_completeness
           FROM dataset ORDER BY num_of_rows DESC LIMIT ?""",
        [limit],
    )
