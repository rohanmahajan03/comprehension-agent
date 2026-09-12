"""Chapter 1 — Q1 (fault vs failure), Q2 (reliability violation).

See tests/geval_test_suite.md for question text, golden answers, and
G-Eval criteria this suite is built from.
"""

from .criteria import Q1_FAULT_VS_FAILURE, Q2_RELIABILITY_VIOLATION
from .support import assert_evaluator_judgment

# --- Q1: Differentiate fault vs failure -------------------------------------

_Q1_ID = "ddia:ch1-fault-tolerance:q1"
_Q1_CONCEPT_ID = "ddia:ch1-fault-tolerance"
_Q1_PROMPT = "Differentiate fault vs failure."
_Q1_GOLDEN = (
    "A fault is when an individual component of a system deviates from its "
    "specification. A failure is when the system as a whole stops providing "
    "the required service to the user. Faults are the cause; failures are "
    "the result. The goal of fault-tolerant systems is to prevent faults "
    "from escalating into failures."
)


def test_ch1_fault_vs_failure_clearly_correct() -> None:
    assert_evaluator_judgment(
        question_id=_Q1_ID,
        concept_id=_Q1_CONCEPT_ID,
        prompt=_Q1_PROMPT,
        golden_answer=_Q1_GOLDEN,
        student_answer=(
            "A fault is when an individual component deviates from its "
            "specification — for example a disk returning corrupted data. A "
            "failure is when the system as a whole stops providing its "
            "required service to the user. Faults are the cause and "
            "failures are the result, so fault-tolerant systems aim to "
            "prevent faults from escalating into failures."
        ),
        metric_name="Fault vs Failure Judgment Quality",
        spec=Q1_FAULT_VS_FAILURE,
    )


def test_ch1_fault_vs_failure_partially_correct_missing_causal_link() -> None:
    assert_evaluator_judgment(
        question_id=_Q1_ID,
        concept_id=_Q1_CONCEPT_ID,
        prompt=_Q1_PROMPT,
        golden_answer=_Q1_GOLDEN,
        student_answer=(
            "A fault is when a component in a system stops working "
            "correctly. A failure is when the entire system goes down. "
            "They are both bad things that can happen in a distributed "
            "system."
        ),
        metric_name="Fault vs Failure Judgment Quality",
        spec=Q1_FAULT_VS_FAILURE,
    )


def test_ch1_fault_vs_failure_clearly_wrong_conflates_fault_and_failure() -> None:
    assert_evaluator_judgment(
        question_id=_Q1_ID,
        concept_id=_Q1_CONCEPT_ID,
        prompt=_Q1_PROMPT,
        golden_answer=_Q1_GOLDEN,
        student_answer=(
            "A fault and a failure are the same thing — they both refer to "
            "when a system stops working and is unavailable to users."
        ),
        metric_name="Fault vs Failure Judgment Quality",
        spec=Q1_FAULT_VS_FAILURE,
    )


def test_ch1_fault_vs_failure_reversed_causal_direction() -> None:
    assert_evaluator_judgment(
        question_id=_Q1_ID,
        concept_id=_Q1_CONCEPT_ID,
        prompt=_Q1_PROMPT,
        golden_answer=_Q1_GOLDEN,
        student_answer=(
            "A fault is when the entire system crashes. A failure is when "
            "an individual component misbehaves. Failures cause faults, so "
            "we try to prevent failures from escalating into faults."
        ),
        metric_name="Fault vs Failure Judgment Quality",
        spec=Q1_FAULT_VS_FAILURE,
    )


# --- Q2: Given a system that goes down when one node fails, identify which
# of the big 3 properties is violated and why -------------------------------

_Q2_ID = "ddia:ch1-reliability:q1"
_Q2_CONCEPT_ID = "ddia:ch1-reliability"
_Q2_PROMPT = (
    "Given a system that goes down when one node fails, identify which of "
    "the big 3 properties is violated and why."
)
_Q2_GOLDEN = (
    "The property violated is reliability. A reliable system should "
    "continue to work correctly even in the face of hardware faults such "
    "as a node going down. If the entire system fails when a single node "
    "fails, it has no fault tolerance — meaning a single hardware fault "
    "escalates directly into a system-wide failure."
)


def test_ch1_reliability_violation_clearly_correct() -> None:
    assert_evaluator_judgment(
        question_id=_Q2_ID,
        concept_id=_Q2_CONCEPT_ID,
        prompt=_Q2_PROMPT,
        golden_answer=_Q2_GOLDEN,
        student_answer=(
            "The property violated is reliability. A reliable system "
            "should be able to tolerate individual node failures and "
            "continue serving requests. If the whole system goes down when "
            "one node fails, there is no fault tolerance and a single "
            "hardware fault escalates into a full system failure."
        ),
        metric_name="Reliability Violation Judgment Quality",
        spec=Q2_RELIABILITY_VIOLATION,
    )


def test_ch1_reliability_violation_partially_correct_weak_justification() -> None:
    assert_evaluator_judgment(
        question_id=_Q2_ID,
        concept_id=_Q2_CONCEPT_ID,
        prompt=_Q2_PROMPT,
        golden_answer=_Q2_GOLDEN,
        student_answer=(
            "Reliability is violated because the system went down. A "
            "reliable system should not go down."
        ),
        metric_name="Reliability Violation Judgment Quality",
        spec=Q2_RELIABILITY_VIOLATION,
    )


def test_ch1_reliability_violation_clearly_wrong_identifies_scalability() -> None:
    assert_evaluator_judgment(
        question_id=_Q2_ID,
        concept_id=_Q2_CONCEPT_ID,
        prompt=_Q2_PROMPT,
        golden_answer=_Q2_GOLDEN,
        student_answer=(
            "The property violated is scalability. The system cannot "
            "handle the load when a node goes down, which means it is not "
            "scaling properly to meet demand."
        ),
        metric_name="Reliability Violation Judgment Quality",
        spec=Q2_RELIABILITY_VIOLATION,
    )


def test_ch1_reliability_violation_correct_conclusion_wrong_justification() -> None:
    assert_evaluator_judgment(
        question_id=_Q2_ID,
        concept_id=_Q2_CONCEPT_ID,
        prompt=_Q2_PROMPT,
        golden_answer=_Q2_GOLDEN,
        student_answer=(
            "Reliability is violated because the system is not "
            "maintainable enough to recover from a node failure. The "
            "engineering team should have built better recovery mechanisms "
            "into the codebase."
        ),
        metric_name="Reliability Violation Judgment Quality",
        spec=Q2_RELIABILITY_VIOLATION,
    )
