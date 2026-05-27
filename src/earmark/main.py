import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from earmark.config import settings
from earmark.database import init_db
from earmark.routers import alignment, auth, mappings, progress, users
from earmark.routers.progress import web_router
from earmark.scheduler import start_scheduler, stop_scheduler
from earmark.services.alignment import recover_orphaned_jobs


def _configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    if settings.log_pretty:
        from rich.logging import RichHandler
        logging.basicConfig(
            level=level,
            format="%(message)s",
            datefmt="[%X]",
            handlers=[RichHandler(rich_tracebacks=True)],
        )
    else:
        logging.basicConfig(level=level)


_configure_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()
    await recover_orphaned_jobs()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="earmark", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    if not settings.log_requests:
        return await call_next(request)
    body = await request.body()
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    body_str = body.decode("utf-8", errors="replace") if body else ""
    headers_str = dict(request.headers)
    logger.info("%s %s → %d (%.1f ms) headers=%s body=%s", request.method, request.url.path, response.status_code, ms, headers_str, body_str)
    return response


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(progress.router)
app.include_router(web_router)
app.include_router(alignment.router)
app.include_router(mappings.router)


@app.get("/healthcheck")
async def healthcheck() -> dict[str, str]:
    return {"state": "OK"}
