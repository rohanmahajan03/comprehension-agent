"""The manual answer-override endpoint, driven over HTTP.

Design doc: docs/specs/2026-09-18-manual-answer-override-design.md. Free and stub-backed —
`evaluator_script` (added for the study-loop remediation) is what makes "grade this one
wrong" reachable on demand, since the default stub alternates.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import get_store

client = TestClient(app)


def _upload_chapter() -> str:
    response = client.post("/api/textbook", json={"text": "A sample chapter about calculus."})
    assert response.status_code == 201
    return response.json()["doc_id"]


def _start(doc_id: str) -> dict:
    return client.post("/api/study-session/start", json={"doc_id": doc_id}).json()


def _answer(session_id: str, question_id: str, text: str = "my answer") -> dict:
    response = client.post(
        f"/api/study-session/{session_id}/answer",
        json={"question_id": question_id, "text": text},
    )
    assert response.status_code == 200
    return response.json()


def _override(session_id: str, question_id: str, note: str | None = None):
    return client.post(
        f"/api/study-session/{session_id}/override",
        json={"question_id": question_id, "note": note},
    )


def _overrides_for(session_id: str) -> list:
    return [o for o in get_store().list_answer_overrides() if o.study_session_id == session_id]


@pytest.fixture
def wrong_first_answer(evaluator_script: list[bool]) -> list[bool]:
    """Grade the first answer wrong, then alternate-free: every later call is correct.

    Long enough that a test answering a few more questions doesn't exhaust the script; the
    stub raises loudly rather than silently reverting to alternation if one ever does.
    """
    evaluator_script.extend([False] + [True] * 12)
    return evaluator_script


def test_override_after_a_wrong_answer_advances_and_records_a_snapshot(
    wrong_first_answer: list[bool],
) -> None:
    """The happy path, and the only test that checks every snapshot field.

    The row has to stand on its own — no FK reaches back to the question or the session
    (design doc §5) — so what it copies at write time is all a later reviewer will ever have.
    """
    doc_id = _upload_chapter()
    session = _start(doc_id)
    question = client.get(f"/api/questions/{session['current_concept_id']}").json()[0]

    result = _answer(session["id"], question["id"], "an answer the grader disliked")
    assert result["evaluation"]["correct"] is False

    response = _override(session["id"], question["id"], note="the rubric wanted an example")
    assert response.status_code == 200
    detail = response.json()

    # Advanced, exactly as a correct answer would have.
    assert detail["status"] == "active"
    assert detail["current_concept_id"] != session["current_concept_id"]
    assert detail["pending_question"]["concept_id"] == detail["current_concept_id"]

    overrides = _overrides_for(session["id"])
    assert len(overrides) == 1
    override = overrides[0]
    assert override.history_seq == 0
    assert override.question_id == question["id"]
    assert override.concept_id == question["concept_id"]
    assert override.doc_id == doc_id
    assert override.question_prompt == question["prompt"]
    assert override.expected_answer_notes == question["expected_answer_notes"]
    assert override.student_answer == "an answer the grader disliked"
    assert override.evaluator_explanation == result["evaluation"]["explanation"]
    assert override.student_note == "the rubric wanted an example"


def test_override_of_a_diagnostic_returns_to_the_concept_that_failed(
    evaluator_script: list[bool],
) -> None:
    """The case this feature waited on the study-loop remediation for.

    Overriding a diagnostic probe is a claim about the *prerequisite* question, not about the
    concept that failed — so the session goes back to that concept rather than past it. Before
    docs/specs/2026-09-17-study-loop-remediation-design.md §1a was fixed, the correct-branch
    advanced unconditionally and this would have marked the failed concept complete.
    """
    doc_id = _upload_chapter()
    # Pass the first concept so the session lands on one that *has* a prerequisite: the stub
    # graph's root ("limits") has none, and the stub diagnoser then names the concept itself,
    # which would make this test pass without any prerequisite probe existing.
    evaluator_script.extend([True, False, False] + [True] * 8)
    session = _start(doc_id)
    root_question = client.get(f"/api/questions/{session['current_concept_id']}").json()[0]
    _answer(session["id"], root_question["id"])

    failed_concept = client.get(f"/api/study-session/{session['id']}").json()[
        "current_concept_id"
    ]
    question = client.get(f"/api/questions/{failed_concept}").json()[0]

    result = _answer(session["id"], question["id"])
    diagnostic = result["diagnosis"]["targeted_question"]
    assert result["study_session"]["status"] == "diagnosing"

    # The diagnostic is graded wrong too, so there is a diagnostic grade to dispute.
    _answer(session["id"], diagnostic["id"])

    detail = _override(session["id"], diagnostic["id"]).json()

    assert detail["status"] == "active"
    assert detail["current_concept_id"] == failed_concept, (
        "overriding a prerequisite probe must hand the concept that failed back, not skip it"
    )
    assert detail["pending_question"]["id"] == question["id"]

    override = _overrides_for(session["id"])[0]
    assert override.question_id == diagnostic["id"]
    assert override.concept_id == diagnostic["concept_id"]
    assert override.concept_id != failed_concept, (
        "the probe must be on a real prerequisite — otherwise this test would pass "
        "without exercising the diagnostic branch at all"
    )


def test_override_leaves_the_history_entry_exactly_as_graded(
    wrong_first_answer: list[bool],
) -> None:
    """The override is a second record asserting the first is wrong, never an edit of it.

    What the evaluator said is the disputed artifact (design doc §4): rewriting it would
    destroy the evidence and make a session replay show agreement where there was none.
    """
    doc_id = _upload_chapter()
    session = _start(doc_id)
    question = client.get(f"/api/questions/{session['current_concept_id']}").json()[0]
    result = _answer(session["id"], question["id"])

    _override(session["id"], question["id"])

    entry = client.get(f"/api/study-session/{session['id']}").json()["history"][0]
    assert entry["evaluation"]["correct"] is False
    assert entry["evaluation"]["explanation"] == result["evaluation"]["explanation"]


def test_second_override_of_the_same_answer_is_a_no_op(
    wrong_first_answer: list[bool],
) -> None:
    """A double-submitted click must not advance the session twice.

    The override appends nothing to history, so the entry it targets is still the newest one
    on the second POST and every validation above passes again. The unique constraint on
    (study_session_id, history_seq), surfaced as `save_answer_override`'s bool, is the only
    thing standing between a double click and a skipped concept (design doc §6).
    """
    doc_id = _upload_chapter()
    session = _start(doc_id)
    question = client.get(f"/api/questions/{session['current_concept_id']}").json()[0]
    _answer(session["id"], question["id"])

    first = _override(session["id"], question["id"], note="original").json()
    second = _override(session["id"], question["id"], note="ignored").json()

    assert second["current_concept_id"] == first["current_concept_id"]
    assert second["status"] == first["status"]

    overrides = _overrides_for(session["id"])
    assert len(overrides) == 1
    assert overrides[0].student_note == "original", "a repeat POST must not rewrite the note"


def test_override_of_a_correct_answer_is_rejected(evaluator_script: list[bool]) -> None:
    doc_id = _upload_chapter()
    evaluator_script.extend([True] * 6)
    session = _start(doc_id)
    question = client.get(f"/api/questions/{session['current_concept_id']}").json()[0]
    _answer(session["id"], question["id"])

    response = _override(session["id"], question["id"])
    assert response.status_code == 409
    assert "already graded correct" in response.json()["detail"]
    assert _overrides_for(session["id"]) == []


def test_override_of_an_older_answer_is_rejected(evaluator_script: list[bool]) -> None:
    """Only the newest answer is overridable (design doc §7).

    The transition branches on the session's *current* status, so applying it to an older
    entry would advance the session from wherever it is now rather than from where that
    answer left it.
    """
    doc_id = _upload_chapter()
    evaluator_script.extend([False, True, True, True])
    session = _start(doc_id)
    first_question = client.get(f"/api/questions/{session['current_concept_id']}").json()[0]

    result = _answer(session["id"], first_question["id"])
    # Answer the diagnostic correctly, so the first (wrong) entry is no longer the newest.
    _answer(session["id"], result["diagnosis"]["targeted_question"]["id"])

    response = _override(session["id"], first_question["id"])
    assert response.status_code == 409
    assert "most recent" in response.json()["detail"]
    assert _overrides_for(session["id"]) == []


def test_override_on_unknown_session_404s() -> None:
    assert _override("does-not-exist", "whatever:q1").status_code == 404


def test_override_before_any_answer_404s() -> None:
    doc_id = _upload_chapter()
    session = _start(doc_id)
    question = client.get(f"/api/questions/{session['current_concept_id']}").json()[0]

    response = _override(session["id"], question["id"])
    assert response.status_code == 404
    assert "no answer to override" in response.json()["detail"]


def test_omitted_note_is_stored_as_null(wrong_first_answer: list[bool]) -> None:
    """The note is optional by design — requiring prose would suppress the disagreements."""
    doc_id = _upload_chapter()
    session = _start(doc_id)
    question = client.get(f"/api/questions/{session['current_concept_id']}").json()[0]
    _answer(session["id"], question["id"])

    assert _override(session["id"], question["id"]).status_code == 200
    assert _overrides_for(session["id"])[0].student_note is None


def _fail_until_cap(session_id: str, concept_id: str) -> dict:
    """Burn a concept's whole attempt budget, returning the response that tripped the cap.

    Each failed attempt parks the session on a diagnostic, so the concept's own question is
    only reachable again by answering that probe correctly — which is why the script below
    alternates rather than simply repeating False.
    """
    question = client.get(f"/api/questions/{concept_id}").json()[0]
    result = _answer(session_id, question["id"])
    while result.get("diagnosis") is not None:
        _answer(session_id, result["diagnosis"]["targeted_question"]["id"])
        result = _answer(session_id, question["id"])
    return result


def test_override_after_the_attempt_cap_does_not_advance_a_second_time(
    evaluator_script: list[bool],
) -> None:
    """The cap already moved the session on, so the override must not move it again.

    This is the branch that separates "which transition applies" from "what is the session's
    status": here the status is ACTIVE and the answer was a main-track one, which is exactly
    the shape that advances — except the loop has already left this concept behind. Without
    the `already_moved_on` check the student would silently skip the next concept too.
    """
    doc_id = _upload_chapter()
    evaluator_script.extend([False, True, False, True, False] + [True] * 8)
    session = _start(doc_id)
    capped_concept = session["current_concept_id"]

    result = _fail_until_cap(session["id"], capped_concept)
    assert result["revealed_answer"] is not None, "expected the attempt cap to have tripped"
    after_cap = result["study_session"]["current_concept_id"]
    assert after_cap != capped_concept

    detail = _override(session["id"], f"{capped_concept}:q1").json()

    assert detail["current_concept_id"] == after_cap, (
        "the cap already advanced past this concept; the override must not advance again"
    )
    assert detail["status"] == "active"
    assert len(_overrides_for(session["id"])) == 1


def test_override_on_a_completed_session_records_without_reviving_it(
    evaluator_script: list[bool],
) -> None:
    """Failing out of the final concept completes the session; disputing that grade still
    deserves a record, but must not resurrect a finished session to re-serve a concept."""
    doc_id = _upload_chapter()
    evaluator_script.extend([False, True, False, True, False])
    session = _start(doc_id)

    # Jump to the chapter's last concept through the store rather than answering four
    # questions to get there: this test is about the completed branch, not the walk. The
    # slug is the stub graph's final concept in topological order.
    store = get_store()
    study_session = store.get_study_session(session["id"])
    last_concept = f"{doc_id}:implicit-differentiation"
    study_session.current_concept_id = last_concept
    store.save_study_session(study_session)

    final = _fail_until_cap(session["id"], last_concept)
    assert final["revealed_answer"] is not None
    assert final["study_session"]["status"] == "completed"

    overridden = final["study_session"]["history"][-1]["question"]["id"]
    response = _override(session["id"], overridden, note="last one was fine")
    assert response.status_code == 200
    assert response.json()["status"] == "completed", "a finished session must stay finished"

    assert _overrides_for(session["id"])[0].student_note == "last one was fine"
