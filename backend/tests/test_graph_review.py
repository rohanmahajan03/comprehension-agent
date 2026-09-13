"""Review mode: the human-in-the-loop pause between graph extraction and question
generation (docs/specs/2026-09-12-human-in-the-loop).

HTTP-level against the stubbed services, same as test_flow.py — the LLM calls are fake,
the pipeline branching and every store write are real. The stub graph is the 5-concept
calculus one from conftest.py.

Review is per-upload (`"review": true`), so these tests need no fixture and no settings
patching: whether a chapter is editable is a property of that chapter, not of the process.
"""

from fastapi.testclient import TestClient

from app.main import app
from app.services import question_generator

client = TestClient(app)


def _upload(review: bool = True) -> dict:
    response = client.post(
        "/api/textbook", json={"text": "A sample chapter about calculus.", "review": review}
    )
    assert response.status_code == 201
    return response.json()


def _graph(doc_id: str) -> dict:
    response = client.get(f"/api/graph/{doc_id}")
    assert response.status_code == 200
    return response.json()


def _concept(doc_id: str, concept_id: str) -> dict:
    return next(c for c in _graph(doc_id)["concepts"] if c["id"] == concept_id)


# --- not asking for review (the default) ---


def test_upload_without_review_finalizes_immediately() -> None:
    """The regression guard for everything below: leave the box unticked and an upload is
    exactly what it was before review mode existed — questions generated, chapter listed,
    session startable, all from the one request."""
    body = _upload(review=False)
    doc_id = body["doc_id"]

    assert body["status"] == "finalized"
    concept_id = _graph(doc_id)["concepts"][0]["id"]
    assert len(client.get(f"/api/questions/{concept_id}").json()) > 0
    assert any(row["id"] == doc_id for row in client.get("/api/textbook").json())
    assert client.post("/api/study-session/start", json={"doc_id": doc_id}).status_code == 201


def test_review_defaults_to_off_when_the_field_is_omitted() -> None:
    """An older client that never heard of `review` must keep getting the old pipeline."""
    response = client.post("/api/textbook", json={"text": "A sample chapter about calculus."})

    assert response.status_code == 201
    assert response.json()["status"] == "finalized"


def test_a_chapter_uploaded_without_review_cannot_be_edited() -> None:
    """Draft status is the only gate, so a chapter that never entered review is refused on
    exactly the same terms as one whose review was already approved (409, not 404) — it's
    finalized either way. The message names the fix, since the likely cause is a forgotten
    checkbox rather than a client bug."""
    doc_id = _upload(review=False)["doc_id"]
    concept_id = _graph(doc_id)["concepts"][0]["id"]

    refused = client.patch(
        f"/api/graph/{doc_id}/concepts/{concept_id}", json={"name": "Renamed"}
    )
    assert refused.status_code == 409
    assert "review" in refused.json()["detail"]

    assert client.post(
        f"/api/graph/{doc_id}/concepts",
        json={"slug": "new_one", "name": "New", "summary": "..."},
    ).status_code == 409
    assert client.delete(f"/api/graph/{doc_id}/concepts/{concept_id}").status_code == 409
    assert client.post(
        f"/api/graph/{doc_id}/concepts/{concept_id}/prereqs", json={"prereq_id": concept_id}
    ).status_code == 409
    assert client.post(f"/api/textbook/{doc_id}/finalize").status_code == 409


# --- the draft state ---


def test_upload_with_review_stops_before_questions() -> None:
    """A draft has its graph but nothing downstream of it: no questions, not offered as a
    chapter to study, and not startable as a session."""
    body = _upload()
    doc_id = body["doc_id"]

    assert body["status"] == "draft"
    assert len(_graph(doc_id)["concepts"]) == 5

    concept_id = _graph(doc_id)["concepts"][0]["id"]
    assert client.get(f"/api/questions/{concept_id}").json() == []
    assert not any(row["id"] == doc_id for row in client.get("/api/textbook").json()), (
        "a draft would 409 the moment a student started it, so it must not be listed"
    )

    started = client.post("/api/study-session/start", json={"doc_id": doc_id})
    assert started.status_code == 409
    assert "review" in started.json()["detail"]


