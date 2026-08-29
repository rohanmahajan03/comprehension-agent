from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import graph, ingestion, questions, study_session

settings = get_settings()


def _run_migrations() -> None:
    """`alembic upgrade head`, invoked programmatically so it always runs against the exact
    same DATABASE_URL the app itself uses (app.config.get_settings(), read in alembic/env.py)
    rather than a separately-configured path. A dev-focused, single-instance project — the
    convenience of `docker compose up` always landing on an up-to-date schema outweighs the
    explicitness a separate manual step would buy in a team/production setting.
    """
    alembic_ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    command.upgrade(Config(str(alembic_ini)), "head")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if settings.database_url:
        _run_migrations()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingestion.router)
app.include_router(graph.router)
app.include_router(questions.router)
app.include_router(study_session.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
