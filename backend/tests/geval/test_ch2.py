"""Chapter 2 — Q3 (relational vs document model for many-to-many).

See tests/geval_test_suite.md for question text, golden answers, and
G-Eval criteria this suite is built from.
"""

from .criteria import Q3_RELATIONAL_VS_DOCUMENT
from .support import assert_evaluator_judgment

_Q3_ID = "ddia:ch2-data-models:q1"
_Q3_CONCEPT_ID = "ddia:ch2-data-models"
_Q3_PROMPT = (
    "Given a many-to-many relationship scenario with students and courses, "
    "identify whether document or relational model handles it better and "
    "why."
)
_Q3_GOLDEN = (
    "The relational model handles this better. Many-to-many relationships "
    "require joins — a student can be enrolled in many courses and a "
    "course can have many students. A relational database handles this "
    "naturally via a join table (e.g. an enrollments table with "
    "student_id and course_id). Document databases handle one-to-many "
    "relationships well via nesting, but struggle with many-to-many "
    "because they lack native join support, forcing you to either "
    "denormalize data or resolve references manually in application code."
)


def test_ch2_relational_vs_document_clearly_correct() -> None:
    assert_evaluator_judgment(
        question_id=_Q3_ID,
        concept_id=_Q3_CONCEPT_ID,
        prompt=_Q3_PROMPT,
        golden_answer=_Q3_GOLDEN,
        student_answer=(
            "Relational is better here. A student can enroll in many "
            "courses and a course can have many students — this is a "
            "many-to-many relationship that requires joins. A relational "
            "database handles this naturally with a join table like "
            "enrollments with student_id and course_id. Document databases "
            "struggle with this because they don't support joins natively, "
            "so you'd have to denormalize or resolve references in "
            "application code."
        ),
        metric_name="Relational vs Document Judgment Quality",
        spec=Q3_RELATIONAL_VS_DOCUMENT,
    )


def test_ch2_relational_vs_document_partially_correct_weak_justification() -> None:
    assert_evaluator_judgment(
        question_id=_Q3_ID,
        concept_id=_Q3_CONCEPT_ID,
        prompt=_Q3_PROMPT,
        golden_answer=_Q3_GOLDEN,
        student_answer=(
            "Relational is better because document databases are not good "
            "at relationships. Relational databases are designed for this "
            "kind of thing."
        ),
        metric_name="Relational vs Document Judgment Quality",
        spec=Q3_RELATIONAL_VS_DOCUMENT,
    )


def test_ch2_relational_vs_document_clearly_wrong_picks_document() -> None:
    assert_evaluator_judgment(
        question_id=_Q3_ID,
        concept_id=_Q3_CONCEPT_ID,
        prompt=_Q3_PROMPT,
        golden_answer=_Q3_GOLDEN,
        student_answer=(
            "Document is better here. You can nest the courses a student "
            "is enrolled in directly inside the student document, making "
            "it easy to retrieve all of a student's courses in one query."
        ),
        metric_name="Relational vs Document Judgment Quality",
        spec=Q3_RELATIONAL_VS_DOCUMENT,
    )


def test_ch2_relational_vs_document_correct_conclusion_wrong_justification() -> None:
    assert_evaluator_judgment(
        question_id=_Q3_ID,
        concept_id=_Q3_CONCEPT_ID,
        prompt=_Q3_PROMPT,
        golden_answer=_Q3_GOLDEN,
        student_answer=(
            "Relational is better because relational databases are faster "
            "and more scalable than document databases for this type of "
            "query."
        ),
        metric_name="Relational vs Document Judgment Quality",
        spec=Q3_RELATIONAL_VS_DOCUMENT,
    )
