from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import duck
from .cache import cache_control_middleware
from .config import settings
from .db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()        # ensure SQLite schema exists before DuckDB attaches it
    duck.connect()
    yield
    duck.close()


app = FastAPI(title="ISLAND — TBIA Specimen Label Annotation Platform", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Added last, so it is outermost and stamps every response -- including the ones
# the exception handlers below produce.
app.middleware("http")(cache_control_middleware)


# Load shedding from duck.py surfaces as 503/504 rather than a hung request.
# Retry-After is the part that matters for the traffic this exists for: a
# crawler reads it and backs off, where a bare 5xx just gets retried at once.
@app.exception_handler(duck.DuckOverloaded)
async def _overloaded(request: Request, exc: duck.DuckOverloaded) -> JSONResponse:
    return JSONResponse(
        {"detail": "Server busy, please retry shortly."},
        status_code=503,
        headers={"Retry-After": "30"},
    )


@app.exception_handler(duck.DuckTimeout)
async def _query_timeout(request: Request, exc: duck.DuckTimeout) -> JSONResponse:
    return JSONResponse(
        {"detail": "Query took too long. Try narrowing the filters."},
        status_code=504,
    )


@app.get("/api/health")
async def health():
    # Both stores are reported: a blank /collectors or /history is almost always
    # a reference store that was never seeded, and this is where you see that
    # without shelling into the box.
    return {
        "status": "ok",
        "annotations_attached": duck.annotations_attached(),
        "reference_attached": duck.reference_attached(),
    }


def _mount_routers() -> None:
    from .api import occurrences
    app.include_router(occurrences.router)

    # Annotation / auth / export / collector routers are added as modules land.
    for modname in ("auth", "annotations", "export", "collectors", "volunteers",
                    "sampling_events", "stories", "species"):
        try:
            mod = __import__(f"app.api.{modname}", fromlist=["router"])
            app.include_router(mod.router)
        except ModuleNotFoundError:
            pass


_mount_routers()
