"""Review mode: the human-in-the-loop pause between graph extraction and question
generation (docs/specs/2026-09-12-human-in-the-loop).

HTTP-level against the stubbed services, same as test_flow.py — the LLM calls are fake,
the pipeline branching and every store write are real. The stub graph is the 5-concept
calculus one from conftest.py.

Review is per-upload (`"review": true`), so these tests need no fixture and no settings
patching: whether a chapter is editable is a property of that chapter, not of the process.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import DependencyGraph
from app.services import evidence_finder, question_generator

client = TestClient(app)


# Names no concept from the stub graph, so every evidence scan against it comes back
# empty — the default these tests inherit unless they ask for CHAPTER_WITH_EVIDENCE.
BLAND_CHAPTER = "A sample chapter about calculus."

# Does name them, so the stubbed scan (tests/conftest.py, sentence mentions the concept by
# name) finds something. Sentence boundaries matter: the stub quotes whole sentences, and
# the route re-checks each one is verbatim in this text.
CHAPTER_WITH_EVIDENCE = (
    "Limits describe the value a function approaches as its input approaches a point. "
    "Continuity is defined in terms of Limits: a function is continuous at a point when "
    "its limit there equals its value. Derivatives are then built on Limits as well."
)


def _upload(review: bool = True, text: str = BLAND_CHAPTER) -> dict:
    response = client.post("/api/textbook", json={"text": text, "review": review})
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


def test_a_hand_added_prerequisite_carries_no_quote_when_the_chapter_has_none() -> None:
    """A hand-drawn edge is scanned for a justifying sentence, but this chapter links no two
    concepts, so the entry stays empty — exactly the behavior that predates the scan. An
    empty entry is what question_generator.source_passages() already skips, so the edge
    contributes no prerequisite_link passage rather than a fabricated one."""
    doc_id = _upload()["doc_id"]
    chain_rule = f"{doc_id}:chain-rule"
    continuity = f"{doc_id}:continuity"

    client.post(f"/api/graph/{doc_id}/concepts/{chain_rule}/prereqs", json={"prereq_id": continuity})

    graph_response = _graph(doc_id)
    concept = next(c for c in graph_response["concepts"] if c["id"] == chain_rule)
    assert concept["evidence"][continuity] == ""

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


# --- evidence (docs/specs/2026-09-13-concept-evidence-generation.md) ---
#
# The scan itself is stubbed (tests/conftest.py: a sentence is evidence for a concept when
# it names that concept), so what these cover is the wiring around it — that a proposal is
# only ever proposed, that the verbatim invariant holds at the write, and that every way of
# finding nothing lands on the pre-existing behavior rather than on an error.


def test_evidence_is_proposed_and_not_applied() -> None:
    """The heart of §6. A human-in-the-loop feature that silently overwrote the summary
    someone just typed with model output would be inverting its own point, so the endpoint
    returns a proposal and the concept is untouched until the reviewer PATCHes it."""
    doc_id = _upload(text=CHAPTER_WITH_EVIDENCE)["doc_id"]
    limits = f"{doc_id}:limits"
    before = _concept(doc_id, limits)

    response = client.post(f"/api/graph/{doc_id}/concepts/{limits}/evidence")
    assert response.status_code == 200
    proposal = response.json()

    assert proposal["found"] is True
    assert proposal["quotes"]
    assert proposal["summary"]
    assert _concept(doc_id, limits) == before, "the scan must not write anything"


def test_accepting_a_proposal_stores_its_quotes() -> None:
    doc_id = _upload(text=CHAPTER_WITH_EVIDENCE)["doc_id"]
    limits = f"{doc_id}:limits"
    proposal = client.post(f"/api/graph/{doc_id}/concepts/{limits}/evidence").json()

    response = client.patch(
        f"/api/graph/{doc_id}/concepts/{limits}",
        json={"summary": proposal["summary"], "source_quotes": proposal["quotes"]},
    )
    assert response.status_code == 200
    assert response.json()["source_quotes"] == proposal["quotes"]
    assert _concept(doc_id, limits)["source_quotes"] == proposal["quotes"]


def test_accepting_part_of_a_proposal_is_expressible() -> None:
    """`source_quotes` replaces the whole list rather than appending, so unticking a quote
    in the review UI is a plain PATCH of what's left."""
    doc_id = _upload(text=CHAPTER_WITH_EVIDENCE)["doc_id"]
    limits = f"{doc_id}:limits"
    quotes = client.post(f"/api/graph/{doc_id}/concepts/{limits}/evidence").json()["quotes"]
    assert len(quotes) > 1

    client.patch(f"/api/graph/{doc_id}/concepts/{limits}", json={"source_quotes": quotes})
    client.patch(f"/api/graph/{doc_id}/concepts/{limits}", json={"source_quotes": quotes[:1]})

    assert _concept(doc_id, limits)["source_quotes"] == quotes[:1]


