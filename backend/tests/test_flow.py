"""End-to-end walk through both pipelines against the stub services."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Question, StudySessionStatus
from app.routers.study_session import _MAX_CONCEPT_ATTEMPTS, _MAX_DIAGNOSTIC_CHAIN
from app.services import graph_builder, question_generator
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


def _start(doc_id: str) -> dict:
    response = client.post("/api/study-session/start", json={"doc_id": doc_id})
    assert response.status_code == 201
    return response.json()


def _answer(session_id: str, question_id: str, text: str = "my answer") -> dict:
    response = client.post(
        f"/api/study-session/{session_id}/answer",
        json={"question_id": question_id, "text": text},
    )
    assert response.status_code == 200
    return response.json()


def _answer_until_reveal(session: dict, start_from: dict | None = None) -> tuple[dict, dict]:
    """Follow the loop — answering whatever it serves next — until one of the caps trips.

    The caller scripts the evaluator; this just walks the path a client would. Returns
    (the question that was abandoned, the response that revealed its answer).

    `start_from` overrides the session's opening question, for callers that have already
    walked it forward onto a concept with prerequisites.
    """
    served = start_from or session["pending_question"]
    body = _answer(session["id"], served["id"])
    while body["revealed_answer"] is None:
        assert body["next_question"] is not None, "the loop stalled with no question to serve"
        served = body["next_question"]
        body = _answer(session["id"], served["id"])
    return served, body


def _advance_to_a_dependent_concept(started: dict) -> tuple[str, dict]:
    """Answer the chapter's root concept correctly and return `(concept_id, question)` for
    the next one, which has a prerequisite.

    Necessary for any test about the *prerequisite* branch. `stub_diagnoser` names a
    concept's first `depends_on` entry and falls back to the concept itself, so a session
    sitting on the topologically-first concept can only ever self-diagnose — and a test
    written there silently exercises the self-diagnosis branch instead of the one its name
    claims. Four tests here did exactly that until the two branches were separated.

    Costs one scripted `True` at the front of `evaluator_script`.
    """
    body = _answer(started["id"], started["pending_question"]["id"])
    assert body["evaluation"]["correct"], "the first scripted grade must pass to move off the root"
    return body["study_session"]["current_concept_id"], body["next_question"]


def test_correct_diagnostic_returns_to_the_concept_that_failed(
    evaluator_script: list[bool],
) -> None:
    """The regression test for the loop's missing return step (design doc §1a).

    Pipeline 2 exists to trace a wrong answer back to the prerequisite at fault, have the
    student repair it, and then return. The correct-branch used to advance unconditionally,
    so passing the diagnostic on prerequisite P marked concept X done without the student
    ever demonstrating X — and inflated `completed_concepts` on the menu screen with it.
    """
    # pass the root concept, fail the next one, then pass its prerequisite probe
    evaluator_script.extend([True, False, True])
    doc_id = _upload_chapter()
    started = _start(doc_id)
    concept_id, question = _advance_to_a_dependent_concept(started)

    wrong = _answer(started["id"], question["id"])
    assert wrong["study_session"]["status"] == "diagnosing"
    assert wrong["diagnosis"]["suspected_gap_concept_id"] != concept_id, (
        "this test is about the prerequisite branch, so the suspect must be another concept"
    )

    body = _answer(started["id"], wrong["diagnosis"]["targeted_question"]["id"])
    study_session = body["study_session"]
    assert study_session["current_concept_id"] == concept_id, (
        "closing the prerequisite gap must hand the student back the concept that exposed "
        "it, not skip past it"
    )
    assert study_session["status"] == "active"
    assert body["next_question"]["id"] == question["id"], (
        "the concept's own question is re-served: diagnostic questions are appended after "
        "the generated set, so index 0 is still the main-track question"
    )
    assert body["revealed_answer"] is None


def test_correct_self_diagnostic_advances_instead_of_re_serving_the_concept(
    evaluator_script: list[bool],
) -> None:
    """The other side of §2's return rule: it only applies to a *prerequisite* probe.

    `stub_diagnoser` falls back to the answered concept when it has no `depends_on`, and
    the real diagnoser self-diagnoses too (CLAUDE.md records `hash_index` doing exactly
    that). The probe is then a question *about this concept*, so answering it correctly
    demonstrates the concept — there is nothing to hand back.

    Reading "was a diagnostic" as "do not advance" made this a treadmill: the loop returned
    to the same concept and `_pending_question` re-served the question that started it, so
    a correct answer moved nothing. Bounded only by `_MAX_CONCEPT_ATTEMPTS`, and invisible
    because every test covering the return step started on the root concept.
    """
    evaluator_script.extend([False, True, True])  # fail the root, then pass its own probe
    doc_id = _upload_chapter()
    started = _start(doc_id)
    concept_id = started["current_concept_id"]
    question = started["pending_question"]

    wrong = _answer(started["id"], question["id"])
    probe = wrong["diagnosis"]["targeted_question"]
    assert wrong["diagnosis"]["suspected_gap_concept_id"] == concept_id, (
        "a root concept has no prerequisites, so the diagnoser can only name itself"
    )

    body = _answer(started["id"], probe["id"])

    assert body["study_session"]["current_concept_id"] == f"{doc_id}:continuity", (
        "the probe was about this concept, so passing it advances rather than returning"
    )
    assert body["study_session"]["status"] == "active"
    assert body["next_question"]["id"] != question["id"], (
        "re-serving the question that started the drill is the treadmill this prevents"
    )


def test_concept_is_left_behind_only_once_answered_correctly(
    evaluator_script: list[bool],
) -> None:
    """The other half of §2's rule: the retry is what advances, and nothing before it."""
    # pass the root, fail X, pass X's prerequisite probe, pass X
    evaluator_script.extend([True, False, True, True])
    doc_id = _upload_chapter()
    started = _start(doc_id)
    concept_id, question = _advance_to_a_dependent_concept(started)
    assert concept_id == f"{doc_id}:continuity"

    diagnostic = _answer(started["id"], question["id"])["diagnosis"]["targeted_question"]
    returned = _answer(started["id"], diagnostic["id"])["study_session"]
    assert returned["current_concept_id"] == concept_id

    body = _answer(started["id"], question["id"])
    # The stub graph's topological order is limits, continuity, derivatives, chain-rule,
    # implicit-differentiation.
    assert body["study_session"]["current_concept_id"] == f"{doc_id}:derivatives"
    assert body["study_session"]["status"] == "active"


