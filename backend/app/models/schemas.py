"""Core domain models, mirrored as TypeScript types in frontend/src/types/index.ts.

Keep the two in sync when changing anything here.
"""

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


class Question(BaseModel):
    id: str
    concept_id: str
    prompt: str # the question that was asked
    expected_answer_notes: str = Field(
        description="Notes for the evaluator on what a correct answer should contain"
    )


class Concept(BaseModel):
    id: str
    name: str
    summary: str
    source_quotes: list[str] = Field(
        default_factory=list,
        description="Verbatim chapter passages explaining this concept, beyond its summary",
    )
    depends_on: list[str] = Field(default_factory=list, description="IDs of prerequisite concepts")
    evidence: dict[str, str] = Field(
        default_factory=dict,
        description="Maps each id in depends_on to the source-text quote justifying that prerequisite",
    )
    questions: list[Question] = Field(
        default_factory=list, description="Question set generated for this concept"
    )


class DependencyGraph(BaseModel):
    doc_id: str
    concepts: list[Concept] = Field(default_factory=list)


class EvidenceProposal(BaseModel):
    """What a targeted re-scan of the chapter turned up for one concept.

    A *proposal*: nothing here is written until the reviewer accepts it through
    `PATCH /api/graph/{doc_id}/concepts/{concept_id}`. Silently overwriting the summary
    someone just typed with model output would invert the human-in-the-loop feature this
    serves (docs/specs/2026-09-13-concept-evidence-generation.md §6).

    `found: False` is an ordinary, expected outcome, not an error: a reviewer may be adding
    a concept the chapter assumes rather than teaches, and manufacturing quotes to fill the
    schema is the failure mode this flag exists to prevent.
    """

    found: bool
    summary: str = Field(
        default="",
        description="A chapter-grounded summary offered as a replacement; empty when found is False",
    )
    quotes: list[str] = Field(
        default_factory=list,
        description="Verbatim chapter passages, each already checked against the source text",
    )
    dropped: int = Field(
        default=0,
        description="How many returned quotes were discarded as not verbatim in the chapter",
    )


class DocumentStatus(str, Enum):
    """Where a chapter sits in pipeline 1.

    DRAFT means its graph has been extracted but not yet approved, so no questions exist
    for it and no study session can start against it. Only reachable by uploading with
    `TextbookUpload.review` set; otherwise a document is FINALIZED from the moment it's
    created. See docs/specs/2026-09-12-human-in-the-loop §3.
    """

    DRAFT = "draft"
    FINALIZED = "finalized"


class DocumentSummary(BaseModel):
    """One row of the "your chapters" list.

    Unlike StudySessionSummaryRow/StudySessionSummary, there's no split into an internal
    row shape plus a router-enriched public one: total_concepts is a plain count the Store
    can compute directly, with no services-layer (topological_order) dependency involved.
    """

    id: str
    title: str | None = Field(
        default=None, description="None when the document was uploaded without one"
    )
    text_snippet: str = Field(
        description="Short label from the document's text, for rendering when title is None"
    )
    total_concepts: int
    created_at: datetime


class Answer(BaseModel):
    question_id: str
    text: str


class EvaluationResult(BaseModel):
    correct: bool
    explanation: str


class DiagnosisResult(BaseModel):
    suspected_gap_concept_id: str
    reasoning: str
    targeted_question: Question


class AnswerOverride(BaseModel):
    """A student's claim that the evaluator misgraded one answer, kept for later review.

    A *second* record asserting the first is wrong, never an edit of it: the history entry
    this points at keeps `eval_correct = False` and the evaluator's explanation verbatim,
    since what the evaluator said is precisely the disputed artifact (design doc
    docs/specs/2026-09-18-manual-answer-override-design.md §4).

    Self-contained on purpose. Every other table here references `questions` by FK rather
    than embedding a copy, but this row has to outlive what it describes:
    `DELETE /api/study-session/{id}` cascades `history_entries`, and `delete_document`
    cascades documents → concepts → questions. The ids below are therefore soft references
    with no FK, and the four snapshot fields carry the text — which also pins the rubric as
    it read *at grading time* rather than as a join would return it later (§5).
    """

    study_session_id: str
    history_seq: int = Field(
        description="Index into StudySession.history — the identity of the attempt, which "
        "question_id alone is not, since a question is re-served on retry"
    )
    question_id: str
    concept_id: str
    doc_id: str
    question_prompt: str
    expected_answer_notes: str
    student_answer: str
    evaluator_explanation: str
    student_note: str | None = Field(
        default=None,
        description="Why the student thinks the grade was wrong. Optional — requiring prose "
        "behind the button would suppress the disagreements this exists to collect",
    )
    created_at: datetime = Field(default_factory=_now)


class StudySessionStatus(str, Enum):
    ACTIVE = "active"
    DIAGNOSING = "diagnosing"
    COMPLETED = "completed"


class HistoryEntry(BaseModel):
    question: Question
    answer: Answer
    evaluation: EvaluationResult
    diagnosis: DiagnosisResult | None = None


class StudySession(BaseModel):
    id: str
    doc_id: str
    current_concept_id: str | None = None
    history: list[HistoryEntry] = Field(default_factory=list)
    status: StudySessionStatus = StudySessionStatus.ACTIVE
    created_at: datetime = Field(default_factory=_now)
    # Both Store implementations overwrite this on every save (see Store.save_study_session),
    # so it reflects the last write rather than when the object was constructed.
    updated_at: datetime = Field(default_factory=_now)


class StudySessionDetail(StudySession):
    """A study session plus the question it is currently waiting on.

    A superset of `StudySession`, returned by the endpoints a client uses to open a session
    (`POST /start` and `GET /{id}`). `pending_question` is *derived* from the session's
    status and history rather than stored, which is why it lives on this read model instead
    of on `StudySession` itself.

    It exists so clients never have to reconstruct "which question is this session on" —
    a rule with a non-obvious branch (a diagnosing session is parked on its diagnostic
    question, not its concept's first question) that `submit_answer` already had to know.
    Deriving it in one place server-side keeps the two from drifting.
    """

    pending_question: Question | None = None


class StudySessionSummaryRow(BaseModel):
    """What a Store can assemble from storage alone — the internal half of the seam.

    `completed_concepts` is deliberately absent: it's the topological position of
    `current_concept_id`, which needs the concept graph and `graph_builder.topological_order`.
    Computing it in a Store would make the storage layer import the services layer, so the
    router does it instead (see docs/specs/2026-08-29-resume-study-session-design.md §4).
    Same internal-seam idea as `graph_builder._extract_raw_graph` vs `build_graph`.
    """

    id: str
    doc_id: str
    title: str | None
    # Always populated. Lets the client label an untitled chapter without a second request,
    # and without the API shipping the whole document to render one line.
    text_snippet: str
    status: StudySessionStatus
    current_concept_id: str | None
    total_concepts: int
    updated_at: datetime


class StudySessionSummary(BaseModel):
    """One row of the "continue a session" list. Public API shape."""

    id: str
    doc_id: str
    title: str | None = Field(
        default=None, description="None when the document was uploaded without one"
    )
    text_snippet: str = Field(
        description="Short label from the document's text, for rendering when title is None"
    )
    status: StudySessionStatus
    completed_concepts: int
    total_concepts: int
    updated_at: datetime
