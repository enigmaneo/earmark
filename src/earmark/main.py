import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
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

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(progress.router)
app.include_router(web_router)
app.include_router(alignment.router)
app.include_router(mappings.router)


@app.get("/healthcheck")
async def healthcheck() -> dict[str, str]:
    return {"state": "OK"}
