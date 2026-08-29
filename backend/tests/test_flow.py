"""End-to-end walk through both pipelines against the stub services."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
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


def test_graph_404_for_unknown_doc() -> None:
    assert client.get("/api/graph/does-not-exist").status_code == 404


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
