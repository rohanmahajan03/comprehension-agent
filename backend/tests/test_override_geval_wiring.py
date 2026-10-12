"""Free smoke test for the override feedback loop (tests/override_corpus, tests/override_geval).

Pins everything that can break without an API call: the anonymous key and the split that
must never move, which modes a case can be graded in, the invariants that stop a malformed
case reaching the billed suite, promotion from rulings (both verdict directions, the
`unclear` exclusion, a re-ruling replacing the first), the classifier's response parsing,
the calibration fixtures' claims about themselves, and the grading path end to end
against fake clients. Design doc: docs/specs/2026-10-11-override-feedback-loop-design.md.
"""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.models import AnswerOverride
from app.services import evaluator, question_generator
from tests.override_corpus import calibration, triage
from tests.override_corpus.cases import (
    Case,
    load_cases,
    override_key,
    split_for,
    validate,
    write_cases,
)
from tests.override_corpus.seeds import seed_cases
from tests.override_geval import support
from tests.points_geval import support as points_support


def _case(**overrides) -> Case:
    key = overrides.pop("id", override_key("s1", 0))
    fields = dict(
        id=key, synthetic=False, split=split_for(key), category="paraphrase_missed",
        component="evaluator", question_kind="pipeline1", question_type="conceptual_correctness",
        concept="limits", question_prompt="What is a limit?",
        expected_answer_notes="The value a function approaches near a point.",
        required_points=("A limit is the value a function approaches.",),
        student_answer="what f(x) tends to as x nears a", student_note=None,
        evaluator_explanation="Did not explain approaching.", evaluator_model="claude-haiku-4-5",
    )
    return Case(**{**fields, **overrides})


# --- keys and splits ---------------------------------------------------------------------


def test_key_is_stable_and_carries_no_session_id() -> None:
    key = override_key("3f9c-session-uuid", 4)
    assert key == override_key("3f9c-session-uuid", 4)
    assert key != override_key("3f9c-session-uuid", 5)
    assert "3f9c" not in key


def test_split_is_a_pure_function_of_the_key_and_roughly_balanced() -> None:
    keys = [override_key("s", i) for i in range(200)]
    assert [split_for(k) for k in keys] == [split_for(k) for k in keys]
    tune = sum(split_for(k) == "tune" for k in keys)
    assert 70 < tune < 130


# --- grading modes -----------------------------------------------------------------------


def test_misgrade_runs_only_in_the_mode_its_component_dictates() -> None:
    assert _case(component="evaluator").modes == ("snapshot",)
    assert _case(category="points_overreach", component="question_generator").modes == (
        "regenerated",
    )


def test_invalid_override_guards_every_mode_it_can() -> None:
    invalid = _case(category="override_invalid", component="none")
    assert invalid.modes == ("snapshot", "regenerated")
    assert replace(invalid, required_points=None).modes == ("regenerated",)
    assert replace(invalid, question_type=None).modes == ("snapshot",)
    # Diagnostic probes aren't written by question_generator, so regenerating their points
    # with rule 10 would test something production never does.
    assert replace(invalid, question_kind="diagnostic").modes == ("snapshot",)


def test_empty_points_are_gradable_but_unrecorded_points_are_not() -> None:
    assert _case(required_points=()).modes == ("snapshot",)
    assert _case(required_points=None).modes == ()


def test_expected_verdict_follows_the_category() -> None:
    assert _case(category="paraphrase_missed").expected_correct is True
    assert _case(category="override_invalid", component="none").expected_correct is False


