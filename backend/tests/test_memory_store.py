"""Unit tests for InMemoryStore and its helpers.

Free and fast — no database, no API key. InMemoryStore had no dedicated coverage before
this file: it was exercised only indirectly through `test_flow.py`'s API-level walks, which
never touched deletion or the session-listing filter directly.

The point of several of these is *parity*: InMemoryStore hand-rolls behavior that
PostgresStore gets from the database (ON DELETE CASCADE, a filtered ORDER BY). Where the
two are meant to agree, the equivalent Postgres assertion lives in test_postgres_store.py.
"""

from datetime import UTC, datetime, timedelta

from app.models import (
    Concept,
    DependencyGraph,
    Question,
    StudySession,
    StudySessionStatus,
)
from app.store.memory_store import SNIPPET_CHARS, InMemoryStore, make_snippet


class TestMakeSnippet:
    """The label shown for a chapter uploaded without a title."""

    def test_short_text_is_returned_whole(self) -> None:
        assert make_snippet("A short chapter.") == "A short chapter."

    def test_whitespace_is_collapsed_to_single_spaces(self) -> None:
        # Chapter text is pasted prose full of newlines; a list row is one line.
        assert make_snippet("first line\n\nsecond\tline  here") == "first line second line here"

    def test_long_text_is_truncated_with_an_ellipsis(self) -> None:
        source = "word " * 100
        snippet = make_snippet(source)

        assert snippet.endswith("…")
        # Bounded, not exact: the budget is trimmed of trailing whitespace before the
        # ellipsis is appended, so cutting mid-space yields one character fewer.
        assert len(snippet) <= SNIPPET_CHARS + 1
        assert not snippet[:-1].endswith(" "), "trailing space is trimmed before the ellipsis"
        # Whatever survives is a genuine prefix of the collapsed source, not a reflow.
        assert " ".join(source.split()).startswith(snippet[:-1])

    def test_text_exactly_at_the_budget_is_not_truncated(self) -> None:
        exact = "x" * SNIPPET_CHARS
        assert make_snippet(exact) == exact
        assert make_snippet("x" * (SNIPPET_CHARS + 1)).endswith("…")

    def test_empty_text_yields_empty_string(self) -> None:
        assert make_snippet("") == ""
        assert make_snippet("   \n  ") == ""


class TestDeleteDocument:
    """InMemoryStore's hand-rolled equivalent of PostgresStore's ON DELETE CASCADE."""

    def _populate(self, store: InMemoryStore, doc_id: str) -> None:
        store.save_document(doc_id, "text", f"Title of {doc_id}")
        store.save_graph(
            DependencyGraph(
                doc_id=doc_id, concepts=[Concept(id=f"{doc_id}:a", name="A", summary="s")]
            )
        )
        store.save_questions(
            f"{doc_id}:a",
            [
                Question(
                    id=f"{doc_id}:a:q1",
                    concept_id=f"{doc_id}:a",
                    prompt="p",
                    expected_answer_notes="n",
                )
            ],
        )
        store.save_study_session(
            StudySession(id=f"{doc_id}_sess", doc_id=doc_id, current_concept_id=f"{doc_id}:a")
        )

    def test_removes_everything_derived_from_the_document(self) -> None:
        store = InMemoryStore()
        self._populate(store, "doomed")

        store.delete_document("doomed")

        assert store.get_document("doomed") is None
        assert store.get_graph("doomed") is None
        assert store.get_questions("doomed:a") is None
        assert store.get_study_session("doomed_sess") is None
        # The title is dropped too, or a re-used doc_id would inherit the old label.
        assert store.list_unfinished_sessions() == []

    def test_leaves_other_documents_alone(self) -> None:
        """Questions are found by id prefix, so a doc_id that prefixes another must not match."""
        store = InMemoryStore()
        self._populate(store, "doc")
        self._populate(store, "doc2")

        store.delete_document("doc")

        assert store.get_document("doc2") == "text"
        assert store.get_questions("doc2:a") is not None
        assert store.get_study_session("doc2_sess") is not None

    def test_unknown_id_is_a_noop(self) -> None:
        """Called on the ingestion failure path, where the document may not exist yet."""
        store = InMemoryStore()
        self._populate(store, "kept")
        store.delete_document("never-existed")
        assert store.get_document("kept") == "text"


class TestDeleteStudySession:
    def test_removes_the_session(self) -> None:
        store = InMemoryStore()
        store.save_study_session(StudySession(id="doomed", doc_id="d"))

        store.delete_study_session("doomed")

        assert store.get_study_session("doomed") is None

    def test_leaves_other_sessions_alone(self) -> None:
        store = InMemoryStore()
        store.save_study_session(StudySession(id="doomed", doc_id="d"))
        store.save_study_session(StudySession(id="kept", doc_id="d"))

        store.delete_study_session("doomed")

        assert store.get_study_session("kept") is not None

    def test_unknown_id_is_a_noop(self) -> None:
        store = InMemoryStore()
        store.save_study_session(StudySession(id="kept", doc_id="d"))
        store.delete_study_session("never-existed")
        assert store.get_study_session("kept") is not None


class TestListUnfinishedSessions:
    def _store_with_graph(self, concepts: int = 2) -> InMemoryStore:
        store = InMemoryStore()
        store.save_document("d", "A chapter about things.", "Chapter")
        store.save_graph(
            DependencyGraph(
                doc_id="d",
                concepts=[Concept(id=f"d:c{i}", name=f"C{i}", summary="s") for i in range(concepts)],
            )
        )
        return store

    def test_excludes_completed_sessions(self) -> None:
        store = self._store_with_graph()
        store.save_study_session(StudySession(id="active", doc_id="d"))
        store.save_study_session(
            StudySession(id="diagnosing", doc_id="d", status=StudySessionStatus.DIAGNOSING)
        )
        store.save_study_session(
            StudySession(id="done", doc_id="d", status=StudySessionStatus.COMPLETED)
        )

        assert {row.id for row in store.list_unfinished_sessions()} == {"active", "diagnosing"}

    def test_sorted_most_recently_updated_first(self) -> None:
        store = self._store_with_graph()
        store.save_study_session(StudySession(id="older", doc_id="d"))
        store.save_study_session(StudySession(id="newer", doc_id="d"))

        # save_study_session stamps updated_at, so insertion order decides this. Force an
        # unambiguous gap rather than relying on two same-microsecond writes.
        store._study_sessions["older"].updated_at = datetime.now(UTC) - timedelta(hours=1)

        assert [row.id for row in store.list_unfinished_sessions()] == ["newer", "older"]

    def test_reports_title_snippet_and_concept_count(self) -> None:
        store = self._store_with_graph(concepts=3)
        store.save_study_session(StudySession(id="s", doc_id="d", current_concept_id="d:c1"))

        row = store.list_unfinished_sessions()[0]
        assert row.title == "Chapter"
        assert row.text_snippet == "A chapter about things."
        assert row.total_concepts == 3
        assert row.current_concept_id == "d:c1"

    def test_session_whose_graph_was_never_saved_reports_zero_concepts(self) -> None:
        """Matches PostgresStore, where the correlated count returns 0 rather than dropping
        the session from the result."""
        store = InMemoryStore()
        store.save_document("d", "text")
        store.save_study_session(StudySession(id="s", doc_id="d"))

        assert store.list_unfinished_sessions()[0].total_concepts == 0
