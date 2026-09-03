"""Storage layer.

`Store` is the interface the rest of the app depends on. `InMemoryStore` is the free/no-setup
implementation, used whenever `settings.database_url` is unset (so tests never need a real
database). `PostgresStore` (postgres_store.py) is the persistent implementation; `get_store()`
in `app/store/__init__.py` picks between them.
"""

from abc import ABC, abstractmethod
from datetime import UTC, datetime

from app.models import (
    Concept,
    DependencyGraph,
    Question,
    StudySession,
    StudySessionStatus,
    StudySessionSummaryRow,
)


SNIPPET_CHARS = 60


def make_snippet(text: str) -> str:
    """A short single-line label for a document with no title.

    Computed server-side rather than shipping the raw text: a chapter is thousands of
    characters, and the list renders one line of it. Both Store implementations use this so
    the two backends can't drift on how an untitled chapter is labelled.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= SNIPPET_CHARS:
        return collapsed
    return collapsed[:SNIPPET_CHARS].rstrip() + "…"


class Store(ABC):
    # --- documents ---
    @abstractmethod
    def save_document(self, doc_id: str, text: str, title: str | None = None) -> None: ...

    @abstractmethod
    def get_document(self, doc_id: str) -> str | None: ...

    @abstractmethod
    def delete_document(self, doc_id: str) -> None:
        """Drop a document and everything derived from it (graph, concepts, questions).

        Exists so a failed ingestion can roll itself back: `routers/ingestion.py` must
        persist the document before `build_graph()` can reference it by FK, so an LLM
        failure mid-pipeline would otherwise strand a document row with no concepts.
        Idempotent — deleting an unknown doc_id is not an error.
        """
        ...

    # --- dependency graphs ---
    @abstractmethod
    def save_graph(self, graph: DependencyGraph) -> None: ...

    @abstractmethod
    def get_graph(self, doc_id: str) -> DependencyGraph | None: ...

    # --- questions ---
    @abstractmethod
    def save_questions(self, concept_id: str, questions: list[Question]) -> None: ...

    @abstractmethod
    def get_questions(self, concept_id: str) -> list[Question] | None: ...

    # --- study sessions ---
    @abstractmethod
    def save_study_session(self, study_session: StudySession) -> None:
        """Persist the session, stamping `updated_at` to now.

        The stamp is applied to the passed-in object as well as the stored copy, so a
        caller that returns the session it just saved reports the real write time. Both
        implementations do this identically.
        """
        ...

    @abstractmethod
    def get_study_session(self, study_session_id: str) -> StudySession | None: ...

    @abstractmethod
    def delete_study_session(self, study_session_id: str) -> None:
        """Remove a session and its history. Idempotent — deleting an unknown id is not an error."""
        ...

    @abstractmethod
    def list_unfinished_sessions(self) -> list[StudySessionSummaryRow]:
        """Sessions that can still be continued, most recently updated first.

        Completed sessions are excluded: they can't be resumed, so the "continue a
        session" list empties itself as work finishes and never needs pruning.

        Returns the internal row shape, without `completed_concepts` — see
        `StudySessionSummaryRow` for why that one field is the router's job.
        """
        ...


class InMemoryStore(Store):
    def __init__(self) -> None:
        self._documents: dict[str, str] = {}
        # Kept beside _documents rather than folded into it so `get_document() -> str | None`
        # keeps its contract and no existing caller changes.
        self._titles: dict[str, str | None] = {}
        self._graphs: dict[str, DependencyGraph] = {}
        self._questions: dict[str, list[Question]] = {}
        self._study_sessions: dict[str, StudySession] = {}

    def save_document(self, doc_id: str, text: str, title: str | None = None) -> None:
        self._documents[doc_id] = text
        self._titles[doc_id] = title

    def get_document(self, doc_id: str) -> str | None:
        return self._documents.get(doc_id)

    def delete_document(self, doc_id: str) -> None:
        """Hand-rolled equivalent of the ON DELETE CASCADE PostgresStore gets for free.
        Questions are keyed by concept id, not doc id, so they're found via the id
        convention (`{doc_id}:{slug}` for concepts, `{concept_id}:{suffix}` for questions)
        rather than by walking the graph — that way a partially-built graph, or one that
        was never saved, still cleans up completely.
        """
        self._documents.pop(doc_id, None)
        self._titles.pop(doc_id, None)
        self._graphs.pop(doc_id, None)
        prefix = f"{doc_id}:"
        for concept_id in [cid for cid in self._questions if cid.startswith(prefix)]:
            del self._questions[concept_id]
        for session_id in [
            sid for sid, s in self._study_sessions.items() if s.doc_id == doc_id
        ]:
            del self._study_sessions[session_id]

    def save_graph(self, graph: DependencyGraph) -> None:
        self._graphs[graph.doc_id] = graph

    def get_graph(self, doc_id: str) -> DependencyGraph | None:
        """`Concept.questions` is reconstructed from `self._questions` on every read, never
        stored on the graph object itself — the same contract PostgresStore.get_graph()
        implements via a join (see docs/specs/2026-08-21-persistent-storage-design.md §3).
        This is what makes a plain `save_questions()` call, with no companion graph
        mutation, enough for a newly-registered question to show up on its concept's next
        load — in either backend.
        """
        graph = self._graphs.get(doc_id)
        if graph is None:
            return None
        return DependencyGraph(
            doc_id=graph.doc_id,
            concepts=[
                Concept(
                    id=c.id,
                    name=c.name,
                    summary=c.summary,
                    depends_on=c.depends_on,
                    evidence=c.evidence,
                    questions=self._questions.get(c.id, []),
                )
                for c in graph.concepts
            ],
        )

    def save_questions(self, concept_id: str, questions: list[Question]) -> None:
        self._questions[concept_id] = questions

    def get_questions(self, concept_id: str) -> list[Question] | None:
        return self._questions.get(concept_id)

    def save_study_session(self, study_session: StudySession) -> None:
        study_session.updated_at = datetime.now(UTC)
        self._study_sessions[study_session.id] = study_session

    def get_study_session(self, study_session_id: str) -> StudySession | None:
        return self._study_sessions.get(study_session_id)

    def delete_study_session(self, study_session_id: str) -> None:
        self._study_sessions.pop(study_session_id, None)

    def list_unfinished_sessions(self) -> list[StudySessionSummaryRow]:
        rows = [
            StudySessionSummaryRow(
                id=s.id,
                doc_id=s.doc_id,
                title=self._titles.get(s.doc_id),
                text_snippet=make_snippet(self._documents.get(s.doc_id, "")),
                status=s.status,
                current_concept_id=s.current_concept_id,
                # A session whose graph was never saved reports 0 rather than raising —
                # PostgresStore's count subquery returns 0 for the same case.
                total_concepts=len(graph.concepts)
                if (graph := self._graphs.get(s.doc_id)) is not None
                else 0,
                updated_at=s.updated_at,
            )
            for s in self._study_sessions.values()
            if s.status is not StudySessionStatus.COMPLETED
        ]
        rows.sort(key=lambda r: r.updated_at, reverse=True)
        return rows