def test_an_edit_that_omits_source_quotes_leaves_them_alone() -> None:
    """Every pre-existing edit path sends only name/summary; none of them may wipe the
    evidence a reviewer already accepted."""
    doc_id = _upload(text=CHAPTER_WITH_EVIDENCE)["doc_id"]
    limits = f"{doc_id}:limits"
    quotes = client.post(f"/api/graph/{doc_id}/concepts/{limits}/evidence").json()["quotes"]
    client.patch(f"/api/graph/{doc_id}/concepts/{limits}", json={"source_quotes": quotes})

    client.patch(f"/api/graph/{doc_id}/concepts/{limits}", json={"name": "Limits (renamed)"})

    assert _concept(doc_id, limits)["source_quotes"] == quotes


def test_a_quote_that_is_not_in_the_chapter_is_rejected() -> None:
    """`evidence_finder` discards non-verbatim quotes, but it isn't the only way into the
    field — a client can PATCH anything, and a reviewer "fixing" a typo in a proposed quote
    turns provenance back into prose. The invariant is enforced at the write."""
    doc_id = _upload(text=CHAPTER_WITH_EVIDENCE)["doc_id"]
    limits = f"{doc_id}:limits"

    response = client.patch(
        f"/api/graph/{doc_id}/concepts/{limits}",
        json={"source_quotes": ["Limits are, broadly speaking, about approaching things."]},
    )
    assert response.status_code == 422
    assert "verbatim" in response.json()["detail"]
    assert _concept(doc_id, limits)["source_quotes"] == []


def test_a_rewrapped_quote_is_accepted() -> None:
    """The one difference the verbatim check forgives: a model (or a reviewer copying out
    of a rendered page) joins a line break with a space."""
    doc_id = _upload(text="Limits describe\na value a function approaches.")["doc_id"]
    limits = f"{doc_id}:limits"

    response = client.patch(
        f"/api/graph/{doc_id}/concepts/{limits}",
        json={"source_quotes": ["Limits describe a value a function approaches."]},
    )
    assert response.status_code == 200


def test_a_chapter_with_nothing_to_say_reports_not_found() -> None:
    """The user-visible half of §2: "found nothing" is a legitimate outcome — a reviewer may
    be adding an idea the chapter assumes rather than teaches — so the endpoint reports it
    rather than manufacturing quotes to fill the schema, and the concept is left standing
    with the reviewer's own summary."""
    doc_id = _upload()["doc_id"]  # BLAND_CHAPTER names no concept
    limits = f"{doc_id}:limits"
    before = _concept(doc_id, limits)

    proposal = client.post(f"/api/graph/{doc_id}/concepts/{limits}/evidence").json()

    assert proposal == {"found": False, "summary": "", "quotes": [], "dropped": 0}
    assert _concept(doc_id, limits) == before


