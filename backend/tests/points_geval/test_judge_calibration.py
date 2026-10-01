"""Calibrating the points judge against fixtures whose right verdict the rulings fix.

Run this file alone to calibrate the judge without generating or grading anything
(~29 judge calls). See calibration.py for how the fixtures are built and judge.py for
what the judge is for.
"""

import pytest

from .calibration import (
    IDEAL_ACCEPTANCE_THRESHOLD,
    OVER_DETECTION_THRESHOLD,
    UNDER_DETECTION_THRESHOLD,
    calibration_fixtures,
    judge_fixture,
    judge_generated,
    rate,
)
from .rulings import QUESTION_TYPES


def _misses(kinds: set[str]) -> str:
    lines = []
    for f in calibration_fixtures():
        if f.kind not in kinds:
            continue
        j = judge_fixture(f.name)
        if f.hit(j):
            continue
        lines.append(f"  {f.name} ({f.basis})")
        for i, (point, check) in enumerate(zip(f.points, j.checks)):
            mark = "essential" if check.essential else "INESSENTIAL"
            planted = "  <- planted" if i == f.planted else ""
            lines.append(f"    [{mark}] {point}{planted}\n      {check.reasoning}")
        lines.append(f"    sufficient={j.sufficient} missing={list(j.missing)}")
    return "\n".join(lines)


def test_judge_accepts_handwritten_points() -> None:
    """The false-alarm side: points the rulings were made against must pass untouched."""
    hits, total = rate({"ideal"})
    assert hits / total >= IDEAL_ACCEPTANCE_THRESHOLD, (
        f"ideal acceptance {hits}/{total}:\n{_misses({'ideal'})}"
    )


def test_judge_flags_points_that_over_require() -> None:
    hits, total = rate({"padded", "bundled"})
    assert hits / total >= OVER_DETECTION_THRESHOLD, (
        f"over-requirement detection {hits}/{total}:\n{_misses({'padded', 'bundled'})}"
    )


def test_judge_flags_points_that_under_require() -> None:
    hits, total = rate({"thinned"})
    assert hits / total >= UNDER_DETECTION_THRESHOLD, (
        f"under-requirement detection {hits}/{total}:\n{_misses({'thinned'})}"
    )


@pytest.mark.parametrize("question_id", list(QUESTION_TYPES))
def test_judge_runs_on_generated_points(question_id: str) -> None:
    """Report-only: judges the generator's points so the terminal summary can set the
    judge's verdict beside what those points did to ruled answers.

    Nothing about agreement is asserted. A ruled answer can miss with sound points (an
    evaluator error), and the first run had over-requiring misses on only 2-3 of 10
    questions — too few positives for a rate to mean anything yet. judge_points()
    raising on a misaligned response is the only failure this can produce.
    """
    judge_generated(question_id)
