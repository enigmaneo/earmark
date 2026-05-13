from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from earmark.database import init_db
from earmark.routers import alignment, auth, progress, users
from earmark.routers.progress import web_router
from earmark.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()
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


@app.get("/healthcheck")
async def healthcheck() -> dict[str, str]:
    return {"state": "OK"}