def test_a_failing_scan_leaves_the_concept_intact() -> None:
    """The reason this is a separate request from `add_concept`: the concept is already
    saved by the time the scan runs, so an LLM failure costs the reviewer nothing."""
    doc_id = _upload(text=CHAPTER_WITH_EVIDENCE)["doc_id"]
    limits = f"{doc_id}:limits"
    before = _concept(doc_id, limits)

    def _boom(chapter_text: str, concept: object) -> None:
        raise RuntimeError("the API is down")

    with patch.object(evidence_finder, "find_evidence", _boom):
        with pytest.raises(RuntimeError):
            client.post(f"/api/graph/{doc_id}/concepts/{limits}/evidence")

    assert _concept(doc_id, limits) == before


def test_evidence_is_locked_behind_draft_status_like_every_other_edit() -> None:
    doc_id = _upload(text=CHAPTER_WITH_EVIDENCE)["doc_id"]
    limits = f"{doc_id}:limits"
    assert client.post(f"/api/textbook/{doc_id}/finalize").status_code == 200

    assert client.post(f"/api/graph/{doc_id}/concepts/{limits}/evidence").status_code == 409
    assert client.post(f"/api/graph/{doc_id}/concepts/{doc_id}:nope/evidence").status_code == 409


def test_scanning_an_unknown_concept_404s() -> None:
    doc_id = _upload(text=CHAPTER_WITH_EVIDENCE)["doc_id"]

    assert client.post(f"/api/graph/{doc_id}/concepts/{doc_id}:nope/evidence").status_code == 404
    assert client.post("/api/graph/ghost/concepts/ghost:x/evidence").status_code == 404


def test_a_hand_added_prerequisite_picks_up_a_quote_when_the_chapter_links_the_two() -> None:
    """The one thing that makes a hand-drawn edge indistinguishable from an extracted one.
    This chapter has a sentence naming both concepts, so the edge stores it verbatim and
    source_passages() sends it on as a prerequisite_link passage — the sharper anchor for a
    conceptual_distinction question than either concept's summary."""
    doc_id = _upload(text=CHAPTER_WITH_EVIDENCE)["doc_id"]
    continuity, limits = f"{doc_id}:continuity", f"{doc_id}:limits"
    # The stub graph already wires this edge; drop it so re-adding it goes through the
    # hand-added path rather than through graph_builder's.
    assert client.delete(
        f"/api/graph/{doc_id}/concepts/{continuity}/prereqs/{limits}"
    ).status_code == 204

    assert client.post(
        f"/api/graph/{doc_id}/concepts/{continuity}/prereqs", json={"prereq_id": limits}
    ).status_code == 204

    quote = _concept(doc_id, continuity)["evidence"][limits]
    assert "Continuity is defined in terms of Limits" in quote
    assert quote in CHAPTER_WITH_EVIDENCE, "an edge quote is chapter text, not a paraphrase"

    parsed = DependencyGraph.model_validate(_graph(doc_id))
    by_id = {c.id: c for c in parsed.concepts}
    roles = [
        p["role"]
        for p in question_generator.source_passages(by_id[continuity], by_id, parsed)
        if p["concept_name"] == "Limits"
    ]
    assert roles == ["prerequisite", "prerequisite_link"]


def test_an_edge_scan_that_fails_still_stores_the_edge() -> None:
    """Silent and non-blocking: failing the edit would lose the reviewer's structural work
    over a missing quote, so a broken scan lands on exactly the pre-scan behavior."""
    doc_id = _upload(text=CHAPTER_WITH_EVIDENCE)["doc_id"]
    chain_rule, continuity = f"{doc_id}:chain-rule", f"{doc_id}:continuity"

    def _boom(chapter_text: str, concept: object, prereq: object) -> None:
        raise RuntimeError("the API is down")

    with patch.object(evidence_finder, "find_edge_evidence", _boom):
        response = client.post(
            f"/api/graph/{doc_id}/concepts/{chain_rule}/prereqs", json={"prereq_id": continuity}
        )

    assert response.status_code == 204
    concept = _concept(doc_id, chain_rule)
    assert continuity in concept["depends_on"]
    assert concept["evidence"][continuity] == ""
