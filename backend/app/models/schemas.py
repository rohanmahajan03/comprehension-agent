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
