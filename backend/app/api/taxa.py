"""The taxon tree and taxon search behind Explore's 分類群 section. See `app/taxa.py`."""

from __future__ import annotations

from fastapi import APIRouter, Query

from .. import taxa

router = APIRouter(prefix="/api", tags=["taxa"])


@router.get("/taxa/children")
async def taxon_children(key: str | None = Query(default=None, description="Kingdom/rank/Name; omit for the kingdoms")):
    return await taxa.children(key)


@router.get("/taxa/search")
async def taxon_search(q: str = "", limit: int = Query(default=20, ge=1, le=50)):
    return await taxa.search(q, limit)
