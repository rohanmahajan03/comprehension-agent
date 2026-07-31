"""End-to-end walk through both pipelines against the stub services."""

from fastapi.testclient import TestClient

from app.main import app

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


def test_graph_404_for_unknown_doc() -> None:
    assert client.get("/api/graph/does-not-exist").status_code == 404
