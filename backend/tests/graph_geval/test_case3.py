"""Case 3 — Storage Engines.

See tests/graph_golden_set.md for source text, golden concepts/edges, and tricky
cases this suite is built from.
"""

from .golden import CASE_3_STORAGE_ENGINES
from .support import CONCEPT_RECALL_THRESHOLD, EDGE_RECALL_THRESHOLD, score_case

_CASE = CASE_3_STORAGE_ENGINES.name


def test_case3_finds_expected_concepts() -> None:
    result = score_case(_CASE)
    assert result.concept_recall >= CONCEPT_RECALL_THRESHOLD, result.missed_concepts_message()


def test_case3_avoids_forbidden_concepts() -> None:
    result = score_case(_CASE)
    assert not result.forbidden_hits, result.forbidden_hits_message()


def test_case3_finds_expected_edges() -> None:
    result = score_case(_CASE)
    assert result.edge_recall >= EDGE_RECALL_THRESHOLD, result.missed_edges_message()


def test_case3_edge_evidence_is_verbatim() -> None:
    result = score_case(_CASE)
    assert not result.evidence_violations, result.evidence_violations_message()
