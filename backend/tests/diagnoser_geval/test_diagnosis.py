"""Case 3 — Storage Engines, diagnosed.

Eight hand-curated wrong answers (see golden.py), each engineered to trace to one specific
prerequisite gap. All five assertions share a single cached run of the diagnoser — see
support.py for what each tier checks and why.
"""

from .support import (
    ACCURACY_THRESHOLD,
    QUESTION_RELEVANCE_THRESHOLD,
    REASONING_QUALITY_THRESHOLD,
    score_all,
)


def test_invariants_hold() -> None:
    """Tier 1: no answer leaks, suspects reachable, questions well-formed, budget kept."""
    result = score_all()
    assert not result.invariant_violations, result.invariant_violations_message()


def test_never_diagnoses_a_forbidden_concept() -> None:
    """Tier 2, zero tolerance: several cases demonstrate mastery of a neighbouring concept,
    so naming it contradicts the evidence the model was given."""
    result = score_all()
    assert not result.forbidden_hits, result.forbidden_message()


def test_diagnostic_accuracy() -> None:
    """Tier 2: the core metric — did it land on a defensible suspect?"""
    result = score_all()
    assert result.accuracy >= ACCURACY_THRESHOLD, result.accuracy_message()


def test_does_not_spuriously_claim_the_gap_is_outside_the_graph() -> None:
    """The general-knowledge escape hatch discloses itself to the student, so it has to stay
    rare. Only the false-positive direction is asserted: a missed disclosure just leaves the
    old behavior, but a spurious one is noise that trains students to ignore the notice."""
    result = score_all()
    assert not result.spurious_disclosures, result.spurious_disclosures_message()


def test_targeted_questions_probe_their_suspect() -> None:
    """Tier 3: a correct suspect paired with an irrelevant question is still a failure."""
    result = score_all()
    assert result.question_relevance_rate >= QUESTION_RELEVANCE_THRESHOLD, (
        result.question_relevance_message()
    )


def test_reasoning_is_evidence_backed() -> None:
    """Tier 3: the certainty requirement made observable.

    The code gate can only enforce that the model *claimed* high confidence. Whether the
    claim was earned — whether the reasoning ties a specific stated deficiency to specific
    concept evidence rather than asserting something plausible — needs a judge.
    """
    result = score_all()
    assert result.reasoning_quality_rate >= REASONING_QUALITY_THRESHOLD, (
        result.reasoning_quality_message()
    )
