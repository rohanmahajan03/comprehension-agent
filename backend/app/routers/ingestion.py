"""Pipeline 1 entrypoint: upload a chapter, build its graph, pre-generate questions."""

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import graph_builder, question_generator
from app.store import get_store

router = APIRouter(prefix="/api", tags=["ingestion"])


class TextbookUpload(BaseModel):
    text: str = Field(min_length=1, description="Raw chapter text")
    title: str | None = None


class TextbookUploadResponse(BaseModel):
    doc_id: str


@router.post("/textbook", response_model=TextbookUploadResponse, status_code=201)
def upload_textbook(payload: TextbookUpload) -> TextbookUploadResponse:
    if not payload.text.strip():
        raise HTTPException(status_code=422, detail="Chapter text must not be blank")

    store = get_store()
    doc_id = uuid.uuid4().hex[:12]
    store.save_document(doc_id, payload.text)

    # Synchronous for now; move to a background task/queue once graph building
    # involves real LLM calls.
    graph = graph_builder.build_graph(doc_id, payload.text)
    question_generator.generate_questions(graph)  # populates concept.questions in place
    store.save_graph(graph)
    for concept in graph.concepts:
        store.save_questions(concept.id, concept.questions)

    return TextbookUploadResponse(doc_id=doc_id)
