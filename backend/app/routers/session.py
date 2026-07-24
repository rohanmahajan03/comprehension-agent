"""Pipeline 2: the ask → evaluate → (advance | diagnose) loop."""

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models import (
    Answer,
    DiagnosisResult,
    EvaluationResult,
    HistoryEntry,
    Question,
    Session,
    SessionStatus,
)
from app.services import diagnoser, evaluator
from app.services.graph_builder import topological_order
from app.store import Store, get_store

router = APIRouter(prefix="/api/session", tags=["session"])


class SessionStartRequest(BaseModel):
    doc_id: str


class AnswerResponse(BaseModel):
    evaluation: EvaluationResult
    diagnosis: DiagnosisResult | None = None
    next_question: Question | None = None
    session: Session


@router.post("/start", response_model=Session, status_code=201)
def start_session(payload: SessionStartRequest) -> Session:
    store = get_store()
    graph = store.get_graph(payload.doc_id)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"No graph found for doc '{payload.doc_id}'")

    ordered = topological_order(graph)
    session = Session(
        id=uuid.uuid4().hex[:12],
        doc_id=payload.doc_id,
        current_concept_id=ordered[0].id if ordered else None,
    )
    store.save_session(session)
    return session


@router.get("/{session_id}", response_model=Session)
def get_session(session_id: str) -> Session:
    session = get_store().get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"No session '{session_id}'")
    return session


def _find_question(store: Store, question_id: str) -> Question | None:
    # Question ids are "{concept_id}:{suffix}", so strip the suffix to find the set.
    concept_id = question_id.rsplit(":", 1)[0]
    for question in store.get_questions(concept_id) or []:
        if question.id == question_id:
            return question
    return None


@router.post("/{session_id}/answer", response_model=AnswerResponse)
def submit_answer(session_id: str, answer: Answer) -> AnswerResponse:
    store = get_store()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"No session '{session_id}'")
    if session.status == SessionStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Session is already completed")

    graph = store.get_graph(session.doc_id)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"No graph found for doc '{session.doc_id}'")
    by_id = {c.id: c for c in graph.concepts}

    question = _find_question(store, answer.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail=f"Unknown question '{answer.question_id}'")

    evaluation = evaluator.evaluate(question, answer)
    diagnosis: DiagnosisResult | None = None
    next_question: Question | None = None

    if evaluation.correct:
        # Advance to the next unvisited concept in prerequisite order. If the
        # learner was answering a diagnostic question, this simply resumes the
        # main track from the session's current concept.
        ordered = topological_order(graph)
        current_index = next(
            (i for i, c in enumerate(ordered) if c.id == session.current_concept_id), -1
        )
        if current_index + 1 < len(ordered):
            session.current_concept_id = ordered[current_index + 1].id
            session.status = SessionStatus.ACTIVE
            next_question = (store.get_questions(session.current_concept_id) or [None])[0]
        else:
            session.status = SessionStatus.COMPLETED
    else:
        concept = by_id.get(question.concept_id)
        if concept is None:
            raise HTTPException(
                status_code=404, detail=f"Unknown concept '{question.concept_id}'"
            )
        diagnosis = diagnoser.diagnose(concept, graph, question, answer)
        # Register the targeted question so the answer to it can be resolved later.
        targeted = diagnosis.targeted_question
        existing = store.get_questions(targeted.concept_id) or []
        if all(q.id != targeted.id for q in existing):
            store.save_questions(targeted.concept_id, [*existing, targeted])
        session.status = SessionStatus.DIAGNOSING
        next_question = targeted

    session.history.append(
        HistoryEntry(question=question, answer=answer, evaluation=evaluation, diagnosis=diagnosis)
    )
    store.save_session(session)

    return AnswerResponse(
        evaluation=evaluation,
        diagnosis=diagnosis,
        next_question=next_question,
        session=session,
    )
