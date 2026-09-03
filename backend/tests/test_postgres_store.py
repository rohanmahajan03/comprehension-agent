"""Tests for PostgresStore against a real Postgres instance.

⚠️ DESTRUCTIVE. Every test starts by TRUNCATEing all five tables. It therefore reads
`TEST_DATABASE_URL`, **not** `DATABASE_URL` — pointing it at the working database would
delete real documents, graphs, and study sessions. Two independent guards enforce that:
the separate variable, and a check that the database name ends in `_test`.

Skipped when TEST_DATABASE_URL is unset — the same opt-in pattern the `geval` suites use
for LLM_API_KEY, just gated on database availability instead. Run it via:

    docker compose up -d postgres
    cd backend && TEST_DATABASE_URL=postgresql+psycopg://comprehension_agent:devpassword@localhost:5433/comprehension_agent_test \\
      .venv/bin/pytest tests/test_postgres_store.py -v

The test database is created on first volume init by docker/postgres/initdb/, and must be
migrated (`alembic upgrade head` against the same URL) before the suite will pass.

No testcontainers: like the geval suites expect a real API key, these expect a real,
already-migrated Postgres.
"""

import os

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db.engine import _session_factory, get_engine
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
from app.store.postgres_store import PostgresStore


@pytest.fixture(autouse=True, scope="module")
def _require_database():
    """Point the engine at a dedicated test database, and refuse to run against any other.

    This suite truncates. The guards exist because a previous run of it, pointed at the
    working database via an exported DATABASE_URL, destroyed real documents and study
    sessions:

    1. The URL comes from `TEST_DATABASE_URL`. Exporting `DATABASE_URL` — the variable that
       points at real data — no longer enables this suite; it skips instead.
    2. The database name must end in `_test`. A `TEST_DATABASE_URL` aimed at the working
       database fails loudly rather than truncating it.

    Failing (not skipping) on guard 2 is deliberate: a misconfigured URL is a mistake worth
    surfacing, whereas an unset one just means "not running DB tests right now".
    """
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("TEST_DATABASE_URL not set — this suite requires a real Postgres instance")

    database_name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not database_name.endswith("_test"):
        pytest.fail(
            f"refusing to run destructive tests against database {database_name!r}: "
            "TEST_DATABASE_URL must name a database whose name ends in '_test'"
        )

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    # Settings and engine are both lru_cached, so they must be rebuilt after the swap —
    # otherwise a cached engine from an earlier import still points at the old URL.
    for cached in (get_settings, get_engine, _session_factory):
        cached.cache_clear()
    yield
    if previous is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous
    for cached in (get_settings, get_engine, _session_factory):
        cached.cache_clear()


@pytest.fixture(autouse=True)
def _clean_tables(_require_database: None):
    """Truncate everything before each test so cases can't see each other's rows.

    Real DB, not a rollback-per-test fixture: TRUNCATE is simple and fast enough for these
    five small tables, and keeps each test's assertions readable against a known-empty start
    rather than reasoning about pollution from whatever ran before it.

    Depends explicitly on `_require_database` — without that, pytest doesn't guarantee the
    skip-check fixture runs first, and this one calling get_engine() with an empty
    DATABASE_URL fails with a connection error instead of skipping cleanly.
    """
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE documents, concepts, questions, study_sessions, history_entries "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield


@pytest.fixture
def store() -> PostgresStore:
    return PostgresStore()


def test_document_round_trip(store: PostgresStore) -> None:
    store.save_document("doc1", "chapter text")
    assert store.get_document("doc1") == "chapter text"
    assert store.get_document("does-not-exist") is None


