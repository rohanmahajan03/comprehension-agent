"""Free smoke test for the billed tests/points_geval suite.

Pins the parts that can break without any API call: every eval_geval answer has a
ruling and vice versa, the rulings agree with the verdicts eval_geval itself asserts,
the points prompt can still be sliced out of question_generator's system prompt, the
grading path runs end to end against fake clients, and the points judge's calibration
fixtures build and actually discriminate.
"""

import json
from types import SimpleNamespace

import pytest

from app.services import evaluator, question_generator
from tests.points_geval import calibration, judge, support
from tests.points_geval.judge import PointCheck, PointsJudgment
from tests.points_geval.rulings import EXPLICIT_RULINGS, QUESTION_TYPES, VERDICTS


def test_every_eval_geval_answer_has_a_ruling() -> None:
    answers = support.collect_ruled_answers()

    assert {a.name for a in answers} == set(VERDICTS)
    assert EXPLICIT_RULINGS <= set(VERDICTS)
    # Every question has at least one answer ruled each way, or a bar that is too high
    # (or too low) everywhere could pass unnoticed on that question.
    for question_id in {a.question_id for a in answers}:
        verdicts = {a.expected_correct for a in answers if a.question_id == question_id}
        assert verdicts == {True, False}, question_id


def test_points_prompt_carries_rule_10_verbatim() -> None:
    prompt = support.points_system_prompt()

    assert "10. Write `required_points`" in prompt
    assert "conceptual_distinction" in prompt
    # Nothing from the question-writing half of the generator prompt leaks in.
    assert "## Input" not in prompt
    assert "source_ids" not in prompt


@pytest.fixture(autouse=True)
def stub_evaluator() -> None:
    """No-op override of tests/conftest.py's autouse stub: the grading path has to reach
    the real evaluate(), whose client is faked below."""


def _fake_response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])


def test_grading_path_runs_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_points(**kwargs: object) -> SimpleNamespace:
        return _fake_response({"required_points": ["A fault is a component deviation.", "  "]})

    def fake_evaluate(**kwargs: object) -> SimpleNamespace:
        seen["prompt"] = kwargs["messages"][0]["content"]
        return _fake_response(
            {"point_checks": [], "correct": True, "explanation": "ok"}
        )

    monkeypatch.setattr(
        question_generator, "_client",
        lambda: SimpleNamespace(messages=SimpleNamespace(create=fake_points)),
    )
    monkeypatch.setattr(
        evaluator, "_client",
        lambda: SimpleNamespace(messages=SimpleNamespace(create=fake_evaluate)),
    )
    support.generate_points.cache_clear()
    support.grade.cache_clear()
    try:
        result = support.grade("test_ch1_fault_vs_failure_clearly_correct")
    finally:
        support.generate_points.cache_clear()
        support.grade.cache_clear()

    assert result.correct is True
    # Blank points are stripped, as generate_questions() does before persisting.
    assert "REQUIRED POINTS:\n1. A fault is a component deviation.\n\n" in seen["prompt"]


# --- points judge -------------------------------------------------------------------


def test_calibration_fixtures_cover_every_question_and_direction() -> None:
    fixtures = calibration.calibration_fixtures()
    by_kind = {kind: [f for f in fixtures if f.kind == kind] for kind in ("ideal", "padded", "bundled", "thinned")}

    assert {f.question_id for f in by_kind["ideal"]} == set(QUESTION_TYPES)
    assert all(by_kind.values())
    assert len({f.name for f in fixtures}) == len(fixtures)
    for f in by_kind["ideal"]:
        assert f.points == next(
            a.handwritten_points for a in support.collect_ruled_answers() if a.question_id == f.question_id
        )
    # Every planted point exists, and padding plants the point it appended.
    for f in by_kind["padded"] + by_kind["bundled"]:
        assert f.planted is not None and 0 <= f.planted < len(f.points)
    for f in by_kind["padded"]:
        assert f.planted == len(f.points) - 1


def _judgment(essential: list[bool], sufficient: bool) -> PointsJudgment:
    checks = tuple(PointCheck(f"p{i}", e, "") for i, e in enumerate(essential))
    return PointsJudgment(checks, (), sufficient)


def test_fixture_hit_discriminates() -> None:
    """A judge that flags everything, or nothing, must fail some category — otherwise the
    calibration rates could all pass while measuring nothing."""
    fixtures = calibration.calibration_fixtures()

    def hits(make) -> set[str]:
        return {f.kind for f in fixtures if f.hit(make(f))}

    flag_nothing = lambda f: _judgment([True] * len(f.points), True)  # noqa: E731
    flag_everything = lambda f: _judgment([False] * len(f.points), False)  # noqa: E731

    assert hits(flag_nothing) == {"ideal"}
    assert hits(flag_everything) == {"padded", "bundled", "thinned"}


def _fake_judge(payload: dict, seen: dict):
    def create(**kwargs: object) -> SimpleNamespace:
        seen.update(kwargs)
        return _fake_response(payload)

    return lambda: SimpleNamespace(messages=SimpleNamespace(create=create))


def test_judge_points_reads_and_aligns_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}
    payload = {
        "point_checks": [
            {"point": "a", "essential": True, "reasoning": "r"},
            {"point": "b", "essential": False, "reasoning": "elaboration"},
        ],
        "missing": [],
        "sufficient": True,
    }
    monkeypatch.setattr(judge, "_client", _fake_judge(payload, seen))

    result = judge.judge_points("conceptual_correctness", "Q?", "Model.", ("a", "b"))

    assert result.inessential == [1]
    assert result.over_requires and not result.under_requires and not result.sound
    assert "QUESTION TYPE: conceptual_correctness" in seen["messages"][0]["content"]
    assert "REQUIRED POINTS:\n1. a\n2. b" in seen["messages"][0]["content"]


def test_judge_points_rejects_misaligned_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "point_checks": [{"point": "a", "essential": True, "reasoning": "r"}],
        "missing": [],
        "sufficient": True,
    }
    monkeypatch.setattr(judge, "_client", _fake_judge(payload, {}))

    with pytest.raises(ValueError, match="1 point checks for 2 points"):
        judge.judge_points("conceptual_correctness", "Q?", "Model.", ("a", "b"))
