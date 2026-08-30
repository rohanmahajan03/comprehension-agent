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
    StudySession,
    StudySessionDetail,
    StudySessionStatus,
    StudySessionSummary,
    StudySessionSummaryRow,
)
from app.services import diagnoser, evaluator
from app.services.graph_builder import topological_order
from app.store import Store, get_store

router = APIRouter(prefix="/api/study-session", tags=["study-session"])


class StudySessionStartRequest(BaseModel):
    doc_id: str


class AnswerResponse(BaseModel):
    evaluation: EvaluationResult
    diagnosis: DiagnosisResult | None = None
    next_question: Question | None = None
    study_session: StudySession


@router.post("/start", response_model=StudySessionDetail, status_code=201)
def start_study_session(payload: StudySessionStartRequest) -> StudySessionDetail:
    store = get_store()
    graph = store.get_graph(payload.doc_id)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"No graph found for doc '{payload.doc_id}'")

    ordered = topological_order(graph)
    study_session = StudySession(
        id=uuid.uuid4().hex[:12],
        doc_id=payload.doc_id,
        current_concept_id=ordered[0].id if ordered else None,
    )
    store.save_study_session(study_session)
    return _with_pending(store, study_session)


@router.get("", response_model=list[StudySessionSummary])
def list_study_sessions() -> list[StudySessionSummary]:
    """The "continue a session" list: unfinished sessions, most recently updated first.

    The store returns everything storage can join cheaply; the one field it can't supply is
    `completed_concepts`, which is the position of `current_concept_id` in the chapter's
    topological order — the same ordering `submit_answer` advances through. That needs
    `topological_order`, and a Store importing from `app.services` would invert the layering
    every other module follows, so the enrichment happens here instead.

    Graphs are loaded once per *distinct* document, not once per session: two sessions on
    the same chapter cost one graph read between them.
    """
    store = get_store()
    rows = store.list_unfinished_sessions()

    orders: dict[str, list[str]] = {}
    for doc_id in {row.doc_id for row in rows}:
        graph = store.get_graph(doc_id)
        orders[doc_id] = [c.id for c in topological_order(graph)] if graph else []

    def completed(row: StudySessionSummaryRow) -> int:
        # None means the session was created against a graph with no concepts and has
        # nothing to advance through; an id missing from the order means the concept was
        # removed since. Both are 0 progress rather than an error.
        if row.current_concept_id is None:
            return 0
        order = orders.get(row.doc_id, [])
        return order.index(row.current_concept_id) if row.current_concept_id in order else 0

    return [
        StudySessionSummary(
            id=row.id,
            doc_id=row.doc_id,
            title=row.title,
            text_snippet=row.text_snippet,
            status=row.status,
            completed_concepts=completed(row),
            total_concepts=row.total_concepts,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.get("/{study_session_id}", response_model=StudySessionDetail)
def get_study_session(study_session_id: str) -> StudySessionDetail:
    """Read a session, including the question it's waiting on — this is the resume path."""
    store = get_store()
    study_session = store.get_study_session(study_session_id)
    if study_session is None:
        raise HTTPException(status_code=404, detail=f"No study session '{study_session_id}'")
    return _with_pending(store, study_session)


def _pending_question(store: Store, study_session: StudySession) -> Question | None:
    """The question this session is waiting on, derived from its own state.

    The non-obvious branch is `diagnosing`: the session is parked on the diagnostic question
    the diagnoser produced, which lives on the last history entry — *not* on the current
    concept's first stored question. That first question is the one the student just
    answered wrong, so serving it would re-ask it and grade the next answer against the
    wrong rubric.

    Single source of truth for the rule. `submit_answer` derives its `next_question` from
    this, and both endpoints that open a session return it as `pending_question`, so a
    client never reimplements the branch (the frontend previously did, in TypeScript).
    """
    if study_session.status is StudySessionStatus.COMPLETED:
        return None

    if study_session.status is StudySessionStatus.DIAGNOSING and study_session.history:
        diagnosis = study_session.history[-1].diagnosis
        if diagnosis is not None:
            return diagnosis.targeted_question

    if study_session.current_concept_id is None:
        return None
    return (store.get_questions(study_session.current_concept_id) or [None])[0]


def _with_pending(store: Store, study_session: StudySession) -> StudySessionDetail:
    return StudySessionDetail(
        **study_session.model_dump(),
        pending_question=_pending_question(store, study_session),
    )


def _find_question(store: Store, question_id: str) -> Question | None:
    # Question ids are "{concept_id}:{suffix}", so strip the suffix to find the set.
    concept_id = question_id.rsplit(":", 1)[0]
    for question in store.get_questions(concept_id) or []:
        if question.id == question_id:
            return question
    return None


@router.post("/{study_session_id}/answer", response_model=AnswerResponse)
def submit_answer(study_session_id: str, answer: Answer) -> AnswerResponse:
    store = get_store()
    study_session = store.get_study_session(study_session_id)
    if study_session is None:
        raise HTTPException(status_code=404, detail=f"No study session '{study_session_id}'")
    if study_session.status == StudySessionStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Study session is already completed")

    graph = store.get_graph(study_session.doc_id)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"No graph found for doc '{study_session.doc_id}'")
    by_id = {c.id: c for c in graph.concepts}

    question = _find_question(store, answer.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail=f"Unknown question '{answer.question_id}'")

    evaluation = evaluator.evaluate(question, answer)
    diagnosis: DiagnosisResult | None = None

    if evaluation.correct:
        # Advance to the next unvisited concept in prerequisite order. If the
        # learner was answering a diagnostic question, this simply resumes the
        # main track from the study session's current concept.
        ordered = topological_order(graph)
        current_index = next(
            (i for i, c in enumerate(ordered) if c.id == study_session.current_concept_id), -1
        )
        if current_index + 1 < len(ordered):
            study_session.current_concept_id = ordered[current_index + 1].id
            study_session.status = StudySessionStatus.ACTIVE
        else:
            study_session.status = StudySessionStatus.COMPLETED
    else:
        concept = by_id.get(question.concept_id)
        if concept is None:
            raise HTTPException(
                status_code=404, detail=f"Unknown concept '{question.concept_id}'"
            )
        diagnosis = diagnoser.diagnose(concept, graph, question, answer, evaluation)
        # Register the targeted question so the answer to it can be resolved later. Both
        # Store implementations reconstruct Concept.questions from this same index on every
        # get_graph() call (see docs/specs/2026-08-21-persistent-storage-design.md §3), so a
        # later diagnosis of this concept sees it as a reuse candidate without any further
        # write here.
        targeted = diagnosis.targeted_question
        existing = store.get_questions(targeted.concept_id) or []
        if all(q.id != targeted.id for q in existing):
            store.save_questions(targeted.concept_id, [*existing, targeted])
        study_session.status = StudySessionStatus.DIAGNOSING

    study_session.history.append(
        HistoryEntry(question=question, answer=answer, evaluation=evaluation, diagnosis=diagnosis)
    )
    store.save_study_session(study_session)

    # Derived after the transition and the history append, from the same helper the resume
    # endpoints use — so "what question comes next" is answered identically whether the
    # client just answered or is reopening the session later.
    return AnswerResponse(
        evaluation=evaluation,
        diagnosis=diagnosis,
        next_question=_pending_question(store, study_session),
        study_session=study_session,
    )