def test_graph_round_trip_preserves_jsonb_fields_verbatim(store: PostgresStore) -> None:
    """depends_on/evidence are JSONB (design doc §2) — confirm they survive a round trip
    without transformation, including a character (em-dash) that has broken other parts of
    this project when re-serialized carelessly."""
    store.save_document("doc1", "text")
    graph = DependencyGraph(
        doc_id="doc1",
        concepts=[
            Concept(
                id="doc1:a",
                name="A",
                summary="A summary — em dash intact.",
                depends_on=["doc1:b"],
                evidence={"doc1:b": "B justifies A."},
            ),
            Concept(id="doc1:b", name="B", summary="B summary.", depends_on=[]),
        ],
    )
    store.save_graph(graph)

    loaded = store.get_graph("doc1")
    assert loaded is not None
    assert {c.id for c in loaded.concepts} == {"doc1:a", "doc1:b"}

    a = next(c for c in loaded.concepts if c.id == "doc1:a")
    assert a.depends_on == ["doc1:b"]
    assert a.evidence == {"doc1:b": "B justifies A."}
    assert a.summary == "A summary — em dash intact."
    assert a.questions == []  # none saved yet


def test_get_graph_returns_none_for_unknown_doc(store: PostgresStore) -> None:
    assert store.get_graph("does-not-exist") is None


def test_question_appears_on_graph_reload_without_a_second_save_graph_call(
    store: PostgresStore,
) -> None:
    """The regression test this design exists to prevent (see design doc §3): a question
    registered via save_questions() alone must be visible on the next get_graph() — no
    companion graph mutation required, in either Store implementation.
    """
    store.save_document("doc1", "text")
    graph = DependencyGraph(
        doc_id="doc1",
        concepts=[Concept(id="doc1:a", name="A", summary="A summary.")],
    )
    store.save_graph(graph)

    q1 = Question(id="doc1:a:q1", concept_id="doc1:a", prompt="What is A?", expected_answer_notes="notes")
    store.save_questions("doc1:a", [q1])

    reloaded = store.get_graph("doc1")
    a = next(c for c in reloaded.concepts if c.id == "doc1:a")
    assert [q.id for q in a.questions] == ["doc1:a:q1"]


def test_get_questions_distinguishes_no_concept_from_no_questions(store: PostgresStore) -> None:
    store.save_document("doc1", "text")
    graph = DependencyGraph(
        doc_id="doc1",
        concepts=[Concept(id="doc1:a", name="A", summary="A summary.")],
    )
    store.save_graph(graph)

    assert store.get_questions("doc1:a") == [], "concept exists, has none yet"
    assert store.get_questions("doc1:does-not-exist") is None, "no such concept"

    q1 = Question(id="doc1:a:q1", concept_id="doc1:a", prompt="q", expected_answer_notes="a")
    store.save_questions("doc1:a", [q1])
    assert store.get_questions("doc1:a") == [q1]


def test_save_questions_only_grows_never_deletes(store: PostgresStore) -> None:
    """Deliberate deviation from the design doc's stated replace-list semantics (see
    postgres_store.py's save_questions docstring): deleting a question that a
    history_entries row already references would violate the foreign key, and would be the
    wrong thing to do even if it didn't. Confirmed here as current, intended behavior."""
    store.save_document("doc1", "text")
    graph = DependencyGraph(
        doc_id="doc1",
        concepts=[Concept(id="doc1:a", name="A", summary="A summary.")],
    )
    store.save_graph(graph)

    q1 = Question(id="doc1:a:q1", concept_id="doc1:a", prompt="q1", expected_answer_notes="a1")
    store.save_questions("doc1:a", [q1])
    q2 = Question(id="doc1:a:q2", concept_id="doc1:a", prompt="q2", expected_answer_notes="a2")
    # A shorter list than what's already stored — must not drop q1.
    store.save_questions("doc1:a", [q2])

    assert {q.id for q in store.get_questions("doc1:a")} == {"doc1:a:q1", "doc1:a:q2"}


