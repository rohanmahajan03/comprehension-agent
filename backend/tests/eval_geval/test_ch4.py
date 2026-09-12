"""Chapter 4 — Q5 (what does async actually mean).

See tests/geval_test_suite.md for question text, golden answers, and
G-Eval criteria this suite is built from.
"""

from .criteria import Q5_ASYNC
from .support import assert_evaluator_judgment

_Q5_ID = "ddia:ch4-encoding-evolution:q1"
_Q5_CONCEPT_ID = "ddia:ch4-encoding-evolution"
_Q5_PROMPT = "What does async actually mean?"
_Q5_GOLDEN = (
    "Async means that when a request is made, control returns to the "
    "caller as soon as the request is acknowledged rather than waiting "
    "for processing to complete. The work happens in the background and "
    "the caller has no guarantee about when it will finish."
)


def test_ch4_async_clearly_correct_includes_sync() -> None:
    assert_evaluator_judgment(
        question_id=_Q5_ID,
        concept_id=_Q5_CONCEPT_ID,
        prompt=_Q5_PROMPT,
        golden_answer=_Q5_GOLDEN,
        student_answer=(
            "Async means that when a request is made, control returns to "
            "the caller immediately after the request is acknowledged, "
            "without waiting for the processing to complete. The work "
            "happens in the background and the caller has no guarantee "
            "about when it will finish. This is in contrast to "
            "synchronous processing where the caller blocks until the "
            "operation is complete."
        ),
        metric_name="Async Definition Judgment Quality",
        spec=Q5_ASYNC,
    )


def test_ch4_async_partially_correct_missing_acknowledgement() -> None:
    assert_evaluator_judgment(
        question_id=_Q5_ID,
        concept_id=_Q5_CONCEPT_ID,
        prompt=_Q5_PROMPT,
        golden_answer=_Q5_GOLDEN,
        student_answer=(
            "Async means that work happens in the background so the "
            "caller doesn't have to wait. This makes systems faster."
        ),
        metric_name="Async Definition Judgment Quality",
        spec=Q5_ASYNC,
    )


def test_ch4_async_clearly_wrong_conflates_parallelism() -> None:
    assert_evaluator_judgment(
        question_id=_Q5_ID,
        concept_id=_Q5_CONCEPT_ID,
        prompt=_Q5_PROMPT,
        golden_answer=_Q5_GOLDEN,
        student_answer=(
            "Async means that multiple requests are processed at the same "
            "time in parallel, allowing the system to handle more load."
        ),
        metric_name="Async Definition Judgment Quality",
        spec=Q5_ASYNC,
    )


def test_ch4_async_correct_but_vague() -> None:
    assert_evaluator_judgment(
        question_id=_Q5_ID,
        concept_id=_Q5_CONCEPT_ID,
        prompt=_Q5_PROMPT,
        golden_answer=_Q5_GOLDEN,
        student_answer=(
            "Async means things happen without blocking. The caller "
            "doesn't have to wait for the response."
        ),
        metric_name="Async Definition Judgment Quality",
        spec=Q5_ASYNC,
    )
