"""Chapter 3 — Q4 (define indexing).

See tests/geval_test_suite.md for question text, golden answers, and
G-Eval criteria this suite is built from.
"""

from .criteria import Q4_INDEXING
from .support import assert_evaluator_judgment

_Q4_ID = "ddia:ch3-storage-retrieval:q1"
_Q4_CONCEPT_ID = "ddia:ch3-storage-retrieval"
_Q4_PROMPT = "Define indexing."
_Q4_GOLDEN = (
    "An index is a separate data structure that allows a database to "
    "locate data efficiently without scanning the entire dataset. Indexes "
    "speed up read queries but slow down writes, since the index must be "
    "updated every time data is written. The choice of what to index is a "
    "tradeoff that is left to the application developer."
)


def test_ch3_indexing_clearly_correct() -> None:
    assert_evaluator_judgment(
        question_id=_Q4_ID,
        concept_id=_Q4_CONCEPT_ID,
        prompt=_Q4_PROMPT,
        golden_answer=_Q4_GOLDEN,
        student_answer=(
            "An index is a separate data structure that helps a database "
            "locate data efficiently without scanning the entire dataset. "
            "The tradeoff is that indexes speed up reads but slow down "
            "writes since the index needs to be updated on every write. "
            "The developer chooses what to index based on their query "
            "patterns."
        ),
        metric_name="Indexing Judgment Quality",
        spec=Q4_INDEXING,
    )


def test_ch3_indexing_partially_correct_misses_tradeoff() -> None:
    assert_evaluator_judgment(
        question_id=_Q4_ID,
        concept_id=_Q4_CONCEPT_ID,
        prompt=_Q4_PROMPT,
        golden_answer=_Q4_GOLDEN,
        student_answer=(
            "An index is a data structure that makes querying a database "
            "faster by organizing data so it can be found without "
            "scanning everything."
        ),
        metric_name="Indexing Judgment Quality",
        spec=Q4_INDEXING,
    )


def test_ch3_indexing_clearly_wrong_conflates_sorting() -> None:
    assert_evaluator_judgment(
        question_id=_Q4_ID,
        concept_id=_Q4_CONCEPT_ID,
        prompt=_Q4_PROMPT,
        golden_answer=_Q4_GOLDEN,
        student_answer=(
            "An index is when you sort your database table alphabetically "
            "or numerically so that queries run faster."
        ),
        metric_name="Indexing Judgment Quality",
        spec=Q4_INDEXING,
    )


def test_ch3_indexing_correct_but_vague() -> None:
    assert_evaluator_judgment(
        question_id=_Q4_ID,
        concept_id=_Q4_CONCEPT_ID,
        prompt=_Q4_PROMPT,
        golden_answer=_Q4_GOLDEN,
        student_answer=(
            "An index helps a database find data faster. Without an index "
            "queries would be slow."
        ),
        metric_name="Indexing Judgment Quality",
        spec=Q4_INDEXING,
    )
