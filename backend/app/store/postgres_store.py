"""Postgres-backed Store implementation.

See docs/specs/2026-08-21-persistent-storage-design.md for the schema and the reasoning
behind it. The one deviation from that doc, found while implementing it, is documented on
`save_questions` below.

Writes use Core insert-on-conflict statements rather than ORM session.merge()/cascades, so
exactly which columns get written is explicit and auditable — in particular so `save_graph`
cannot accidentally cascade into the `questions` table through the ORM relationship (per the
design's §3, a graph write must never touch questions; only `save_questions` does).
"""

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload

from app.db.engine import session_scope
from app.db.models import ConceptRow, DocumentRow, HistoryEntryRow, QuestionRow, StudySessionRow
from app.models import (
    Answer,
    Concept,
    DependencyGraph,
    DiagnosisResult,
    EvaluationResult,
    HistoryEntry,
    Question,
    StudySession,
    StudySessionStatus,
)
from app.store.memory_store import Store


def _to_question(row: QuestionRow) -> Question:
    return Question(
        id=row.id,
        concept_id=row.concept_id,
        prompt=row.prompt,
        expected_answer_notes=row.expected_answer_notes,
    )


def _to_concept(row: ConceptRow) -> Concept:
    return Concept(
        id=row.id,
        name=row.name,
        summary=row.summary,
        depends_on=list(row.depends_on),
        evidence=dict(row.evidence),
        questions=[_to_question(q) for q in row.questions],
    )


