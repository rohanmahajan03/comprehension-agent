"""Shared test fixtures."""

from itertools import count

import pytest

from app.models import Answer, EvaluationResult, Question
from app.services import evaluator


@pytest.fixture(autouse=True)
def stub_evaluator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real LLM call with a deterministic stub so tests never hit the API.

    Alternates correct/incorrect per call so both the "advance" and "diagnose"
    branches of the study-session loop get exercised, mirroring the old stub.
    """
    call_counter = count()

    def _fake_evaluate(question: Question, answer: Answer) -> EvaluationResult:
        correct = next(call_counter) % 2 == 0
        return EvaluationResult(
            correct=correct,
            explanation=f"[test stub] marked {'correct' if correct else 'incorrect'}",
        )

    monkeypatch.setattr(evaluator, "evaluate", _fake_evaluate)
