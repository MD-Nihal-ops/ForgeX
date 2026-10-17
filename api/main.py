"""FastAPI application entry point for ForgeX."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.database import close_database, initialize_schema
from api.routes_brief import router as brief_router
from api.routes_analysis import router as analysis_router
from api.routes_design import router as design_router
from api.routes_exports import router as exports_router
from api.schemas import HealthResponse
from core.data_loader import CatalogError, load_components, load_materials

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await initialize_schema()
    yield
    await close_database()


app = FastAPI(
    title="ForgeX API",
    description="Backend API for the ForgeX engineering brief and deterministic design workflow.",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def disable_workbench_cache(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    response = await call_next(request)
    if request.url.path == "/app" or request.url.path.startswith("/app/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


app.include_router(brief_router)
app.include_router(design_router)
app.include_router(exports_router)
app.include_router(analysis_router)


@app.get("/app/", include_in_schema=False)
def workbench_shell() -> FileResponse:
    return FileResponse(
        Path(__file__).resolve().parent.parent / "frontend_web" / "app.html",
        media_type="text/html",
    )


app.mount(
    "/app",
    StaticFiles(directory=Path(__file__).resolve().parent.parent / "frontend_web", html=True),
    name="frontend_web",
)


@app.get("/", include_in_schema=False)
def workbench_redirect() -> RedirectResponse:
    return RedirectResponse(url="/app/")


@app.get("/api/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    try:
        load_materials()
        load_components()
    except CatalogError:
        return HealthResponse(status="degraded", engine_loaded=False)
    return HealthResponse(status="ok", engine_loaded=True)
