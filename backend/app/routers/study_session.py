"""Pipeline 2: the ask → evaluate → (advance | diagnose) loop."""

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models import (
    Answer,
    AnswerOverride,
    DependencyGraph,
    DiagnosisResult,
    DocumentStatus,
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

# How far remediation on one concept is allowed to go, from
# docs/specs/2026-09-17-study-loop-remediation-design.md §3. Two numbers, because one cannot
# close both doors: counting only attempts on the concept itself lets a student loop forever
# through prerequisite diagnostics without ever returning to it, while counting every wrong
# answer made while it is current spends the whole budget on prerequisites so the concept is
# never retried. Module constants rather than settings — nothing about them is
# deployment-specific, and a knob invites tuning without measurement. The ceiling is
# A + (A-1) × C questions on one concept (the final attempt triggers no drill), so at 3/2:
# 7 questions and 4 diagnoser runs, and the diagnoser term dominates the bill.
_MAX_CONCEPT_ATTEMPTS = 3  # wrong answers on a concept's own question
_MAX_DIAGNOSTIC_CHAIN = 2  # consecutive diagnostics in one drill before forcing a return


class StudySessionStartRequest(BaseModel):
    doc_id: str


class AnswerResponse(BaseModel):
    evaluation: EvaluationResult
    diagnosis: DiagnosisResult | None = None
    next_question: Question | None = None
    study_session: StudySession
    # Transient, in the response only: `StudySessionDetail` does not carry it, so reloading
    # after a reveal loses the banner. The fact itself isn't lost — the history entry
    # recording the final failed attempt is persisted either way — and storing it would mean
    # a `history_entries` column and a migration for something the client can re-derive.
    revealed_answer: str | None = Field(
        default=None,
        description="The abandoned question's model answer, set only when a cap tripped "
        "and the loop moved on without the student getting it right",
    )


@router.post("/start", response_model=StudySessionDetail, status_code=201)
def start_study_session(payload: StudySessionStartRequest) -> StudySessionDetail:
    store = get_store()
    graph = store.get_graph(payload.doc_id)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"No graph found for doc '{payload.doc_id}'")
    if store.get_document_status(payload.doc_id) is DocumentStatus.DRAFT:
        # A draft has concepts but no questions yet, so the session would open on a
        # concept with nothing to ask. Only chapters uploaded with `review` are ever DRAFT,
        # so for every other chapter this branch is simply unreachable.
        raise HTTPException(
            status_code=409,
            detail="Chapter is still in review; finalize its graph before studying it",
        )

    # Open on the first concept in prerequisite order that actually has a question, for the
    # same reason `_advance` skips them: parking on a question-less concept leaves
    # `_pending_question` returning None with nothing the client can submit, which deadlocks
    # the session — here, at birth (design doc §5).
    ordered = topological_order(graph)
    first = next((c for c in ordered if store.get_questions(c.id)), None)
    study_session = StudySession(
        id=uuid.uuid4().hex[:12],
        doc_id=payload.doc_id,
        current_concept_id=first.id if first is not None else None,
        # Nothing in this chapter can be asked, so the session is born finished rather than
        # 201-ing into an active state it can never leave. (A chapter in that condition is a
        # question-generation failure; refusing it at finalize instead is design doc §8.)
        status=StudySessionStatus.ACTIVE if first is not None else StudySessionStatus.COMPLETED,
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


@router.delete("/{study_session_id}", status_code=204)
def delete_study_session(study_session_id: str) -> None:
    store = get_store()
    if store.get_study_session(study_session_id) is None:
        raise HTTPException(status_code=404, detail=f"No study session '{study_session_id}'")
    store.delete_study_session(study_session_id)


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


def _diagnostic_question_ids(study_session: StudySession) -> set[str]:
    """Every question this session served as a diagnostic probe.

    Derived from the diagnoses themselves rather than from the `:diagnostic{n}` id suffix:
    the suffix is minted in `diagnoser._next_diagnostic_id()` and parsing it here would put
    a second reader on a convention with one owner. The session already holds the fact.
    """
    return {
        entry.diagnosis.targeted_question.id
        for entry in study_session.history
        if entry.diagnosis is not None
    }


def _failed_main_track_attempts(study_session: StudySession, concept_id: str) -> int:
    """Wrong answers to `concept_id`'s own question, excluding diagnostic probes.

    The exclusion matters: the diagnoser may name the answered concept itself as the
    suspect (a documented outcome for concepts with no prerequisites), so an entry can
    carry `question.concept_id == concept_id` and still be a diagnostic.
    """
    diagnostics = _diagnostic_question_ids(study_session)
    return sum(
        1
        for entry in study_session.history
        if not entry.evaluation.correct
        and entry.question.concept_id == concept_id
        and entry.question.id not in diagnostics
    )


def _current_chain_length(study_session: StudySession) -> int:
    """How many diagnostics deep the *current* drill is.

    Trailing diagnostic entries only — a main-track entry ends the chain, which is what
    makes this the current drill rather than the session's total.
    """
    diagnostics = _diagnostic_question_ids(study_session)
    length = 0
    for entry in reversed(study_session.history):
        if entry.question.id not in diagnostics:
            break
        length += 1
    return length


def _advance(store: Store, study_session: StudySession, graph: DependencyGraph) -> None:
    """Move to the next concept in prerequisite order that actually has a question.

    Concepts with an empty question set are skipped rather than parked on: reaching one
    leaves `_pending_question` returning None with no answer the client can submit, which
    deadlocks the session permanently. `question_generator` is told to skip question types
    that do not fit the evidence, so an empty set is a legitimate output, not a failure.
    """
    ordered = topological_order(graph)
    index = next(
        (i for i, c in enumerate(ordered) if c.id == study_session.current_concept_id), -1
    )
    for candidate in ordered[index + 1 :]:
        if store.get_questions(candidate.id):
            study_session.current_concept_id = candidate.id
            study_session.status = StudySessionStatus.ACTIVE
            return
    # `current_concept_id` is left where it was, matching the behavior this replaced.
    study_session.status = StudySessionStatus.COMPLETED


class AnswerOverrideRequest(BaseModel):
    question_id: str
    note: str | None = None


@router.post("/{study_session_id}/override", response_model=StudySessionDetail)
def override_answer(
    study_session_id: str, payload: AnswerOverrideRequest
) -> StudySessionDetail:
    """Record that the evaluator misgraded the last answer, and move the session on.

    Two things happen, and only one of them is about this session: a snapshot of the
    disagreement is written for later human validation and evaluator tuning (the durable
    half), and the session takes the same transition a correct answer would (the immediate
    half). See docs/specs/2026-09-18-manual-answer-override-design.md.

    **The history entry is deliberately left as graded** — `eval_correct` stays False with
    the evaluator's explanation intact. What the evaluator said is the disputed artifact, so
    overwriting it would destroy the evidence and make a session replay show agreement where
    there was none (§4). The consequence to know about: the overridden attempt still counts
    toward `_MAX_CONCEPT_ATTEMPTS` for that concept.
    """
    store = get_store()
    study_session = store.get_study_session(study_session_id)
    if study_session is None:
        raise HTTPException(status_code=404, detail=f"No study session '{study_session_id}'")
    if not study_session.history:
        raise HTTPException(
            status_code=404, detail="Study session has no answer to override yet"
        )

    graph = store.get_graph(study_session.doc_id)
    if graph is None:
        raise HTTPException(
            status_code=404, detail=f"No graph found for doc '{study_session.doc_id}'"
        )

    # Only the newest entry is overridable. The transition below branches on
    # `study_session.status`, and status describes the latest entry alone — running that rule
    # against an older one would advance the session from wherever it happens to be now
    # rather than from where that answer left it (§7). It also makes `history_seq`
    # unambiguous with no search.
    history_seq = len(study_session.history) - 1
    entry = study_session.history[history_seq]
    if entry.question.id != payload.question_id:
        raise HTTPException(
            status_code=409,
            detail="Only the most recent answer can be overridden",
        )
    if entry.evaluation.correct:
        raise HTTPException(
            status_code=409, detail="That answer was already graded correct"
        )

    wrote = store.save_answer_override(
        AnswerOverride(
            study_session_id=study_session.id,
            history_seq=history_seq,
            question_id=entry.question.id,
            concept_id=entry.question.concept_id,
            doc_id=study_session.doc_id,
            question_prompt=entry.question.prompt,
            expected_answer_notes=entry.question.expected_answer_notes,
            student_answer=entry.answer.text,
            evaluator_explanation=entry.evaluation.explanation,
            student_note=payload.note,
        )
    )
    if not wrote:
        # Already overridden. An override appends nothing to history, so this entry is still
        # the newest one and every check above passed a second time — without this the
        # session would advance twice on a double-submitted click (§6).
        return _with_pending(store, study_session)

    # Which transition applies is a fact about the *entry*, not about the session's current
    # status. By the time an override arrives the status already reflects what the wrong
    # answer did: a failed main-track answer leaves the session DIAGNOSING, so reading the
    # status here would misread it as a prerequisite probe and refuse to advance.
    was_diagnostic = entry.question.id in _diagnostic_question_ids(study_session)
    # True only when a cap already carried the session past this concept (`_advance` ran and
    # the answer was revealed), in which case there is nothing left to advance.
    already_moved_on = entry.question.concept_id != study_session.current_concept_id

    if study_session.status is StudySessionStatus.COMPLETED:
        # The session finished on this answer. Recording the disagreement is the whole point
        # here; resurrecting a completed session to re-serve a concept is not.
        pass
    elif was_diagnostic or already_moved_on:
        # The concept this answer belongs to isn't waiting on it — the student disputed a
        # prerequisite probe, or a cap already moved the loop on. Either way: stop drilling,
        # leave `current_concept_id` alone, and let the student take that concept again.
        study_session.status = StudySessionStatus.ACTIVE
    else:
        _advance(store, study_session, graph)
    store.save_study_session(study_session)

    return _with_pending(store, study_session)


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

    # The whole transition below discriminates on the status the request arrived with, read
    # before anything mutates it: it already encodes which track the student was on, so
    # nothing has to inspect the answered question's id or provenance (design doc §2).
    entry_status = study_session.status
    evaluation = evaluator.evaluate(question, answer)
    diagnosis: DiagnosisResult | None = None
    revealed_answer: str | None = None

    if evaluation.correct:
        if entry_status is StudySessionStatus.DIAGNOSING:
            # The prerequisite gap is closed, so hand the student back the concept that
            # exposed it — deliberately *without* advancing. This is the return step the loop
            # was missing: the old code advanced unconditionally here, so repairing a
            # prerequisite counted as passing the concept that failed (design doc §1a).
            # Re-serving needs nothing else — an ACTIVE session on this concept already gets
            # `store.get_questions(...)[0]`, and diagnostic questions are appended after the
            # generated set, so index 0 is still the main-track question.
            study_session.status = StudySessionStatus.ACTIVE
        else:
            _advance(store, study_session, graph)
    else:
        if entry_status is StudySessionStatus.ACTIVE:
            # +1 for the attempt being recorded now: history is appended further below.
            give_up = (
                _failed_main_track_attempts(study_session, question.concept_id) + 1
                >= _MAX_CONCEPT_ATTEMPTS
            )
        else:
            give_up = _current_chain_length(study_session) + 1 >= _MAX_DIAGNOSTIC_CHAIN

        if give_up:
            # One give-up rule for both caps (§3), so there is one behavior to reason about:
            # reveal the abandoned question's model answer and move the loop on.
            # `expected_answer_notes` is used as-is, with no new LLM call — since the
            # `expected_answer` fix it is the ideal student response in prose, which
            # question_geval's checks 4 and 5 already hold to answering its own question
            # completely and standing alone for a reader who cannot see the evidence.
            revealed_answer = question.expected_answer_notes
            if entry_status is StudySessionStatus.ACTIVE:
                _advance(store, study_session, graph)  # left unmastered, deliberately
            else:
                # Stop drilling and return to the concept the drill started from, which
                # `current_concept_id` has been sitting on the whole time.
                study_session.status = StudySessionStatus.ACTIVE
        else:
            concept = by_id.get(question.concept_id)
            if concept is None:
                raise HTTPException(
                    status_code=404, detail=f"Unknown concept '{question.concept_id}'"
                )
            diagnosis = diagnoser.diagnose(concept, graph, question, answer, evaluation)
            # Register the targeted question so the answer to it can be resolved later. Both
            # Store implementations reconstruct Concept.questions from this same index on
            # every get_graph() call (see docs/specs/2026-08-21-persistent-storage-design.md
            # §3), so a later diagnosis of this concept sees it as a reuse candidate without
            # any further write here.
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
        revealed_answer=revealed_answer,
    )