def test_attempt_cap_reveals_the_answer_and_moves_on(evaluator_script: list[bool]) -> None:
    """Without a cap on attempts, §2's return rule would re-serve X forever (design doc §3).

    Each failure is followed by a passed diagnostic, so the drill never stalls — only the
    count of wrong answers on X's own question decides. The final attempt triggers no
    diagnosis: the loop gives up instead, which is what makes the ceiling A + (A-1) × C
    rather than A × (1 + C).
    """
    # The leading True moves off the root concept: a passed probe only *returns* when the
    # probe was on another concept, so accumulating attempts on one question requires a
    # concept that actually has a prerequisite (see `_advance_to_a_dependent_concept`).
    evaluator_script.extend(
        [True] + [False, True] * (_MAX_CONCEPT_ATTEMPTS - 1) + [False]
    )
    doc_id = _upload_chapter()
    started = _start(doc_id)
    _, question = _advance_to_a_dependent_concept(started)

    abandoned, body = _answer_until_reveal(started, question)
    assert abandoned["id"] == question["id"]
    assert body["revealed_answer"] == abandoned["expected_answer_notes"]
    assert body["diagnosis"] is None, "the capped attempt gives up instead of drilling again"
    assert body["study_session"]["status"] == "active"
    assert body["study_session"]["current_concept_id"] == f"{doc_id}:derivatives", (
        "a capped concept is left unmastered, deliberately, rather than parked on"
    )

    failures = [
        entry
        for entry in body["study_session"]["history"]
        if entry["question"]["id"] == abandoned["id"] and not entry["evaluation"]["correct"]
    ]
    assert len(failures) == _MAX_CONCEPT_ATTEMPTS


def test_diagnostic_chain_cap_stops_drilling_and_returns_to_the_concept(
    evaluator_script: list[bool],
) -> None:
    """The second door (design doc §3): a student failing every diagnostic.

    The session starts on a root concept, so the stub diagnoser names it as its own suspect
    — the documented shape that makes the drill unbounded without this cap. Giving up here
    returns to the concept rather than advancing, because the concept itself has not been
    abandoned: its own attempt budget is untouched by failed diagnostics.
    """
    evaluator_script.extend([False] * (_MAX_DIAGNOSTIC_CHAIN + 1))
    doc_id = _upload_chapter()
    started = _start(doc_id)
    question = started["pending_question"]

    abandoned, body = _answer_until_reveal(started)
    assert abandoned["id"] != question["id"], "the abandoned question is the last diagnostic"
    assert body["revealed_answer"] == abandoned["expected_answer_notes"]
    assert body["diagnosis"] is None
    assert body["study_session"]["status"] == "active"
    assert body["study_session"]["current_concept_id"] == f"{doc_id}:limits"
    assert body["next_question"]["id"] == question["id"], (
        "the student is handed back the concept's own question, with attempts left on it"
    )
    assert len(body["study_session"]["history"]) == 1 + _MAX_DIAGNOSTIC_CHAIN


