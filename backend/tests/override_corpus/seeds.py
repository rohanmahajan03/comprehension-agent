"""Synthetic cases, for exercising the pipeline before any real override exists (§7).

Built from the triage calibration fixtures rather than written separately: each already
pairs a ruled answer with a known category, which is exactly a confirmed ruling. Flagged
`synthetic`, so every reported number excludes them — they duplicate what eval_geval and
points_geval already measure, and prove only that the plumbing works, not that the loop
does. tests/override_geval runs them only when `OVERRIDE_GEVAL_SEEDS=1`.
"""

from __future__ import annotations

from functools import lru_cache

from .calibration import calibration_fixtures
from .cases import DEFAULT_COMPONENT, Case, split_for, validate


@lru_cache
def seed_cases() -> tuple[Case, ...]:
    cases = tuple(
        Case(
            id=f["key"],
            synthetic=True,
            split=split_for(f["key"]),
            category=fixture.expected,
            component=DEFAULT_COMPONENT[fixture.expected] or "evaluator",
            question_kind=f["question_kind"],
            question_type=fixture.question_type,
            concept=f["concept"],
            question_prompt=f["question_prompt"],
            expected_answer_notes=f["expected_answer_notes"],
            required_points=tuple(f["required_points"]),
            student_answer=f["student_answer"],
            student_note=f["student_note"],
            evaluator_explanation=f["evaluator_explanation"],
            evaluator_model=f["evaluator_model"],
            reviewer_note=fixture.basis,
        )
        for fixture in calibration_fixtures()
        for f in (fixture.snapshot,)
    )
    validate(cases)
    return cases