def test_study_session_round_trip_with_diagnosis(store: PostgresStore) -> None:
    """Exercises both question foreign keys on history_entries: the answered question and
    the diagnosis's targeted_question."""
    store.save_document("doc1", "text")
    graph = DependencyGraph(
        doc_id="doc1",
        concepts=[
            Concept(id="doc1:a", name="A", summary="A summary.", depends_on=["doc1:b"]),
            Concept(id="doc1:b", name="B", summary="B summary."),
        ],
    )
    store.save_graph(graph)
    q1 = Question(id="doc1:a:q1", concept_id="doc1:a", prompt="What is A?", expected_answer_notes="notes A")
    q2 = Question(
        id="doc1:b:diagnostic1", concept_id="doc1:b", prompt="Diagnostic about B", expected_answer_notes="notes B"
    )
    store.save_questions("doc1:a", [q1])
    store.save_questions("doc1:b", [q2])

    session = StudySession(
        id="sess1", doc_id="doc1", current_concept_id="doc1:a", status=StudySessionStatus.DIAGNOSING
    )
    session.history.append(
        HistoryEntry(
            question=q1,
            answer=Answer(question_id=q1.id, text="a wrong answer"),
            evaluation=EvaluationResult(correct=False, explanation="missing X"),
            diagnosis=DiagnosisResult(
                suspected_gap_concept_id="doc1:b", reasoning="because Y", targeted_question=q2
            ),
        )
    )
    store.save_study_session(session)

    loaded = store.get_study_session("sess1")
    assert loaded is not None
    assert loaded.status == StudySessionStatus.DIAGNOSING
    assert loaded.current_concept_id == "doc1:a"
    assert len(loaded.history) == 1

    entry = loaded.history[0]
    assert entry.question.id == q1.id
    assert entry.question.prompt == q1.prompt  # full Question, not just an id, reconstructed
    assert entry.answer == Answer(question_id=q1.id, text="a wrong answer")
    assert entry.evaluation == EvaluationResult(correct=False, explanation="missing X")
    assert entry.diagnosis is not None
    assert entry.diagnosis.suspected_gap_concept_id == "doc1:b"
    assert entry.diagnosis.targeted_question.id == q2.id
    assert entry.diagnosis.targeted_question.prompt == q2.prompt


def test_study_session_with_no_diagnosis(store: PostgresStore) -> None:
    """A correct answer: diagnosis is None end to end, not a row of nulls masquerading
    as one — get_study_session must reconstruct None, not a DiagnosisResult of blanks."""
    store.save_document("doc1", "text")
    store.save_graph(DependencyGraph(doc_id="doc1", concepts=[Concept(id="doc1:a", name="A", summary="s")]))
    q1 = Question(id="doc1:a:q1", concept_id="doc1:a", prompt="q", expected_answer_notes="a")
    store.save_questions("doc1:a", [q1])

    session = StudySession(id="sess1", doc_id="doc1", status=StudySessionStatus.ACTIVE)
    session.history.append(
        HistoryEntry(
            question=q1,
            answer=Answer(question_id=q1.id, text="right answer"),
            evaluation=EvaluationResult(correct=True, explanation="good"),
            diagnosis=None,
        )
    )
    store.save_study_session(session)

    loaded = store.get_study_session("sess1")
    assert loaded.history[0].diagnosis is None


def test_get_study_session_returns_none_for_unknown_id(store: PostgresStore) -> None:
    assert store.get_study_session("does-not-exist") is None


