import json
import os

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import duck, search
from ..config import DATA
from ..search import Filters

router = APIRouter(prefix="/api", tags=["occurrences"])


@router.get("/registry")
def registry():
    """Institution / aggregator → dataset registry (data/registry.json)."""
    path = os.path.join(DATA, "registry.json")
    if not os.path.exists(path):
        return {"institutions": {}, "aggregators": {}}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


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
        from ..annotations_store import list_for_occurrence
        record["annotations"] = list_for_occurrence(occ_id)
    except Exception:
        record["annotations"] = []
    return record


@router.get("/datasets")
async def list_datasets(limit: int = Query(default=100, le=1000)):
    return await duck.query(
        """SELECT dataset_name, tbia_dataset_id, rights_holder, n_records,
                  n_identified, n_georeferenced, n_dated, n_with_media, avg_completeness
           FROM datasets ORDER BY n_records DESC LIMIT ?""",
        [limit],
    )
