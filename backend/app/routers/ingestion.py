"""Pipeline 1 entrypoint: upload a chapter, build its graph, pre-generate questions."""

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models import DocumentSummary
from app.services import graph_builder, question_generator
from app.store import get_store

router = APIRouter(prefix="/api", tags=["ingestion"])


class TextbookUpload(BaseModel):
    text: str = Field(min_length=1, description="Raw chapter text")
    title: str | None = None


class TextbookUploadResponse(BaseModel):
    doc_id: str


@router.get("/textbook", response_model=list[DocumentSummary])
def list_textbooks() -> list[DocumentSummary]:
    """Chapters that already have a graph, so the client can start a new session against
    one without re-uploading and re-paying for extraction."""
    return get_store().list_documents()


@router.post("/textbook", response_model=TextbookUploadResponse, status_code=201)
def upload_textbook(payload: TextbookUpload) -> TextbookUploadResponse:
    if not payload.text.strip():
        raise HTTPException(status_code=422, detail="Chapter text must not be blank")

    store = get_store()
    doc_id = uuid.uuid4().hex[:12]
    store.save_document(doc_id, payload.text, payload.title)

    # The document has to be persisted first — concepts reference it by foreign key — but
    # everything after it can fail (both steps are real LLM calls). Without this rollback a
    # failure strands a document row with no concepts, invisible to the app but permanent in
    # the database. Deleting the document cascades away any partial graph/questions too, so
    # a failed upload leaves no trace and the client is free to just retry.
    try:
        # Synchronous for now; move to a background task/queue once graph building
        # involves real LLM calls.
        graph = graph_builder.build_graph(doc_id, payload.text)
        if not graph.concepts:
            # A graph with zero concepts is indistinguishable from "never saved" once
            # persisted (see PostgresStore.get_graph), so a silent 201 here would strand
            # the client with a doc_id that immediately 404s on GET /api/graph/{doc_id}.
            # Surface it as a rejected upload instead — typically means the text has no
            # textbook-style prerequisite structure for graph_builder to extract.
            raise HTTPException(
                status_code=422,
                detail="Couldn't extract any concepts from this text. Try a chapter with "
                "more structured, technical content where ideas build on each other.",
            )
        question_generator.generate_questions(graph)  # populates concept.questions in place
        store.save_graph(graph)
        for concept in graph.concepts:
            store.save_questions(concept.id, concept.questions)
    except Exception:
        store.delete_document(doc_id)
        raise

    return TextbookUploadResponse(doc_id=doc_id)