def test_reveal_and_next_question_arrive_in_one_response(
    evaluator_script: list[bool],
) -> None:
    """One response carries both halves when a cap trips mid-chapter (design doc §7).

    The frontend renders the reveal in the result card and the next question below it, so
    the student is never left with an answer and nothing to do — and the next question is
    the same one the resume path would serve.
    """
    evaluator_script.extend(
        [True] + [False, True] * (_MAX_CONCEPT_ATTEMPTS - 1) + [False]
    )
    doc_id = _upload_chapter()
    started = _start(doc_id)
    _, question = _advance_to_a_dependent_concept(started)

    _, body = _answer_until_reveal(started, question)
    assert body["revealed_answer"]
    assert body["next_question"]["id"] == f"{doc_id}:derivatives:q1"

    resumed = client.get(f"/api/study-session/{started['id']}").json()
    assert resumed["pending_question"]["id"] == body["next_question"]["id"]


def _generate_one_question_except(*empty_slugs: str):
    """Stand in for conftest's question-generator stub, leaving the named concepts empty.

    `question_generator`'s rule 3 tells the model to skip any question type that doesn't fit
    the evidence, so a concept legitimately coming back with no questions is what this
    reproduces — the conftest stub always writes two per concept and can't.
    """

    def _generate(graph) -> None:
        for concept in graph.concepts:
            slug = concept.id.split(":", 1)[1]
            concept.questions = (
                []
                if slug in empty_slugs
                else [
                    Question(
                        id=f"{concept.id}:q1",
                        concept_id=concept.id,
                        prompt=f"In your own words, explain what “{concept.name}” means.",
                        expected_answer_notes=f"A correct answer restates: {concept.summary}",
                    )
                ]
            )

    return _generate


def test_concepts_without_questions_are_skipped(
    monkeypatch: pytest.MonkeyPatch, evaluator_script: list[bool]
) -> None:
    """A question-less concept is stepped over, not parked on (design doc §1c, §5).

    Parking on one leaves `_pending_question` returning None: the UI renders "No question
    available", there is nothing to submit, and the session is deadlocked permanently. Both
    ways in are guarded — `start_study_session` at birth, `_advance` mid-chapter.
    """
    evaluator_script.append(True)
    monkeypatch.setattr(
        question_generator,
        "generate_questions",
        _generate_one_question_except("limits", "derivatives"),
    )
    doc_id = _upload_chapter()

    started = _start(doc_id)
    assert started["current_concept_id"] == f"{doc_id}:continuity", (
        "the first concept in topological order has no question, so the session opens on "
        "the next one that does"
    )
    assert started["pending_question"] is not None

    body = _answer(started["id"], started["pending_question"]["id"])
    assert body["study_session"]["current_concept_id"] == f"{doc_id}:chain-rule", (
        "advancing skips `derivatives`, which has no question to serve"
    )
    assert body["next_question"] is not None


def test_chapter_with_no_questions_starts_a_completed_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The degenerate end of the same guard: nothing to ask means nothing to study.

    Born completed rather than 201-ing into an active session with no question, which the
    student could neither answer nor leave.
    """

    def _no_questions(graph) -> None:
        for concept in graph.concepts:
            concept.questions = []

    monkeypatch.setattr(question_generator, "generate_questions", _no_questions)
    doc_id = _upload_chapter()

    started = _start(doc_id)
    assert started["status"] == "completed"
    assert started["pending_question"] is None


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

    Independent of `DELETE /api/study-session/{id}` (docs/specs/2026-09-03-delete-study-
    session-design.md) — completion drops a session from this list automatically; delete
    removes a session (of any status) from the store entirely.
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


def test_delete_session_removes_it() -> None:
    doc_id = _upload_chapter()
    session_id = client.post("/api/study-session/start", json={"doc_id": doc_id}).json()["id"]

    assert client.delete(f"/api/study-session/{session_id}").status_code == 204
    assert client.get(f"/api/study-session/{session_id}").status_code == 404


def test_delete_unknown_session_404s() -> None:
    assert client.delete("/api/study-session/does-not-exist").status_code == 404


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


def _list_documents() -> list[dict]:
    response = client.get("/api/textbook")
    assert response.status_code == 200
    return response.json()


def _find_doc(rows: list[dict], doc_id: str) -> dict | None:
    return next((r for r in rows if r["id"] == doc_id), None)


def test_list_documents_returns_uploaded_chapter() -> None:
    """The "your chapters" list is how a new session can start against a graph already
    in the DB, without re-uploading — this is that list's happy path."""
    doc_id = client.post(
        "/api/textbook",
        json={"text": "A sample chapter about calculus.", "title": "Calculus I"},
    ).json()["doc_id"]

    row = _find_doc(_list_documents(), doc_id)
    assert row is not None
    assert row["title"] == "Calculus I"
    assert row["total_concepts"] == 5  # the stub graph's concept count


def test_list_documents_sorted_most_recently_created_first() -> None:
    older = _upload_chapter()
    newer = _upload_chapter()

    # Other tests share the store's singleton, so compare positions of just these two.
    ids = [r["id"] for r in _list_documents()]
    assert ids.index(newer) < ids.index(older)