def test_status_endpoint_reports_the_lifecycle() -> None:
    doc_id = _upload()["doc_id"]

    assert client.get(f"/api/textbook/{doc_id}/status").json()["status"] == "draft"
    assert client.post(f"/api/textbook/{doc_id}/finalize").status_code == 200
    assert client.get(f"/api/textbook/{doc_id}/status").json()["status"] == "finalized"
    assert client.get("/api/textbook/nope/status").status_code == 404


# --- editing a draft ---


def test_edit_concept_rewrites_name_and_summary() -> None:
    doc_id = _upload()["doc_id"]
    concept_id = f"{doc_id}:limits"

    response = client.patch(
        f"/api/graph/{doc_id}/concepts/{concept_id}",
        json={"name": "Limits (revised)", "summary": "What a function approaches."},
    )
    assert response.status_code == 200

    stored = _concept(doc_id, concept_id)
    assert stored["name"] == "Limits (revised)"
    assert stored["summary"] == "What a function approaches."


def test_add_concept_joins_the_graph() -> None:
    doc_id = _upload()["doc_id"]

    response = client.post(
        f"/api/graph/{doc_id}/concepts",
        json={"slug": "epsilon_delta", "name": "Epsilon-delta", "summary": "The formal definition."},
    )
    assert response.status_code == 201
    assert response.json()["id"] == f"{doc_id}:epsilon_delta"

    assert any(c["id"] == f"{doc_id}:epsilon_delta" for c in _graph(doc_id)["concepts"])
    # Re-adding the same slug is a conflict, not a silent overwrite of the reviewer's work.
    assert client.post(
        f"/api/graph/{doc_id}/concepts",
        json={"slug": "epsilon_delta", "name": "Dup", "summary": "..."},
    ).status_code == 409


def test_delete_concept_strips_it_from_every_dependent() -> None:
    """The cascade that makes deletion more than a row removal: `continuity` and
    `derivatives` both depend on `limits`, and a graph still pointing at a deleted id would
    break topological_order and hand question_generator a dangling prerequisite."""
    doc_id = _upload()["doc_id"]
    limits = f"{doc_id}:limits"
    assert limits in _concept(doc_id, f"{doc_id}:derivatives")["depends_on"]

    assert client.delete(f"/api/graph/{doc_id}/concepts/{limits}").status_code == 204

    graph = _graph(doc_id)
    assert all(c["id"] != limits for c in graph["concepts"])
    for concept in graph["concepts"]:
        assert limits not in concept["depends_on"]
        assert limits not in concept["evidence"]


def test_add_and_remove_a_prerequisite() -> None:
    doc_id = _upload()["doc_id"]
    chain_rule = f"{doc_id}:chain-rule"
    continuity = f"{doc_id}:continuity"

    assert client.post(
        f"/api/graph/{doc_id}/concepts/{chain_rule}/prereqs", json={"prereq_id": continuity}
    ).status_code == 204
    assert continuity in _concept(doc_id, chain_rule)["depends_on"]

    assert client.delete(
        f"/api/graph/{doc_id}/concepts/{chain_rule}/prereqs/{continuity}"
    ).status_code == 204
    assert continuity not in _concept(doc_id, chain_rule)["depends_on"]


def test_a_hand_added_prerequisite_is_rejected_if_it_would_cycle() -> None:
    """The DAG invariant topological_order depends on. `derivatives` already depends on
    `limits`, so making `limits` depend on `derivatives` closes a loop — the same check
    build_graph applies to LLM-extracted edges, via the shared creates_cycle()."""
    doc_id = _upload()["doc_id"]

    response = client.post(
        f"/api/graph/{doc_id}/concepts/{doc_id}:limits/prereqs",
        json={"prereq_id": f"{doc_id}:derivatives"},
    )
    assert response.status_code == 422
    assert "cycle" in response.json()["detail"]
    assert _concept(doc_id, f"{doc_id}:limits")["depends_on"] == []

    # And the degenerate case the cycle walk would otherwise report as "already depends".
    assert client.post(
        f"/api/graph/{doc_id}/concepts/{doc_id}:limits/prereqs",
        json={"prereq_id": f"{doc_id}:limits"},
    ).status_code == 422


