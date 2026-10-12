"""Does the pipeline reach the verdict a human ruled for each disputed answer?

Design doc: docs/specs/2026-10-11-override-feedback-loop-design.md §5. The cases are
answer overrides after triage (tests/override_corpus): real students, real generated
questions, a human ruling on each. Verdict-only and judge-free, like points_geval — the
ruling is ground truth, so the comparison is exact, and the suite stays the cheapest
billed one that touches the evaluator.

Each case is graded in one or two modes (`Case.modes`): `snapshot` holds the rubric the
student actually saw fixed and tests the evaluator; `regenerated` rewrites the points with
question_generator's model and rule 10 (through points_geval's `write_points`, so the two
suites can't drift on how points are written) and tests the generator.
"""

from __future__ import annotations

import os
from functools import lru_cache

from app.models import Answer, EvaluationResult, Question
from app.services import evaluator
from tests.override_corpus.cases import Case, Mode, load_cases
from tests.override_corpus.seeds import seed_cases
from tests.points_geval.support import write_points


def seeds_enabled() -> bool:
    return os.environ.get("OVERRIDE_GEVAL_SEEDS") == "1"


@lru_cache
def all_cases() -> tuple[Case, ...]:
    """Promoted cases, plus the synthetic seeds when asked for. Seeds are opt-in because
    they duplicate eval_geval/points_geval and would bill a run for measuring nothing new."""
    return load_cases() + (seed_cases() if seeds_enabled() else ())


def case_by_id(case_id: str) -> Case:
    return next(c for c in all_cases() if c.id == case_id)


def points_for(case: Case, mode: Mode) -> tuple[str, ...]:
    if mode == "snapshot":
        assert case.required_points is not None, f"{case.id} has no recorded points"
        return case.required_points
    assert case.question_type is not None, f"{case.id} has no question_type"
    return write_points(case.question_type, case.question_prompt, case.expected_answer_notes)


@lru_cache
def grade(case_id: str, mode: Mode) -> EvaluationResult:
    case = case_by_id(case_id)
    question = Question(
        id=f"override:{case.id}",
        concept_id=case.concept,
        prompt=case.question_prompt,
        expected_answer_notes=case.expected_answer_notes,
        required_points=list(points_for(case, mode)),
    )
    return evaluator.evaluate(question, Answer(question_id=question.id, text=case.student_answer))
