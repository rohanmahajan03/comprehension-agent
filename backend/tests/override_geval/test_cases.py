"""One test per (case, grading mode): does the real pipeline reach the ruled verdict?
See support.py for the design."""

import pytest

from .support import all_cases, case_by_id, grade, points_for

_PARAMS = [(c.id, mode) for c in all_cases() for mode in c.modes]


@pytest.mark.skipif(
    not _PARAMS,
    reason="no promoted cases yet — run tests.override_corpus.triage, "
    "or set OVERRIDE_GEVAL_SEEDS=1 to run the synthetic seeds",
)
@pytest.mark.parametrize(("case_id", "mode"), _PARAMS or [("none", "snapshot")])
def test_verdict_matches_ruling(case_id: str, mode: str) -> None:
    case = case_by_id(case_id)
    result = grade(case_id, mode)
    points = "\n".join(f"  - {p}" for p in points_for(case, mode))
    assert result.correct is case.expected_correct, (
        f"[{case.category} → {case.component}, {mode}] ruled correct={case.expected_correct}, "
        f"evaluator said {result.correct}.\npoints:\n{points}\nevaluator: {result.explanation}"
    )
