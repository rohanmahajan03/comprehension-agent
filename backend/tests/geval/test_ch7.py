"""Chapter 7 — Q9 (what is ACID).

See tests/geval_test_suite.md for question text, golden answers, and
G-Eval criteria this suite is built from.
"""

from .criteria import Q9_ACID
from .support import assert_evaluator_judgment

_Q9_ID = "ddia:ch7-transactions:q1"
_Q9_CONCEPT_ID = "ddia:ch7-transactions"
_Q9_PROMPT = "What is ACID?"
_Q9_GOLDEN = (
    "ACID stands for Atomicity, Consistency, Isolation, and Durability. "
    "Atomicity means a transaction is never left in an intermediary state "
    "— either all writes in the transaction succeed or none do. "
    "Consistency means the database does not violate its invariants at "
    "any point. Isolation means concurrent transactions execute as if "
    "they were serial — they do not see each other's intermediate state. "
    "Durability means that once a transaction is committed, the data will "
    "not be lost even in the event of a fault."
)


def test_ch7_acid_clearly_correct() -> None:
    assert_evaluator_judgment(
        question_id=_Q9_ID,
        concept_id=_Q9_CONCEPT_ID,
        prompt=_Q9_PROMPT,
        golden_answer=_Q9_GOLDEN,
        student_answer=(
            "ACID stands for Atomicity, Consistency, Isolation, and "
            "Durability. Atomicity means all writes in a transaction "
            "succeed or none do. Consistency means the database never "
            "violates its invariants. Isolation means concurrent "
            "transactions don't see each other's intermediate state and "
            "execute as if they were serial. Durability means committed "
            "data is not lost even if the system crashes."
        ),
        metric_name="ACID Judgment Quality",
        spec=Q9_ACID,
    )


def test_ch7_acid_partially_correct_missing_durability() -> None:
    assert_evaluator_judgment(
        question_id=_Q9_ID,
        concept_id=_Q9_CONCEPT_ID,
        prompt=_Q9_PROMPT,
        golden_answer=_Q9_GOLDEN,
        student_answer=(
            "ACID stands for Atomicity, Consistency, Isolation, and "
            "Durability. Atomicity means all writes succeed or none do. "
            "Consistency means the database doesn't violate its "
            "invariants. Isolation means concurrent transactions don't "
            "interfere with each other. Durability is not something I "
            "remember clearly."
        ),
        metric_name="ACID Judgment Quality",
        spec=Q9_ACID,
    )


def test_ch7_acid_clearly_wrong_wrong_definitions() -> None:
    assert_evaluator_judgment(
        question_id=_Q9_ID,
        concept_id=_Q9_CONCEPT_ID,
        prompt=_Q9_PROMPT,
        golden_answer=_Q9_GOLDEN,
        student_answer=(
            "ACID stands for Atomicity, Consistency, Isolation, and "
            "Durability. Atomicity means the database processes one "
            "transaction at a time. Consistency means all replicas have "
            "the same data. Isolation means transactions are encrypted "
            "and secure. Durability means the database can recover from "
            "crashes."
        ),
        metric_name="ACID Judgment Quality",
        spec=Q9_ACID,
    )


def test_ch7_acid_partially_correct_vague_definitions() -> None:
    assert_evaluator_judgment(
        question_id=_Q9_ID,
        concept_id=_Q9_CONCEPT_ID,
        prompt=_Q9_PROMPT,
        golden_answer=_Q9_GOLDEN,
        student_answer=(
            "ACID means that databases handle transactions safely. "
            "Atomicity is all or nothing, consistency keeps the data "
            "correct, isolation keeps transactions separate, and "
            "durability means data is saved permanently."
        ),
        metric_name="ACID Judgment Quality",
        spec=Q9_ACID,
    )