def test_hand_added_prerequisites_carry_no_evidence_quote() -> None:
    """There's no source sentence to quote for an edge a human drew, and an empty entry is
    what question_generator.source_passages() already skips — so the edge contributes no
    prerequisite_link passage rather than a fabricated one."""
    doc_id = _upload()["doc_id"]
    chain_rule = f"{doc_id}:chain-rule"
    continuity = f"{doc_id}:continuity"

    client.post(f"/api/graph/{doc_id}/concepts/{chain_rule}/prereqs", json={"prereq_id": continuity})

    graph_response = _graph(doc_id)
    concept = next(c for c in graph_response["concepts"] if c["id"] == chain_rule)
    assert concept["evidence"][continuity] == ""

    from app.models import DependencyGraph

    parsed = DependencyGraph.model_validate(graph_response)
    by_id = {c.id: c for c in parsed.concepts}
    roles = [
        p["role"]
        for p in question_generator.source_passages(by_id[chain_rule], by_id, parsed)
        if p["concept_name"] == "Continuity"
    ]
    assert roles == ["prerequisite"], "an empty evidence quote must not reach the generator"


# --- finalizing ---


def test_finalize_generates_questions_and_opens_the_chapter() -> None:
    doc_id = _upload()["doc_id"]
    client.patch(
        f"/api/graph/{doc_id}/concepts/{doc_id}:limits", json={"name": "Limits, reviewed"}
    )

    response = client.post(f"/api/textbook/{doc_id}/finalize")
    assert response.status_code == 200
    assert response.json() == {"doc_id": doc_id, "status": "finalized"}

    # Questions now exist for every concept, and they were written against the edited graph.
    for concept in _graph(doc_id)["concepts"]:
        assert len(client.get(f"/api/questions/{concept['id']}").json()) > 0
    limits_questions = client.get(f"/api/questions/{doc_id}:limits").json()
    assert "Limits, reviewed" in limits_questions[0]["prompt"]

    assert any(row["id"] == doc_id for row in client.get("/api/textbook").json())
    assert client.post("/api/study-session/start", json={"doc_id": doc_id}).status_code == 201


def test_a_finalized_graph_is_locked() -> None:
    """Editing stops at finalize even with the mode still on: questions, study sessions and
    history entries all reference concepts by id from here on (design doc §8)."""
    doc_id = _upload()["doc_id"]
    assert client.post(f"/api/textbook/{doc_id}/finalize").status_code == 200

    response = client.patch(
        f"/api/graph/{doc_id}/concepts/{doc_id}:limits", json={"name": "Too late"}
    )
    assert response.status_code == 409
    assert client.delete(f"/api/graph/{doc_id}/concepts/{doc_id}:limits").status_code == 409
    assert client.post(f"/api/textbook/{doc_id}/finalize").status_code == 409


def test_finalizing_an_emptied_graph_is_rejected() -> None:
    """Reachable by deleting every concept: a chapter with no concepts is one whose every
    downstream endpoint 404s, the same reason upload rejects a zero-concept extraction."""
    doc_id = _upload()["doc_id"]
    for concept in _graph(doc_id)["concepts"]:
        assert client.delete(f"/api/graph/{doc_id}/concepts/{concept['id']}").status_code == 204

    response = client.post(f"/api/textbook/{doc_id}/finalize")
    assert response.status_code == 422
    assert client.get(f"/api/textbook/{doc_id}/status").json()["status"] == "draft"


def test_editing_an_unknown_concept_or_document_404s() -> None:
    doc_id = _upload()["doc_id"]

    assert client.patch(
        f"/api/graph/{doc_id}/concepts/{doc_id}:nope", json={"name": "x"}
    ).status_code == 404
    assert client.delete(f"/api/graph/{doc_id}/concepts/{doc_id}:nope").status_code == 404
    assert client.post(
        f"/api/graph/{doc_id}/concepts/{doc_id}:limits/prereqs", json={"prereq_id": "ghost"}
    ).status_code == 404
    assert client.delete(
        f"/api/graph/{doc_id}/concepts/{doc_id}:limits/prereqs/{doc_id}:continuity"
    ).status_code == 404, "removing a prerequisite that isn't there is a 404, not a silent no-op"
    assert client.post(
        "/api/graph/ghost-doc/concepts", json={"slug": "x", "name": "X", "summary": "..."}
    ).status_code == 404
