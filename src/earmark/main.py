import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from earmark.app_settings import get_effective_int, seed_settings
from earmark.config import settings
from earmark.database import AsyncSessionLocal, init_db
from earmark.routers import alignment, auth, mappings, progress, users
from earmark.routers import settings as settings_router
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
    async with AsyncSessionLocal() as session:
        await seed_settings(session)
        interval = await get_effective_int(
            "sync_interval_seconds", settings.sync_interval_seconds, session
        )
    await recover_orphaned_jobs()
    start_scheduler(interval)
    yield
    stop_scheduler()


app = FastAPI(title="earmark", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Headers and paths whose contents must never be written to logs.
_REDACTED_HEADERS = {"authorization", "x-auth-key", "cookie", "set-cookie"}
_SENSITIVE_BODY_PATHS = {"/auth/login", "/auth/register", "/users/create"}


@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    if not settings.log_requests:
        return await call_next(request)
    body = await request.body()
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    if request.url.path in _SENSITIVE_BODY_PATHS:
        body_str = "<redacted>"
    else:
        body_str = body.decode("utf-8", errors="replace") if body else ""
    headers_str = {
        k: ("<redacted>" if k.lower() in _REDACTED_HEADERS else v)
        for k, v in request.headers.items()
    }
    logger.info("%s %s → %d (%.1f ms) headers=%s body=%s", request.method, request.url.path, response.status_code, ms, headers_str, body_str)
    return response


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(progress.router)
app.include_router(web_router)
app.include_router(alignment.router)
app.include_router(mappings.router)
app.include_router(settings_router.router)


@app.get("/healthcheck")
async def healthcheck(response: Response) -> dict[str, str]:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Healthcheck DB connectivity failed")
        response.status_code = 503
        return {"state": "ERROR", "detail": "database unreachable"}
    return {"state": "OK"}
