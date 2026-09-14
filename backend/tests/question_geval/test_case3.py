"""Case 3 — Storage Engines.

See tests/graph_golden_set.md for source text and tests/question_geval/golden.py for
the hand-curated evidence anchors and per-concept applicable question types this
suite is built from.
"""

from .support import (
    ANSWER_QUALITY_THRESHOLD,
    EVIDENCE_BASIS_THRESHOLD,
    TARGET_FOCUS_THRESHOLD,
    TYPE_RECALL_THRESHOLD,
    score_case,
)


def test_case3_question_type_recall() -> None:
    result = score_case()
    assert result.type_recall >= TYPE_RECALL_THRESHOLD, result.missed_types_message()


def test_case3_grounding_is_faithful() -> None:
    result = score_case()
    assert not result.grounding_violations, result.grounding_violations_message()


def test_case3_expected_answers_are_gradeable() -> None:
    result = score_case()
    assert not result.expected_answer_violations, result.expected_answer_violations_message()


def test_case3_expected_answers_answer_their_question() -> None:
    result = score_case()
    assert result.answer_quality_rate >= ANSWER_QUALITY_THRESHOLD, result.answer_quality_message()


def test_case3_questions_are_evidence_based() -> None:
    result = score_case()
    assert result.evidence_basis_rate >= EVIDENCE_BASIS_THRESHOLD, result.evidence_basis_message()


def test_case3_questions_assess_their_own_concept() -> None:
    """Prerequisites and siblings are sent as context, not as subject matter.

    A question on concept X whose correct answer is really a statement about prerequisite Y
    burns one of X's question slots testing nothing about X — and Y already has its own
    question set. It also corrupts pipeline 2: a wrong answer there is supposed to mean
    "the gap may be in X's prerequisites", which is the signal diagnoser.py reasons from.
    """
    result = score_case()
    assert result.target_focus_rate >= TARGET_FOCUS_THRESHOLD, result.target_focus_message()
