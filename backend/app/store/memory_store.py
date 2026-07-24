"""Storage layer.

`Store` is the interface the rest of the app depends on. `InMemoryStore` is the
only implementation for now; swapping in Postgres later means writing a new
subclass and changing `get_store()` — nothing else should need to change.
"""

from abc import ABC, abstractmethod
from functools import lru_cache

from app.models import DependencyGraph, Question, Session


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

    # --- sessions ---
    @abstractmethod
    def save_session(self, session: Session) -> None: ...

    @abstractmethod
    def get_session(self, session_id: str) -> Session | None: ...


class InMemoryStore(Store):
    def __init__(self) -> None:
        self._documents: dict[str, str] = {}
        self._graphs: dict[str, DependencyGraph] = {}
        self._questions: dict[str, list[Question]] = {}
        self._sessions: dict[str, Session] = {}

    def save_document(self, doc_id: str, text: str) -> None:
        self._documents[doc_id] = text

    def get_document(self, doc_id: str) -> str | None:
        return self._documents.get(doc_id)

    def save_graph(self, graph: DependencyGraph) -> None:
        self._graphs[graph.doc_id] = graph

    def get_graph(self, doc_id: str) -> DependencyGraph | None:
        return self._graphs.get(doc_id)

    def save_questions(self, concept_id: str, questions: list[Question]) -> None:
        self._questions[concept_id] = questions

    def get_questions(self, concept_id: str) -> list[Question] | None:
        return self._questions.get(concept_id)

    def save_session(self, session: Session) -> None:
        self._sessions[session.id] = session

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)


@lru_cache
def get_store() -> Store:
    return InMemoryStore()