def test_history_resave_preserves_order_and_grows(store: PostgresStore) -> None:
    """save_study_session deletes and re-inserts the full history every call (safe here,
    unlike questions: nothing has a foreign key pointing at history_entries.id). Confirms
    that re-save doesn't scramble order or lose earlier entries."""
    store.save_document("doc1", "text")
    store.save_graph(DependencyGraph(doc_id="doc1", concepts=[Concept(id="doc1:a", name="A", summary="s")]))
    q1 = Question(id="doc1:a:q1", concept_id="doc1:a", prompt="q1", expected_answer_notes="a1")
    q2 = Question(id="doc1:a:q2", concept_id="doc1:a", prompt="q2", expected_answer_notes="a2")
    store.save_questions("doc1:a", [q1, q2])

    session = StudySession(id="sess1", doc_id="doc1", status=StudySessionStatus.ACTIVE)
    session.history.append(
        HistoryEntry(
            question=q1,
            answer=Answer(question_id=q1.id, text="first"),
            evaluation=EvaluationResult(correct=False, explanation="e1"),
            diagnosis=None,
        )
    )
    store.save_study_session(session)

    reloaded = store.get_study_session("sess1")
    reloaded.history.append(
        HistoryEntry(
            question=q2,
            answer=Answer(question_id=q2.id, text="second"),
            evaluation=EvaluationResult(correct=True, explanation="e2"),
            diagnosis=None,
        )
    )
    store.save_study_session(reloaded)

    final = store.get_study_session("sess1")
    assert [e.question.id for e in final.history] == [q1.id, q2.id]
    assert [e.answer.text for e in final.history] == ["first", "second"]


def test_delete_document_cascades_to_everything_derived_from_it() -> None:
    """The cascade `delete_document` relies on, encoded rather than assumed.

    `PostgresStore.delete_document` issues a single DELETE and depends on ON DELETE CASCADE
    to remove concepts, questions, study sessions, and history entries. It runs on the
    ingestion failure path (routers/ingestion.py), so if an FK ever loses its `ondelete`,
    failed uploads silently start leaving orphaned documents again — the bug the rollback
    was added to fix.
    """
    store = PostgresStore()
    store.save_document("doomed", "text", "Doomed")
    store.save_document("keeper", "text", "Keeper")
    store.save_graph(
        DependencyGraph(doc_id="doomed", concepts=[Concept(id="doomed:a", name="A", summary="s")])
    )
    store.save_graph(
        DependencyGraph(doc_id="keeper", concepts=[Concept(id="keeper:a", name="A", summary="s")])
    )
    doomed_question = Question(
        id="doomed:a:q1", concept_id="doomed:a", prompt="p", expected_answer_notes="n"
    )
    store.save_questions("doomed:a", [doomed_question])
    store.save_questions(
        "keeper:a",
        [Question(id="keeper:a:q1", concept_id="keeper:a", prompt="p", expected_answer_notes="n")],
    )
    study_session = StudySession(id="doomed_sess", doc_id="doomed", current_concept_id="doomed:a")
    study_session.history.append(
        HistoryEntry(
            question=doomed_question,
            answer=Answer(question_id=doomed_question.id, text="a"),
            evaluation=EvaluationResult(correct=True, explanation="e"),
            diagnosis=None,
        )
    )
    store.save_study_session(study_session)

    store.delete_document("doomed")

    assert store.get_document("doomed") is None
    assert store.get_graph("doomed") is None
    assert store.get_questions("doomed:a") is None
    assert store.get_study_session("doomed_sess") is None
    with get_engine().begin() as conn:
        remaining = conn.execute(
            text("select count(*) from history_entries where study_session_id = 'doomed_sess'")
        ).scalar_one()
    assert remaining == 0, "history entries must go with their session"

    # The neighbouring document is untouched — the cascade is scoped, not a wipe.
    assert store.get_document("keeper") == "text"
    assert store.get_questions("keeper:a") is not None


