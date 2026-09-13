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
    DocumentStatus,
    DocumentSummary,
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
    def save_document(
        self,
        doc_id: str,
        text: str,
        title: str | None = None,
        status: DocumentStatus = DocumentStatus.FINALIZED,
    ) -> None: ...

    @abstractmethod
    def get_document(self, doc_id: str) -> str | None: ...

    @abstractmethod
    def get_document_status(self, doc_id: str) -> DocumentStatus | None:
        """The document's pipeline-1 status, or None if there's no such document."""
        ...

    @abstractmethod
    def finalize_document(self, doc_id: str) -> None:
        """Move a document to FINALIZED, making it usable for study sessions.

        Idempotent, and one-directional: nothing ever moves a document back to DRAFT,
        since re-opening a finalized graph for editing would strand the questions and
        study sessions already built on it (see the design doc's §8).
        """
        ...

    @abstractmethod
    def delete_document(self, doc_id: str) -> None:
        """Drop a document and everything derived from it (graph, concepts, questions).

        Exists so a failed ingestion can roll itself back: `routers/ingestion.py` must
        persist the document before `build_graph()` can reference it by FK, so an LLM
        failure mid-pipeline would otherwise strand a document row with no concepts.
        Idempotent — deleting an unknown doc_id is not an error.
        """
        ...

    @abstractmethod
    def list_documents(self) -> list[DocumentSummary]:
        """Finalized documents with at least one concept, most recently created first.

        Zero-concept documents are excluded rather than merely unusual: `get_graph()`
        can't tell "a graph with zero concepts" apart from "never saved" (see
        PostgresStore.get_graph), so listing one here would produce a link that 404s.
        `routers/ingestion.py` now rejects zero-concept extractions outright, so this
        only ever filters out documents that predate that fix.

        DRAFT documents are excluded for a related reason: a draft *does* have concepts
        (extraction already ran) but has no questions yet and can't host a study session,
        so listing it would offer the student a chapter that 409s the moment they start.
        """
        ...

    # --- dependency graphs ---
    @abstractmethod
    def save_graph(self, graph: DependencyGraph) -> None: ...

    @abstractmethod
    def get_graph(self, doc_id: str) -> DependencyGraph | None: ...

    @abstractmethod
    def delete_concept(self, concept_id: str) -> None:
        """Remove a single concept. Idempotent — an unknown id is not an error.

        Exists for draft-mode graph editing; normal ingestion never drops a concept after
        extraction. `save_graph()` can't cover this: it deliberately only ever upserts the
        concepts it's given and never deletes the ones missing from that list (same
        upsert-only contract as `save_questions`), so removing a concept for real needs
        its own call.

        Does NOT scrub references to this id from other concepts' `depends_on`/`evidence`
        — the caller already holds the whole graph to build the edited version, so it
        strips those itself and persists them with `save_graph()`.
        """
        ...

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
        self._status: dict[str, DocumentStatus] = {}
        self._created_at: dict[str, datetime] = {}
        self._graphs: dict[str, DependencyGraph] = {}
        self._questions: dict[str, list[Question]] = {}
        self._study_sessions: dict[str, StudySession] = {}

    def save_document(
        self,
        doc_id: str,
        text: str,
        title: str | None = None,
        status: DocumentStatus = DocumentStatus.FINALIZED,
    ) -> None:
        self._documents[doc_id] = text
        self._titles[doc_id] = title
        self._status[doc_id] = status
        # setdefault, not assignment: PostgresStore's upsert omits this column from its
        # on_conflict_do_update, so a re-save there preserves the original insert's
        # server_default value — this mirrors that instead of resetting it on every call.
        self._created_at.setdefault(doc_id, datetime.now(UTC))

    def get_document(self, doc_id: str) -> str | None:
        return self._documents.get(doc_id)

    def get_document_status(self, doc_id: str) -> DocumentStatus | None:
        return self._status.get(doc_id)

    def finalize_document(self, doc_id: str) -> None:
        if doc_id in self._status:
            self._status[doc_id] = DocumentStatus.FINALIZED

    def delete_document(self, doc_id: str) -> None:
        """Hand-rolled equivalent of the ON DELETE CASCADE PostgresStore gets for free.
        Questions are keyed by concept id, not doc id, so they're found via the id
        convention (`{doc_id}:{slug}` for concepts, `{concept_id}:{suffix}` for questions)
        rather than by walking the graph — that way a partially-built graph, or one that
        was never saved, still cleans up completely.
        """
        self._documents.pop(doc_id, None)
        self._titles.pop(doc_id, None)
        self._status.pop(doc_id, None)
        self._created_at.pop(doc_id, None)
        self._graphs.pop(doc_id, None)
        prefix = f"{doc_id}:"
        for concept_id in [cid for cid in self._questions if cid.startswith(prefix)]:
            del self._questions[concept_id]
        for session_id in [
            sid for sid, s in self._study_sessions.items() if s.doc_id == doc_id
        ]:
            del self._study_sessions[session_id]

    def list_documents(self) -> list[DocumentSummary]:
        rows = []
        for doc_id, text in self._documents.items():
            if self._status.get(doc_id) is not DocumentStatus.FINALIZED:
                continue
            graph = self._graphs.get(doc_id)
            total_concepts = len(graph.concepts) if graph is not None else 0
            if total_concepts == 0:
                continue
            rows.append(
                DocumentSummary(
                    id=doc_id,
                    title=self._titles.get(doc_id),
                    text_snippet=make_snippet(text),
                    total_concepts=total_concepts,
                    created_at=self._created_at[doc_id],
                )
            )
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows

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

    def delete_concept(self, concept_id: str) -> None:
        """Dropping the concept's questions alongside it is the hand-rolled equivalent of
        the ON DELETE CASCADE from `concepts` to `questions` PostgresStore gets for free
        (moot in practice — a concept is only deletable while its document is still a
        draft, which is before any question exists)."""
        # Concepts live inside their document's graph, so the owning doc is found via the
        # id convention ({doc_id}:{slug}) rather than by scanning every stored graph.
        doc_id = concept_id.split(":", 1)[0]
        graph = self._graphs.get(doc_id)
        if graph is not None:
            graph.concepts = [c for c in graph.concepts if c.id != concept_id]
        self._questions.pop(concept_id, None)

    def save_questions(self, concept_id: str, questions: list[Question]) -> None:
        self._questions[concept_id] = questions

    def get_questions(self, concept_id: str) -> list[Question] | None:
        questions = self._questions.get(concept_id)
        if questions is not None:
            return questions
        # Distinguish "concept exists, has no questions yet" ([]) from "no such concept"
        # (None), which a raw dict lookup can't. PostgresStore.get_questions has always
        # drawn that line; here it only became observable with review mode, which is the
        # first thing to leave a saved concept without a question set.
        doc_id = concept_id.split(":", 1)[0]
        graph = self._graphs.get(doc_id)
        exists = graph is not None and any(c.id == concept_id for c in graph.concepts)
        return [] if exists else None

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
