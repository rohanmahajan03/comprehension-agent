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
