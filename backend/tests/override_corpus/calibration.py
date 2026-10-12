"""Calibration fixtures for the triage classifier: disputes whose right category is known.

Same discipline as tests/points_geval/calibration.py, and built from the same material —
eval_geval's answers, its handwritten points, and the rulings — so every expected category
traces back to a ruling rather than to a judgement made here:

- **points_overreach** — the points carry an idea the rulings make optional (points_geval's
  padded and bundled perturbations, reused by name), and the disputing answer is a
  ruled-correct one that omits it. The student is right, and only the bar is wrong.
- **paraphrase_missed** — the handwritten points unchanged, a ruled-correct answer, and a
  grader explanation claiming one point is missing. The bar is fine; the grader misread.
- **override_invalid** — the handwritten points unchanged and a ruled-*incorrect* answer,
  with a confident student note. The grader was right.

The overreach and paraphrase fixtures deliberately reuse answers (the concise
replication-lag one appears in both): with the answer held fixed, only the points tell the
two categories apart, so a classifier reading the student's note or the answer's tone
can't pass both. Each category guards the others against a degenerate classifier — one
that always sides with the student fails override_invalid, one that always sides with the
grader fails the rest. Rates are reported per category, never combined.

The grader explanations are written here, in the evaluator's register, since the fixtures
need a grade that disagrees with the ruling and the real evaluator mostly doesn't.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

from tests.points_geval.calibration import _BUNDLINGS, _PADDINGS
from tests.points_geval.rulings import VERDICTS
from tests.points_geval.support import RuledAnswer, collect_ruled_answers

#: Proposals are always reviewed by a human, so this only has to screen out a classifier
#: too skewed to save review time. Loose for the same reason as the points judge's: three
#: to five fixtures per category, so one flip moves a rate by 0.2 or more.
TRIAGE_THRESHOLD = 0.6


@dataclass(frozen=True)
class TriageFixture:
    name: str
    expected: str  # the category the classifier must pick
    snapshot: dict  # the shape triage.snapshot_from_override() produces
    basis: str
    question_type: str  # from rulings.QUESTION_TYPES — what the reviewer would confirm


def _answer(name: str) -> RuledAnswer:
    return next(a for a in collect_ruled_answers() if a.name == name)


def _snapshot(name: str, answer: RuledAnswer, points, explanation: str, note: str | None):
    return {
        "key": f"cal-{name}",
        "concept": answer.question_id.rsplit(":", 2)[-2],
        "question_kind": "pipeline1",
        "question_prompt": answer.prompt,
        "expected_answer_notes": answer.model_answer,
        "required_points": list(points),
        "student_answer": answer.student_answer,
        "student_note": note,
        "evaluator_explanation": explanation,
        "evaluator_model": "claude-haiku-4-5",
    }


def _require_ruling(name: str, expected: bool) -> None:
    if VERDICTS.get(name) is not expected:
        raise AssertionError(
            f"triage calibration cites {name} as ruled {expected}, rulings.py says "
            f"{VERDICTS.get(name)}"
        )


def _missing(point: str) -> str:
    return f'The answer does not express the required point: "{point}" Marked incorrect.'


# (fixture name, ruled-incorrect answer, the point the grader names, the student's note)
_INVALID = (
    ("fault_missing_causal_link",
     "test_ch1_fault_vs_failure_partially_correct_missing_causal_link", 2,
     "I defined both terms, which is what the question asked."),
    ("acid_missing_durability",
     "test_ch7_acid_partially_correct_missing_durability", 3,
     "I got three of the four and named all of them."),
    ("replication_lag_quorum_rollback",
     "test_ch5_replication_lag_clearly_wrong_quorum_rollback", 1,
     "My scenario is a valid example of a write going missing."),
    ("async_missing_acknowledgement",
     "test_ch4_async_partially_correct_missing_acknowledgement", 0,
     "This is exactly what async means."),
)

# (fixture name, ruled-correct answer, the point the grader wrongly says is missing, note)
_PARAPHRASE = (
    ("replication_lag_concise_mechanism",
     "test_ch5_replication_lag_correct_concise_mechanism", 1, None),
    ("replication_lag_banking_balance",
     "test_ch5_replication_lag_correct_banking_scenario", 1,
     "The balance not updating IS the write appearing missing."),
    ("gsi_hash_user_ids",
     "test_ch6_gsi_layout_correct_hash_partitioned_different_attribute", 2,
     "It stores user_ids, which are the primary keys."),
    ("clocks_elapsed_time",
     "test_ch8_clocks_correct_omits_slewing_and_cross_machine", 0, None),
)

_OVERREACH_NOTES = {
    "replication_lag_plus_leader_recorded": "The question didn't ask about the leader.",
    "clocks_monotonic_bundles_slewing": None,
}


@lru_cache
def calibration_fixtures() -> tuple[TriageFixture, ...]:
    fixtures: list[TriageFixture] = []

    for pad in _PADDINGS:
        if pad.omitted_by is None:
            continue  # without a ruled-correct answer omitting it, no dispute to build
        _require_ruling(pad.omitted_by, True)
        answer = _answer(pad.omitted_by)
        points = (*answer.handwritten_points, pad.point)
        fixtures.append(TriageFixture(
            pad.name, "points_overreach",
            _snapshot(pad.name, answer, points, _missing(pad.point),
                      _OVERREACH_NOTES.get(pad.name)),
            f"padded: {pad.basis}",
            answer.question_type,
        ))

    for bundle in _BUNDLINGS:
        if bundle.omitted_by is None:
            continue
        _require_ruling(bundle.omitted_by, True)
        answer = _answer(bundle.omitted_by)
        points = list(answer.handwritten_points)
        points[bundle.index] = bundle.point
        fixtures.append(TriageFixture(
            bundle.name, "points_overreach",
            _snapshot(bundle.name, answer, points, _missing(bundle.point),
                      _OVERREACH_NOTES.get(bundle.name)),
            f"bundled: {bundle.basis}",
            answer.question_type,
        ))

    for name, source, index, note in _PARAPHRASE:
        _require_ruling(source, True)
        answer = _answer(source)
        point = answer.handwritten_points[index]
        fixtures.append(TriageFixture(
            name, "paraphrase_missed",
            _snapshot(name, answer, answer.handwritten_points, _missing(point), note),
            f"ruled correct against unchanged points; the grader named point {index + 1}",
            answer.question_type,
        ))

    for name, source, index, note in _INVALID:
        _require_ruling(source, False)
        answer = _answer(source)
        point = answer.handwritten_points[index]
        fixtures.append(TriageFixture(
            name, "override_invalid",
            _snapshot(name, answer, answer.handwritten_points, _missing(point), note),
            "ruled incorrect against unchanged points",
            answer.question_type,
        ))

    return tuple(fixtures)


def rates(results) -> dict[str, tuple[int, int]]:
    """{expected category: (hits, fixtures)} from (fixture, proposal) pairs."""
    tally: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for fixture, proposal in results:
        tally[fixture.expected][1] += 1
        tally[fixture.expected][0] += proposal.category == fixture.expected
    return {k: (hit, n) for k, (hit, n) in tally.items()}
