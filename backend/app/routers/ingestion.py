"""Pipeline 1 entrypoint: upload a chapter, build its graph, pre-generate questions."""

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models import DependencyGraph, DocumentStatus, DocumentSummary
from app.services import graph_builder, question_generator
from app.store import Store, get_store

router = APIRouter(prefix="/api", tags=["ingestion"])


class TextbookUpload(BaseModel):
    text: str = Field(min_length=1, description="Raw chapter text")
    title: str | None = None
    review: bool = Field(
        default=False,
        description="Stop after graph extraction so the concept graph can be edited, "
        "instead of generating questions immediately. The chapter stays a DRAFT until "
        "POST /api/textbook/{doc_id}/finalize.",
    )


class TextbookUploadResponse(BaseModel):
    doc_id: str
    # DRAFT only when review mode stopped the pipeline short of question generation. The
    # client routes straight to the review screen on this alone, with no second request.
    status: DocumentStatus


class DocumentStatusResponse(BaseModel):
    status: DocumentStatus


def _finalize(store: Store, graph: DependencyGraph) -> None:
    """Generate a question set for every concept, then persist the finished graph.

    The shared tail of both routes to a finalized chapter — the automatic one (review mode
    off, straight through from upload) and the explicit one (`finalize_textbook` below,
    once a human has edited the graph). Sharing it is what makes a reviewed chapter
    identical in every respect to an unreviewed one.
    """
    question_generator.generate_questions(graph)  # populates concept.questions in place
    store.save_graph(graph)
    for concept in graph.concepts:
        store.save_questions(concept.id, concept.questions)


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
    status = DocumentStatus.DRAFT if payload.review else DocumentStatus.FINALIZED
    store.save_document(doc_id, payload.text, payload.title, status=status)

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
        if payload.review:
            # Pause for review: persist the graph as extracted and stop before spending a
            # question-generation call per concept on a graph a human is about to change.
            # POST /api/textbook/{doc_id}/finalize resumes the pipeline from here.
            store.save_graph(graph)
        else:
            _finalize(store, graph)
    except Exception:
        store.delete_document(doc_id)
        raise

    return TextbookUploadResponse(doc_id=doc_id, status=status)


@router.get("/textbook/{doc_id}/status", response_model=DocumentStatusResponse)
def get_textbook_status(doc_id: str) -> DocumentStatusResponse:
    """Whether this chapter is still awaiting review.

    The only way to observe a draft's state: `list_documents()` hides drafts, and
    `GET /api/graph/{id}` returns the graph without saying which side of finalize it's on.
    """
    status = get_store().get_document_status(doc_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"No document '{doc_id}'")
    return DocumentStatusResponse(status=status)


@router.post("/textbook/{doc_id}/finalize", response_model=TextbookUploadResponse)
def finalize_textbook(doc_id: str) -> TextbookUploadResponse:
    """Approve a reviewed graph: generate its questions and open it to study sessions."""
    store = get_store()
    status = store.get_document_status(doc_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"No document '{doc_id}'")
    if status is DocumentStatus.FINALIZED:
        raise HTTPException(status_code=409, detail="Document is already finalized")

    graph = store.get_graph(doc_id)
    if graph is None or not graph.concepts:
        # Same reasoning as the upload path's zero-concept rejection — a chapter with no
        # concepts is one whose every downstream endpoint 404s. Reachable here by deleting
        # every concept during review.
        raise HTTPException(status_code=422, detail="Cannot finalize a chapter with no concepts")

    # No rollback around this one, deliberately: `upload_textbook` deletes its document on
    # failure because nothing of value is lost, whereas here a failed question-generation
    # call would be discarding a human's review work. The document stays DRAFT with its
    # edited graph intact, and finalizing again just retries.
    _finalize(store, graph)
    store.finalize_document(doc_id)
    return TextbookUploadResponse(doc_id=doc_id, status=DocumentStatus.FINALIZED)