class PostgresStore(Store):
    def save_document(self, doc_id: str, text: str) -> None:
        with session_scope() as session:
            stmt = pg_insert(DocumentRow).values(id=doc_id, text=text)
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_={"text": stmt.excluded.text})
            session.execute(stmt)

    def get_document(self, doc_id: str) -> str | None:
        with session_scope() as session:
            row = session.get(DocumentRow, doc_id)
            return row.text if row else None

    def save_graph(self, graph: DependencyGraph) -> None:
        """Upsert every concept row. Never touches `questions` — see module docstring."""
        with session_scope() as session:
            for concept in graph.concepts:
                stmt = pg_insert(ConceptRow).values(
                    id=concept.id,
                    doc_id=graph.doc_id,
                    name=concept.name,
                    summary=concept.summary,
                    depends_on=concept.depends_on,
                    evidence=concept.evidence,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "doc_id": stmt.excluded.doc_id,
                        "name": stmt.excluded.name,
                        "summary": stmt.excluded.summary,
                        "depends_on": stmt.excluded.depends_on,
                        "evidence": stmt.excluded.evidence,
                    },
                )
                session.execute(stmt)

    def get_graph(self, doc_id: str) -> DependencyGraph | None:
        """Concept.questions is reconstructed by joining `questions` here — never stored on
        the concept row. See design doc §3."""
        with session_scope() as session:
            rows = session.scalars(
                select(ConceptRow)
                .where(ConceptRow.doc_id == doc_id)
                .options(selectinload(ConceptRow.questions))
            ).all()
            if not rows:
                # No stored graph for this doc_id. (A saved graph with zero concepts is
                # indistinguishable from "never saved" under this schema — accepted, since
                # graph_builder cannot produce zero concepts from non-empty chapter text.)
                return None
            return DependencyGraph(doc_id=doc_id, concepts=[_to_concept(r) for r in rows])

    def save_questions(self, concept_id: str, questions: list[Question]) -> None:
        """Upsert every question in `questions`. Deliberately does NOT delete rows for this
        concept_id that are missing from the list — a deviation from the design doc, which
        described full replace-list semantics matching InMemoryStore's raw dict behavior.

        Found during implementation: `history_entries.question_id` and
        `.diagnosis_targeted_question_id` are foreign keys with no ON DELETE clause, so
        deleting a question a student has already been asked (and that a history_entries row
        now references) would raise an integrity error — and destroying that record would be
        wrong even if it didn't. Every real call site (ingestion's full initial list;
        study_session.py's `[*existing, targeted]`) only ever grows the list, so this is a
        behavior-preserving narrowing, not a functional change.
        """
        with session_scope() as session:
            for q in questions:
                stmt = pg_insert(QuestionRow).values(
                    id=q.id,
                    concept_id=concept_id,
                    prompt=q.prompt,
                    expected_answer_notes=q.expected_answer_notes,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "concept_id": stmt.excluded.concept_id,
                        "prompt": stmt.excluded.prompt,
                        "expected_answer_notes": stmt.excluded.expected_answer_notes,
                    },
                )
                session.execute(stmt)

    def get_questions(self, concept_id: str) -> list[Question] | None:
        with session_scope() as session:
            rows = session.scalars(
                select(QuestionRow).where(QuestionRow.concept_id == concept_id)
            ).all()
            if rows:
                return [_to_question(r) for r in rows]
            # No question rows: distinguish "concept exists, has none yet" ([]) from
            # "no such concept" (None), mirroring InMemoryStore's dict.get() semantics.
            return [] if session.get(ConceptRow, concept_id) is not None else None

    def save_study_session(self, study_session: StudySession) -> None:
        """`history` is always resaved as a whole snapshot (the router appends to
        `study_session.history` in place, then calls this once) — so it's safe to delete and
        fully re-insert on every call. Unlike `questions`, nothing has a foreign key pointing
        at `history_entries.id`, so this can never violate referential integrity.
        """
        with session_scope() as session:
            stmt = pg_insert(StudySessionRow).values(
                id=study_session.id,
                doc_id=study_session.doc_id,
                current_concept_id=study_session.current_concept_id,
                status=study_session.status.value,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "doc_id": stmt.excluded.doc_id,
                    "current_concept_id": stmt.excluded.current_concept_id,
                    "status": stmt.excluded.status,
                },
            )
            session.execute(stmt)

            session.execute(
                delete(HistoryEntryRow).where(
                    HistoryEntryRow.study_session_id == study_session.id
                )
            )
            for seq, entry in enumerate(study_session.history):
                diagnosis = entry.diagnosis
                session.add(
                    HistoryEntryRow(
                        study_session_id=study_session.id,
                        seq=seq,
                        question_id=entry.question.id,
                        answer_text=entry.answer.text,
                        eval_correct=entry.evaluation.correct,
                        eval_explanation=entry.evaluation.explanation,
                        diagnosis_suspected_concept_id=(
                            diagnosis.suspected_gap_concept_id if diagnosis else None
                        ),
                        diagnosis_reasoning=diagnosis.reasoning if diagnosis else None,
                        diagnosis_targeted_question_id=(
                            diagnosis.targeted_question.id if diagnosis else None
                        ),
                    )
                )

    def get_study_session(self, study_session_id: str) -> StudySession | None:
        with session_scope() as session:
            row = session.get(
                StudySessionRow,
                study_session_id,
                options=[
                    selectinload(StudySessionRow.history).selectinload(HistoryEntryRow.question),
                    selectinload(StudySessionRow.history).selectinload(
                        HistoryEntryRow.targeted_question
                    ),
                ],
            )
            if row is None:
                return None

            history = []
            for h in row.history:  # relationship declares order_by=HistoryEntryRow.seq
                diagnosis = None
                if h.diagnosis_suspected_concept_id is not None:
                    diagnosis = DiagnosisResult(
                        suspected_gap_concept_id=h.diagnosis_suspected_concept_id,
                        reasoning=h.diagnosis_reasoning or "",
                        targeted_question=_to_question(h.targeted_question),
                    )
                history.append(
                    HistoryEntry(
                        question=_to_question(h.question),
                        answer=Answer(question_id=h.question_id, text=h.answer_text),
                        evaluation=EvaluationResult(
                            correct=h.eval_correct, explanation=h.eval_explanation
                        ),
                        diagnosis=diagnosis,
                    )
                )

            return StudySession(
                id=row.id,
                doc_id=row.doc_id,
                current_concept_id=row.current_concept_id,
                history=history,
                status=StudySessionStatus(row.status),
            )
