"""Free smoke test for the billed tests/question_geval suite.

That suite only runs with LLM_API_KEY set, so nothing else in the free test run ever
executes `score_case()` or the CaseResult properties it feeds. A plain import check
doesn't help either: a name that's only referenced *inside* those functions resolves
fine at import time and blows up at call time. This drives the whole path with fake
clients so a wiring break costs a second here instead of a ~14-minute billed run.

Scope is deliberately narrow: it asserts the code path executes and the checks report
on well-formed input. It says nothing about generation quality — that's the real
suite's job.
"""

import json
from types import SimpleNamespace

import pytest

from app.services import question_generator
from tests.question_geval import support


def _fake_response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])


@pytest.fixture
def fake_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for both the generator and the judge, with well-formed output."""

    def fake_generate(**kwargs: object) -> SimpleNamespace:
        # Cite the target concept's own passage, which every concept has.
        return _fake_response(
            {
                "concept_id": "x",
                "questions": [
                    {
                        "type": "conceptual_correctness",
                        "question": "What is it?",
                        "expected_answer": "A sufficiently long model answer that states "
                        "the substance of the concept in the student's own voice.",
                        "source_ids": ["s1"],
                    }
                ],
            }
        )

    def fake_judge(**kwargs: object) -> SimpleNamespace:
        # Superset of both judge schemas; each caller reads only its own key.
        return _fake_response(
            {"grounded": True, "answers_question": True, "reasoning": "fine"}
        )

    monkeypatch.setattr(
        question_generator,
        "_client",
        lambda: SimpleNamespace(messages=SimpleNamespace(create=fake_generate)),
    )
    monkeypatch.setattr(
        support,
        "_judge_client",
        lambda: SimpleNamespace(messages=SimpleNamespace(create=fake_judge)),
    )


def test_score_case_path_executes_and_all_checks_report(fake_clients: None) -> None:
    # __wrapped__ bypasses score_case's lru_cache: caching this fake result would
    # otherwise be served to the real suite if both ever run in one process.
    result = support.score_case.__wrapped__()

    assert result.raw_by_concept, "no concepts scored"
    assert result.passages_by_concept.keys() == result.raw_by_concept.keys()

    # Every check's code path, including the message builders used only on failure.
    assert not result.grounding_violations, result.grounding_violations_message()
    assert not result.expected_answer_violations, result.expected_answer_violations_message()
    assert result.type_recall >= 0.0 and result.missed_types_message()
    assert result.evidence_basis_rate == 1.0 and result.evidence_basis_message()
    assert result.answer_quality_rate == 1.0 and result.answer_quality_message()


def test_grounding_check_catches_model_typed_text(fake_clients: None) -> None:
    """The standing guard: `grounding` must stay a verbatim join of cited passages."""
    result = support.score_case.__wrapped__()
    concept_id = next(iter(result.raw_by_concept))
    result.raw_by_concept[concept_id][0]["grounding"] = "text the model typed itself"

    violations = result.grounding_violations
    assert any("not the verbatim join" in v for v in violations), violations