def test_delete_study_session_cascades_to_history_entries() -> None:
    """Mirrors test_delete_document_cascades_to_everything_derived_from_it, one level down:
    `delete_study_session` relies on `history_entries.study_session_id`'s ON DELETE CASCADE
    rather than deleting history rows itself.
    """
    store = PostgresStore()
    store.save_document("doc", "text", "Doc")
    store.save_graph(
        DependencyGraph(doc_id="doc", concepts=[Concept(id="doc:a", name="A", summary="s")])
    )
    question = Question(id="doc:a:q1", concept_id="doc:a", prompt="p", expected_answer_notes="n")
    store.save_questions("doc:a", [question])

    doomed = StudySession(id="doomed_sess", doc_id="doc", current_concept_id="doc:a")
    doomed.history.append(
        HistoryEntry(
            question=question,
            answer=Answer(question_id=question.id, text="a"),
            evaluation=EvaluationResult(correct=True, explanation="e"),
            diagnosis=None,
        )
    )
    store.save_study_session(doomed)
    kept = StudySession(id="kept_sess", doc_id="doc", current_concept_id="doc:a")
    store.save_study_session(kept)

    store.delete_study_session("doomed_sess")

    assert store.get_study_session("doomed_sess") is None
    with get_engine().begin() as conn:
        remaining = conn.execute(
            text("select count(*) from history_entries where study_session_id = 'doomed_sess'")
        ).scalar_one()
    assert remaining == 0, "history entries must go with their session"

    # The neighbouring session, and the document/questions it shares, are untouched.
    assert store.get_study_session("kept_sess") is not None
    assert store.get_document("doc") == "text"
    assert store.get_questions("doc:a") is not None


def test_delete_study_session_unknown_id_is_a_noop() -> None:
    store = PostgresStore()
    store.save_document("doc", "text", "Doc")
    store.save_study_session(StudySession(id="kept_sess", doc_id="doc"))

    store.delete_study_session("never-existed")

    assert store.get_study_session("kept_sess") is not None


def test_delete_document_is_a_noop_for_an_unknown_id() -> None:
    """Called on the ingestion failure path, where the document may never have been written."""
    store = PostgresStore()
    store.save_document("kept", "text")
    store.delete_document("never-existed")
    assert store.get_document("kept") == "text"


def test_list_unfinished_sessions_joins_title_and_counts_concepts() -> None:
    """The list query's join and correlated count, against a real database.

    Exercises the two cases the count has to get right: a document with several concepts,
    and one with a NULL title (uploaded before titles existed, or without one).
    """
    store = PostgresStore()
    store.save_document("d1", "text one", "Chapter One")
    store.save_document("d2", "text two")  # deliberately untitled
    store.save_graph(
        DependencyGraph(
            doc_id="d1",
            concepts=[
                Concept(id="d1:a", name="A", summary="s"),
                Concept(id="d1:b", name="B", summary="s", depends_on=["d1:a"]),
            ],
        )
    )
    store.save_graph(
        DependencyGraph(doc_id="d2", concepts=[Concept(id="d2:a", name="A", summary="s")])
    )

    store.save_study_session(StudySession(id="s1", doc_id="d1", current_concept_id="d1:b"))
    store.save_study_session(StudySession(id="s2", doc_id="d2"))
    store.save_study_session(
        StudySession(id="s3", doc_id="d1", status=StudySessionStatus.COMPLETED)
    )

    by_id = {r.id: r for r in store.list_unfinished_sessions()}

    assert "s3" not in by_id, "completed sessions must be excluded by the query"
    assert by_id["s1"].title == "Chapter One"
    assert by_id["s1"].total_concepts == 2
    assert by_id["s1"].current_concept_id == "d1:b"
    assert by_id["s2"].title is None
    assert by_id["s2"].total_concepts == 1


def test_save_advances_updated_at_but_preserves_created_at() -> None:
    """`updated_at` is what the list sorts by, so every write must move it.

    `created_at` must survive an update: it's excluded from the upsert's set_ clause
    precisely so a resave doesn't overwrite the original insert time.
    """
    store = PostgresStore()
    store.save_document("d1", "text")
    store.save_graph(
        DependencyGraph(doc_id="d1", concepts=[Concept(id="d1:a", name="A", summary="s")])
    )

    study_session = StudySession(id="s1", doc_id="d1", current_concept_id="d1:a")
    store.save_study_session(study_session)
    first = store.get_study_session("s1")

    study_session.status = StudySessionStatus.DIAGNOSING
    store.save_study_session(study_session)
    second = store.get_study_session("s1")

    assert second.updated_at > first.updated_at
    assert second.created_at == first.created_at
