"""Shared scaffolding for the G-Eval regression suite.

Each test builds a Question/Answer pair from tests/geval_test_suite.md, runs
the real evaluator LLM call, then scores the evaluator's explanation with a
GEval metric built from that question's frozen criteria + evaluation_steps
(see criteria.py).
"""

from __future__ import annotations

from functools import lru_cache

from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.models import AnthropicModel
from deepeval.test_case import LLMTestCase, SingleTurnParams

from app.config import get_settings
from app.models import Answer, Question
from app.services import evaluator

from .criteria import GEvalSpec

# Judge model for the GEval metrics below — deliberately a different (and
# stronger) model than the evaluator under test (`claude-haiku-4-5`, see
# app/services/evaluator.py) so the suite isn't a model grading its own
# homework. Must be a model deepeval's AnthropicModel recognizes (see
# deepeval.models.llms.constants.ANTHROPIC_MODELS_DATA) — an unrecognized
# name crashes during cost-tracking setup rather than failing gracefully.
_JUDGE_MODEL = "claude-opus-4-5"


@lru_cache
def _judge_model() -> AnthropicModel:
    return AnthropicModel(
        model=_JUDGE_MODEL,
        api_key=get_settings().llm_api_key,
        temperature=0,
    )


def assert_evaluator_judgment(
    *,
    question_id: str,
    concept_id: str,
    prompt: str,
    golden_answer: str,
    required_points: list[str],
    student_answer: str,
    metric_name: str,
    spec: GEvalSpec,
    threshold: float = 0.7,
    expected_correct: bool | None = None,
) -> None:
    """Run the real evaluator on `student_answer`, then G-Eval-score its
    explanation against `golden_answer`.

    `expected_correct`, when given, also asserts the evaluator's verdict
    directly. Without it the verdict is only judged indirectly, by the GEval
    judge reading the criteria — which is ambiguous for a variant sitting on
    the line between "concise but correct" and "partial".

    `spec.evaluation_steps` must be frozen (generated once, hardcoded in
    criteria.py) so the judge's rubric isn't regenerated on every run.
    """
    question = Question(
        id=question_id,
        concept_id=concept_id,
        prompt=prompt,
        expected_answer_notes=golden_answer,
        required_points=required_points,
    )
    answer = Answer(question_id=question_id, text=student_answer)

    result = evaluator.evaluate(question, answer)

    if expected_correct is not None:
        assert result.correct is expected_correct, (
            f"evaluator returned correct={result.correct}, expected "
            f"{expected_correct}: {result.explanation}"
        )

    test_case = LLMTestCase(
        input=student_answer,
        actual_output=result.explanation,
        expected_output=golden_answer,
    )
    metric = GEval(
        name=metric_name,
        criteria=spec.criteria,
        evaluation_steps=spec.evaluation_steps,
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
        ],
        model=_judge_model(),
        threshold=threshold,
    )
    assert_test(test_case, [metric])
