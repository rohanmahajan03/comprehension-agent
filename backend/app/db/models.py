"""SQLAlchemy ORM models — the table layer only.

Deliberately separate from the Pydantic schemas in app/models/schemas.py (see the design
doc, docs/specs/2026-08-21-persistent-storage-design.md §5): PostgresStore is the boundary
that converts between the two. No SQLAlchemy type crosses the Store interface.
"""

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.engine import Base


class DocumentRow(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(primary_key=True)
    text: Mapped[str]


class ConceptRow(Base):
    __tablename__ = "concepts"

    id: Mapped[str] = mapped_column(primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    name: Mapped[str]
    summary: Mapped[str]
    # list[str] of concept ids. Never queried independent of a full-graph load — see design
    # doc §2 — so this stays JSONB rather than a normalized edge table.
    depends_on: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # dict[str, str]: prereq_id -> the source-text quote justifying that dependency.
    evidence: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)

    questions: Mapped[list["QuestionRow"]] = relationship(
        back_populates="concept", cascade="all, delete-orphan"
    )


class QuestionRow(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(primary_key=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"))
    prompt: Mapped[str]
    expected_answer_notes: Mapped[str]

    concept: Mapped[ConceptRow] = relationship(back_populates="questions")


class StudySessionRow(Base):
    __tablename__ = "study_sessions"

    id: Mapped[str] = mapped_column(primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    current_concept_id: Mapped[str | None]
    status: Mapped[str]

    history: Mapped[list["HistoryEntryRow"]] = relationship(
        back_populates="study_session",
        cascade="all, delete-orphan",
        order_by="HistoryEntryRow.seq",
    )


class HistoryEntryRow(Base):
    __tablename__ = "history_entries"
    __table_args__ = (UniqueConstraint("study_session_id", "seq"),)

    # Surrogate key: HistoryEntry (the Pydantic model) has no id of its own — it's a list
    # item identified only by position, which `seq` captures. This exists purely so the row
    # can be a foreign-key target; it's never surfaced through Store or the API.
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    study_session_id: Mapped[str] = mapped_column(
        ForeignKey("study_sessions.id", ondelete="CASCADE")
    )
    seq: Mapped[int]
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"))
    answer_text: Mapped[str]
    eval_correct: Mapped[bool]
    eval_explanation: Mapped[str]
    diagnosis_suspected_concept_id: Mapped[str | None]
    diagnosis_reasoning: Mapped[str | None]
    diagnosis_targeted_question_id: Mapped[str | None] = mapped_column(
        ForeignKey("questions.id")
    )

    study_session: Mapped[StudySessionRow] = relationship(back_populates="history")
    question: Mapped[QuestionRow] = relationship(foreign_keys=[question_id])
    targeted_question: Mapped[QuestionRow | None] = relationship(
        foreign_keys=[diagnosis_targeted_question_id]
    )
