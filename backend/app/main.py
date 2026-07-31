from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import graph, ingestion, questions, study_session

settings = get_settings()

app = FastAPI(title=settings.app_name)

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
