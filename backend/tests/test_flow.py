"""End-to-end walk through both pipelines against the stub services."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import StudySessionStatus
from app.services import graph_builder
from app.store import get_store

client = TestClient(app)


def _upload_chapter() -> str:
    response = client.post("/api/textbook", json={"text": "A sample chapter about calculus."})
    assert response.status_code == 201
    return response.json()["doc_id"]


def test_upload_builds_graph_and_questions() -> None:
    doc_id = _upload_chapter()

    graph = client.get(f"/api/graph/{doc_id}").json()
    assert graph["doc_id"] == doc_id
    assert len(graph["concepts"]) > 0

    concept_id = graph["concepts"][0]["id"]
    questions = client.get(f"/api/questions/{concept_id}").json()
    assert len(questions) > 0
    assert questions[0]["concept_id"] == concept_id


def test_study_session_loop_advances_or_diagnoses() -> None:
    doc_id = _upload_chapter()

    study_session = client.post("/api/study-session/start", json={"doc_id": doc_id}).json()
    assert study_session["doc_id"] == doc_id
    assert study_session["current_concept_id"] is not None

    # Answer twice; the stub evaluator alternates, so both branches get exercised.
    for _ in range(2):
        concept_id = study_session["current_concept_id"]
        question = client.get(f"/api/questions/{concept_id}").json()[0]
        response = client.post(
            f"/api/study-session/{study_session['id']}/answer",
            json={"question_id": question["id"], "text": "my answer"},
        )
        assert response.status_code == 200
        body = response.json()
        if body["evaluation"]["correct"]:
            assert body["diagnosis"] is None
        else:
            assert body["diagnosis"] is not None
            assert body["next_question"]["id"] == body["diagnosis"]["targeted_question"]["id"]
        study_session = body["study_session"]
        assert len(study_session["history"]) > 0


def _answer_until_diagnosis(doc_id: str) -> tuple[str, dict]:
    """Answer questions until the stub evaluator marks one wrong. Returns (session_id, body)."""
    study_session = client.post("/api/study-session/start", json={"doc_id": doc_id}).json()
    for _ in range(4):  # the stub alternates, so a wrong answer arrives within two
        concept_id = study_session["current_concept_id"]
        question = client.get(f"/api/questions/{concept_id}").json()[0]
        body = client.post(
            f"/api/study-session/{study_session['id']}/answer",
            json={"question_id": question["id"], "text": "my answer"},
        ).json()
        if not body["evaluation"]["correct"]:
            return study_session["id"], body
        study_session = body["study_session"]
    raise AssertionError("stub evaluator never marked an answer incorrect")


def test_diagnostic_question_is_registered_in_both_places() -> None:
    """A generated diagnostic question must land in the store's question index *and* on the
    graph concept it belongs to.

    Two consumers, two homes: `study_session._find_question` resolves an answered question
    through the store index, while `diagnoser.pull_question_from_storage` reads
    `Concept.questions` off the graph. Writing only to the store is the bug this guards —
    the question would resolve when answered, but be invisible to a later diagnosis of the
    same concept, so the diagnoser would regenerate a question it already had.
    """
    doc_id = _upload_chapter()
    _, body = _answer_until_diagnosis(doc_id)

    targeted = body["diagnosis"]["targeted_question"]
    suspect_id = body["diagnosis"]["suspected_gap_concept_id"]

    stored = client.get(f"/api/questions/{suspect_id}").json()
    assert any(q["id"] == targeted["id"] for q in stored), (
        f"targeted question missing from the store's index for {suspect_id}"
    )

    graph = client.get(f"/api/graph/{doc_id}").json()
    suspect = next(c for c in graph["concepts"] if c["id"] == suspect_id)
    assert any(q["id"] == targeted["id"] for q in suspect["questions"]), (
        f"targeted question missing from {suspect_id}'s questions on the graph — a later "
        "diagnosis of this concept would not see it as a reuse candidate"
    )


def test_resuming_a_diagnosing_session_serves_the_diagnostic_question() -> None:
    """The branch that makes `pending_question` worth deriving server-side.

    A diagnosing session is parked on the diagnostic question the diagnoser produced, not on
    its concept's first stored question — that one is what the student just answered wrong.
    Serving it on resume would re-ask it and grade the next answer against the wrong rubric.
    """
    doc_id = _upload_chapter()
    study_session_id, body = _answer_until_diagnosis(doc_id)

    resumed = client.get(f"/api/study-session/{study_session_id}").json()
    assert resumed["status"] == "diagnosing"

    pending = resumed["pending_question"]
    assert pending is not None
    assert pending["id"] == body["diagnosis"]["targeted_question"]["id"], (
        "resuming must serve the diagnostic question the session was left on"
    )

    naive = client.get(f"/api/questions/{resumed['current_concept_id']}").json()[0]
    assert pending["id"] != naive["id"], (
        "the concept's first stored question is a *different* question here — if these were "
        "ever equal this test would pass vacuously and stop guarding the branch"
    )


def test_resuming_an_active_session_serves_its_concept_question() -> None:
    doc_id = _upload_chapter()
    started = client.post("/api/study-session/start", json={"doc_id": doc_id}).json()

    assert started["status"] == "active"
    expected = client.get(f"/api/questions/{started['current_concept_id']}").json()[0]
    assert started["pending_question"]["id"] == expected["id"]

    # And the same answer comes back when the session is reopened rather than started.
    resumed = client.get(f"/api/study-session/{started['id']}").json()
    assert resumed["pending_question"]["id"] == expected["id"]


def test_completed_session_has_no_pending_question() -> None:
    doc_id = _upload_chapter()
    session_id = client.post("/api/study-session/start", json={"doc_id": doc_id}).json()["id"]

    store = get_store()
    study_session = store.get_study_session(session_id)
    study_session.status = StudySessionStatus.COMPLETED
    store.save_study_session(study_session)

    assert client.get(f"/api/study-session/{session_id}").json()["pending_question"] is None


def test_answer_next_question_matches_what_resuming_would_serve() -> None:
    """`submit_answer` and the resume endpoints derive this from one helper — prove it.

    If these ever diverge, a student who answers and a student who closes the tab and comes
    back get different questions from the same session state.
    """
    doc_id = _upload_chapter()
    study_session_id, body = _answer_until_diagnosis(doc_id)

    resumed = client.get(f"/api/study-session/{study_session_id}").json()
    assert body["next_question"]["id"] == resumed["pending_question"]["id"]


def test_graph_404_for_unknown_doc() -> None:
    assert client.get("/api/graph/does-not-exist").status_code == 404


def _list_sessions() -> list[dict]:
    response = client.get("/api/study-session")
    assert response.status_code == 200
    return response.json()


def _find_row(rows: list[dict], session_id: str) -> dict | None:
    return next((r for r in rows if r["id"] == session_id), None)


def test_list_sessions_returns_unfinished_and_drops_completed() -> None:
    """The list is self-cleaning: a session leaves it the moment it completes.

    This is what makes a delete affordance unnecessary — see
    docs/specs/2026-08-29-resume-study-session-design.md §5.
    """
    doc_id = _upload_chapter()
    session_id = client.post("/api/study-session/start", json={"doc_id": doc_id}).json()["id"]

    row = _find_row(_list_sessions(), session_id)
    assert row is not None, "a freshly started session should be resumable"
    assert row["doc_id"] == doc_id
    assert row["total_concepts"] == 5  # the stub graph's concept count

    # Complete it through the store rather than by answering N questions: this test is
    # about the list's filter, not about the loop that eventually sets the status.
    store = get_store()
    study_session = store.get_study_session(session_id)
    assert study_session is not None
    study_session.status = StudySessionStatus.COMPLETED
    store.save_study_session(study_session)

    assert _find_row(_list_sessions(), session_id) is None, (
        "a completed session cannot be continued and must drop out of the list"
    )


def test_list_sessions_sorted_most_recently_updated_first() -> None:
    doc_id = _upload_chapter()
    older = client.post("/api/study-session/start", json={"doc_id": doc_id}).json()["id"]
    newer = client.post("/api/study-session/start", json={"doc_id": doc_id}).json()["id"]

    # Other tests share the store's singleton, so compare positions of just these two.
    ids = [r["id"] for r in _list_sessions()]
    assert ids.index(newer) < ids.index(older)


def test_list_session_progress_is_topological_position() -> None:
    """`completed_concepts` is the position of current_concept_id in topological order.

    Not an answer tally: a diagnosis appends history without advancing a concept, so the
    two diverge exactly when a student is struggling.
    """
    doc_id = _upload_chapter()
    session_id = client.post("/api/study-session/start", json={"doc_id": doc_id}).json()["id"]

    # A new session sits on the first concept in topological order — zero completed.
    assert _find_row(_list_sessions(), session_id)["completed_concepts"] == 0

    store = get_store()
    study_session = store.get_study_session(session_id)
    # "derivatives" is index 2 of the stub graph's order (limits, continuity, derivatives, …).
    study_session.current_concept_id = f"{doc_id}:derivatives"
    store.save_study_session(study_session)
    assert _find_row(_list_sessions(), session_id)["completed_concepts"] == 2

    # A session with no current concept reports 0 rather than raising.
    study_session.current_concept_id = None
    store.save_study_session(study_session)
    assert _find_row(_list_sessions(), session_id)["completed_concepts"] == 0


def test_uploaded_title_reaches_the_session_list() -> None:
    """`title` was accepted by the upload endpoint and silently dropped before this feature."""
    doc_id = client.post(
        "/api/textbook",
        json={"text": "A sample chapter about calculus.", "title": "Calculus I"},
    ).json()["doc_id"]
    session_id = client.post("/api/study-session/start", json={"doc_id": doc_id}).json()["id"]

    assert _find_row(_list_sessions(), session_id)["title"] == "Calculus I"


def test_untitled_upload_reports_null_title() -> None:
    """The API returns null rather than synthesizing a label; the client renders a snippet."""
    doc_id = _upload_chapter()  # no title supplied
    session_id = client.post("/api/study-session/start", json={"doc_id": doc_id}).json()["id"]

    assert _find_row(_list_sessions(), session_id)["title"] is None


def test_failed_ingestion_leaves_no_orphan_document(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mid-pipeline failure must roll the document back rather than strand it.

    `upload_textbook` has to save the document before building the graph (concepts
    reference it by FK), so a failing LLM call would otherwise leave a document row with
    no concepts — invisible to the app, permanent in the database. The spy captures the
    generated doc_id, which is otherwise unobservable when the request fails.
    """
    store = get_store()

    def _failing_build_graph(doc_id: str, text: str):
        raise RuntimeError("simulated LLM failure")

    monkeypatch.setattr(graph_builder, "build_graph", _failing_build_graph)

    deleted: list[str] = []
    real_delete = store.delete_document

    def _spy_delete(doc_id: str) -> None:
        deleted.append(doc_id)
        real_delete(doc_id)

    monkeypatch.setattr(store, "delete_document", _spy_delete)

    with pytest.raises(RuntimeError, match="simulated LLM failure"):
        client.post("/api/textbook", json={"text": "A sample chapter about calculus."})

    assert deleted, "failed ingestion did not attempt to clean up its document"
    assert store.get_document(deleted[0]) is None, "document survived the rollback"
