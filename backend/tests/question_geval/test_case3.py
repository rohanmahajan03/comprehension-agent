"""Case 3 — Storage Engines.

See tests/graph_golden_set.md for source text and tests/question_geval/golden.py for
the hand-curated evidence anchors and per-concept applicable question types this
suite is built from.
"""

from .support import EVIDENCE_BASIS_THRESHOLD, TYPE_RECALL_THRESHOLD, score_case


def test_case3_question_type_recall() -> None:
    result = score_case()
    assert result.type_recall >= TYPE_RECALL_THRESHOLD, result.missed_types_message()


def test_case3_grounding_is_faithful() -> None:
    result = score_case()
    assert not result.grounding_violations, result.grounding_violations_message()


def test_case3_questions_are_evidence_based() -> None:
    result = score_case()
    assert result.evidence_basis_rate >= EVIDENCE_BASIS_THRESHOLD, result.evidence_basis_message()
