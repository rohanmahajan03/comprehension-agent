"""Storage layer.

`Store` is the interface the rest of the app depends on. `InMemoryStore` is the free/no-setup
implementation, used whenever `settings.database_url` is unset (so tests never need a real
database). `PostgresStore` (postgres_store.py) is the persistent implementation; `get_store()`
in `app/store/__init__.py` picks between them.
"""

from abc import ABC, abstractmethod

from app.models import Concept, DependencyGraph, Question, StudySession


class Store(ABC):
    # --- documents ---
    @abstractmethod
    def save_document(self, doc_id: str, text: str) -> None: ...

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
    def save_study_session(self, study_session: StudySession) -> None: ...

    @abstractmethod
    def get_study_session(self, study_session_id: str) -> StudySession | None: ...


class InMemoryStore(Store):
    def __init__(self) -> None:
        self._documents: dict[str, str] = {}
        self._graphs: dict[str, DependencyGraph] = {}
        self._questions: dict[str, list[Question]] = {}
        self._study_sessions: dict[str, StudySession] = {}

    def save_document(self, doc_id: str, text: str) -> None:
        self._documents[doc_id] = text

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
        self._graphs.pop(doc_id, None)
        prefix = f"{doc_id}:"
        for concept_id in [cid for cid in self._questions if cid.startswith(prefix)]:
            del self._questions[concept_id]

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
        self._study_sessions[study_session.id] = study_session

    def get_study_session(self, study_session_id: str) -> StudySession | None:
        return self._study_sessions.get(study_session_id)
