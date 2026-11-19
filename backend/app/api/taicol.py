"""TaiCOL name lookups for the identification form (see app/taicol.py)."""

from fastapi import APIRouter, HTTPException, Query

from .. import taicol

router = APIRouter(prefix="/api/taicol", tags=["taicol"])


def _unavailable(e: taicol.TaicolUnavailable) -> HTTPException:
    # 502, not 500: the fault is upstream, and the form treats it as "type the
    # name by hand", which is exactly what it offered before TaiCOL was wired in.
    return HTTPException(status_code=502, detail=str(e))


@router.get("/suggest")
async def suggest(q: str = Query(min_length=1, max_length=100),
                  lang: str = Query(default="zh-hant", pattern="^(zh-hant|en-us)$")):
    try:
        return await taicol.suggest(q, lang)
    except taicol.TaicolUnavailable as e:
        raise _unavailable(e)


@router.get("/taxon/{taxon_id}")
async def taxon(taxon_id: str):
    try:
        t = await taicol.taxon(taxon_id)
    except taicol.TaicolUnavailable as e:
        raise _unavailable(e)
    if t is None:
        raise HTTPException(status_code=404, detail="No such TaiCOL taxon")
    return t


@router.get("/tree")
def tree(parent: str | None = Query(default=None, pattern=r"^t\d{7}$")):
    """One level of the TaiCOL tree (roots without `parent`). Local release only:
    503 until `make seed-taicol` has run, which the form reads as "no tree"."""
    nodes = taicol.tree(parent)
    if nodes is None:
        raise HTTPException(status_code=503, detail="TaiCOL release not loaded (make seed-taicol)")
    return nodes


@router.get("/release")
def release():
    """Which TaiCOL release the picker answers from (null = live fallback)."""
    return taicol.release()
