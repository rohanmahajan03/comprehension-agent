"""The triage classifier against fixtures whose category is known (override_corpus/
calibration.py). ~13 Opus calls, no grading. Run alone with `-k triage`; deselect with
`-k "not triage"`. Each category is asserted separately so a classifier that always sides
with the student (or the grader) can't average its way past."""

from functools import lru_cache

import pytest

from tests.override_corpus.calibration import TRIAGE_THRESHOLD, calibration_fixtures, rates
from tests.override_corpus.triage import Proposal, propose


@lru_cache
def proposal_for(name: str) -> Proposal:
    fixture = next(f for f in calibration_fixtures() if f.name == name)
    return propose(fixture.snapshot)


def calibration_results() -> list:
    return [(f, proposal_for(f.name)) for f in calibration_fixtures()]


@pytest.mark.parametrize(
    "category", sorted({f.expected for f in calibration_fixtures()})
)
def test_triage_calibration(category: str) -> None:
    hit, n = rates(calibration_results())[category]
    misses = [
        f"  {f.name}: got {p.category} — {p.rationale}"
        for f, p in calibration_results()
        if f.expected == category and p.category != category
    ]
    assert hit / n >= TRIAGE_THRESHOLD, (
        f"{category}: {hit}/{n} below {TRIAGE_THRESHOLD}\n" + "\n".join(misses)
    )
