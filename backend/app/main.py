from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import duck
from .config import settings
from .db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()        # ensure SQLite schema exists before DuckDB attaches it
    duck.connect()
    yield
    duck.close()


app = FastAPI(title="TBIA Specimen Annotation Platform", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok", "annotations_attached": duck.annotations_attached()}


def _mount_routers() -> None:
    from .api import occurrences
    app.include_router(occurrences.router)

    # Annotation / auth / export / collector routers are added as modules land.
    for modname in ("auth", "annotations", "export", "collectors"):
        try:
            mod = __import__(f"app.api.{modname}", fromlist=["router"])
            app.include_router(mod.router)
        except ModuleNotFoundError:
            pass


_mount_routers()
