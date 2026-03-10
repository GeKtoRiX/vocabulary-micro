"""FastAPI application factory with lifespan management."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.dependencies import init_dependencies, shutdown_dependencies
from api.routes import parse, lexicon, assignments, statistics, system


@asynccontextmanager
async def lifespan(app: FastAPI):
    from infrastructure.bootstrap.web_builder import build_web_components
    components = build_web_components()
    init_dependencies(components)
    yield
    shutdown_dependencies()


app = FastAPI(title="Vocabulary Manager API", lifespan=lifespan)

app.include_router(parse.router, prefix="/api")
app.include_router(lexicon.router, prefix="/api")
app.include_router(assignments.router, prefix="/api")
app.include_router(statistics.router, prefix="/api")
app.include_router(system.router, prefix="/api")

# Serve built React app as static files (if it exists)
_web_dist = Path(__file__).resolve().parents[1] / "web" / "dist"
if _web_dist.exists():
    app.mount("/", StaticFiles(directory=str(_web_dist), html=True), name="static")