# --- invariants and files ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "message"),
    [
        (_case(category="unclear"), "can't be a case"),
        (_case(split="holdout" if split_for(override_key("s1", 0)) == "tune" else "tune"),
         "moved by hand"),
        (_case(required_points=None), "no way to grade it"),
        (_case(question_type="essay"), "unknown question_type"),
    ],
)
def test_validate_rejects(case: Case, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate([case])


def test_validate_rejects_duplicate_ids() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        validate([_case(), _case()])


def test_cases_round_trip_keeping_none_and_empty_points_apart(tmp_path) -> None:
    path = tmp_path / "cases.jsonl"
    cases = [
        _case(id=override_key("s1", 0)),
        _case(id=override_key("s1", 1), required_points=()),
        _case(id=override_key("s1", 2), category="override_invalid", component="none",
              required_points=None),
    ]
    write_cases(cases, path)
    assert sorted(load_cases(path), key=lambda c: c.id) == sorted(cases, key=lambda c: c.id)


def test_missing_cases_file_is_no_cases(tmp_path) -> None:
    assert load_cases(tmp_path / "absent.jsonl") == ()


# --- triage ------------------------------------------------------------------------------


def _override(**overrides) -> AnswerOverride:
    fields = dict(
        study_session_id="sess-uuid", history_seq=2, question_id="doc-uuid:limits:q1",
        concept_id="doc-uuid:limits", doc_id="doc-uuid", question_prompt="What is a limit?",
        expected_answer_notes="The value approached.", student_answer="what it tends to",
        evaluator_explanation="Missing approach.", required_points=["Approached value."],
        evaluator_model="claude-haiku-4-5", question_kind="pipeline1",
    )
    return AnswerOverride(**{**fields, **overrides})


def test_snapshot_is_anonymized() -> None:
    snapshot = triage.snapshot_from_override(_override())
    assert snapshot["key"] == override_key("sess-uuid", 2)
    assert snapshot["concept"] == "limits"
    assert "doc-uuid" not in json.dumps(snapshot)
    assert "sess-uuid" not in json.dumps(snapshot)


def test_render_tells_unrecorded_points_from_self_chosen_ones() -> None:
    unrecorded = triage.render(triage.snapshot_from_override(_override(required_points=None)))
    self_chosen = triage.render(triage.snapshot_from_override(_override(required_points=[])))
    assert "not recorded" in unrecorded
    assert "grader chose its own points" in self_chosen


def _record(key: str, points=("Approached value.",)) -> dict:
    snapshot = triage.snapshot_from_override(_override())
    return {"key": key, "snapshot": {**snapshot, "key": key, "required_points": list(points)
                                     if points is not None else None}}


def _ruling(key: str, category: str, component: str, **extra) -> dict:
    return {"key": key, "category": category, "component": component,
            "question_type": "conceptual_correctness", "accepted_unchanged": True, **extra}


def test_promote_turns_rulings_into_cases_in_both_directions() -> None:
    a, b, c = (override_key("s", i) for i in range(3))
    result = triage.promote(
        [_record(a), _record(b), _record(c)],
        [_ruling(a, "paraphrase_missed", "evaluator"),
         _ruling(b, "override_invalid", "none"),
         _ruling(c, "unclear", "none")],
    )
    verdicts = {case.id: case.expected_correct for case in result.cases}
    assert verdicts == {a: True, b: False}
    assert result.skipped == ((c, "ruled unclear"),)
    assert all(case.split == split_for(case.id) for case in result.cases)


def test_a_later_ruling_replaces_an_earlier_one() -> None:
    key = override_key("s", 0)
    result = triage.promote(
        [_record(key)],
        [_ruling(key, "paraphrase_missed", "evaluator"),
         _ruling(key, "override_invalid", "none", accepted_unchanged=False)],
    )
    assert [c.category for c in result.cases] == ["override_invalid"]
    assert triage.agreement(
        [_ruling(key, "paraphrase_missed", "evaluator"),
         _ruling(key, "override_invalid", "none", accepted_unchanged=False)]
    ) == (0, 1)


def test_promote_reports_what_it_cannot_grade_instead_of_dropping_it() -> None:
    a, b = override_key("s", 0), override_key("s", 1)
    result = triage.promote(
        [_record(a, points=None)],
        [_ruling(a, "paraphrase_missed", "evaluator"), _ruling(b, "paraphrase_missed", "evaluator")],
    )
    assert result.cases == ()
    assert {key for key, _ in result.skipped} == {a, b}


def _fake_response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])


def test_propose_parses_the_classifier_response(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_create(**kwargs):
        seen.update(kwargs)
        return _fake_response({"quoted_point": "Approached value.", "rationale": "r",
                               "category": "paraphrase_missed", "component": "evaluator",
                               "question_type": "unknown"})

    monkeypatch.setattr(triage, "_client",
                        lambda: SimpleNamespace(messages=SimpleNamespace(create=fake_create)))
    proposal = triage.propose(triage.snapshot_from_override(_override()))

    assert proposal.category == "paraphrase_missed"
    assert proposal.question_type is None
    assert "STUDENT ANSWER:\nwhat it tends to" in seen["messages"][0]["content"]
    assert seen["model"] != evaluator.MODEL, "the classifier must not be the graded model"


# --- calibration fixtures and seeds ------------------------------------------------------


def test_calibration_covers_both_sides_of_every_dispute() -> None:
    fixtures = calibration.calibration_fixtures()
    expected = {f.expected for f in fixtures}
    assert expected == {"points_overreach", "paraphrase_missed", "override_invalid"}
    assert all(sum(f.expected == e for f in fixtures) >= 3 for e in expected)


def test_overreach_and_paraphrase_fixtures_share_an_answer() -> None:
    """The docstring's claim: with the answer held fixed, only the points separate the two
    categories — so a classifier keyed on the answer or note can't pass both."""
    fixtures = calibration.calibration_fixtures()

    def answers(category):
        return {f.snapshot["student_answer"] for f in fixtures if f.expected == category}

    assert answers("points_overreach") & answers("paraphrase_missed")


def test_seed_cases_are_synthetic_gradable_and_valid() -> None:
    seeds = seed_cases()
    assert len(seeds) == len(calibration.calibration_fixtures())
    assert all(c.synthetic and c.modes for c in seeds)


# --- grading path ------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def stub_evaluator() -> None:
    """No-op override of tests/conftest.py's autouse stub: the grading path has to reach
    the real evaluate(), whose client is faked below."""


def test_grading_path_runs_in_both_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    invalid = _case(category="override_invalid", component="none")
    monkeypatch.setattr(support, "all_cases", lambda: (invalid,))
    prompts: list[str] = []

    def fake_evaluate(**kwargs):
        prompts.append(kwargs["messages"][0]["content"])
        return _fake_response({"point_checks": [], "correct": False, "explanation": "no"})

    monkeypatch.setattr(evaluator, "_client",
                        lambda: SimpleNamespace(messages=SimpleNamespace(create=fake_evaluate)))
    monkeypatch.setattr(
        question_generator, "_client",
        lambda: SimpleNamespace(messages=SimpleNamespace(
            create=lambda **_: _fake_response({"required_points": ["Regenerated point."]})
        )),
    )
    support.grade.cache_clear()
    points_support.write_points.cache_clear()
    try:
        results = [support.grade(invalid.id, mode) for mode in invalid.modes]
    finally:
        support.grade.cache_clear()
        points_support.write_points.cache_clear()

    assert [r.correct for r in results] == [False, False]
    assert "A limit is the value a function approaches." in prompts[0]
    assert "Regenerated point." in prompts[1]
