"""Core domain models, mirrored as TypeScript types in frontend/src/types/index.ts.

Keep the two in sync when changing anything here.
"""

from enum import Enum

from pydantic import BaseModel, Field


class Concept(BaseModel):
    id: str
    name: str
    summary: str
    depends_on: list[str] = Field(default_factory=list, description="IDs of prerequisite concepts")


class DependencyGraph(BaseModel):
    doc_id: str
    concepts: list[Concept] = Field(default_factory=list)


class Question(BaseModel):
    id: str
    concept_id: str
    prompt: str
    expected_answer_notes: str = Field(
        description="Notes for the evaluator on what a correct answer should contain"
    )


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


class SessionStatus(str, Enum):
    ACTIVE = "active"
    DIAGNOSING = "diagnosing"
    COMPLETED = "completed"


class HistoryEntry(BaseModel):
    question: Question
    answer: Answer
    evaluation: EvaluationResult
    diagnosis: DiagnosisResult | None = None


class Session(BaseModel):
    id: str
    doc_id: str
    current_concept_id: str | None = None
    history: list[HistoryEntry] = Field(default_factory=list)
    status: SessionStatus = SessionStatus.ACTIVE
