"""Free smoke test for the billed tests/points_geval suite.

Pins the parts that can break without any API call: every eval_geval answer has a
ruling and vice versa, the rulings agree with the verdicts eval_geval itself asserts,
the points prompt can still be sliced out of question_generator's system prompt, and
the grading path runs end to end against fake clients.
"""

import json
from types import SimpleNamespace

import pytest

from app.services import evaluator, question_generator
from tests.points_geval import support
from tests.points_geval.rulings import EXPLICIT_RULINGS, VERDICTS


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
