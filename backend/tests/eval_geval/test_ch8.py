"""Chapter 8 — Q10 (time of day clock vs monotonic clock).

See tests/geval_test_suite.md for question text, golden answers, and
G-Eval criteria this suite is built from.
"""

from .criteria import Q10_CLOCKS
from .support import assert_evaluator_judgment

_Q10_ID = "ddia:ch8-distributed-troubles:q1"
_Q10_CONCEPT_ID = "ddia:ch8-distributed-troubles"
_Q10_PROMPT = "Time of day clock vs monotonic clock."
_Q10_GOLDEN = (
    "A time of day clock returns the current date and time and is "
    "synchronized across machines via NTP. However it can jump forwards "
    "or backwards due to NTP adjustments, making it unreliable for "
    "measuring elapsed time. A monotonic clock only moves forward and is "
    "suitable for measuring durations such as timeouts or response times "
    "on a single machine. NTP can slew a monotonic clock — speeding it up "
    "or slowing it down slightly — but cannot cause it to jump, "
    "preserving the monotonic guarantee. Monotonic clock values are "
    "meaningless in absolute terms and cannot be compared across "
    "machines."
)


def test_ch8_clocks_clearly_correct() -> None:
    assert_evaluator_judgment(
        question_id=_Q10_ID,
        concept_id=_Q10_CONCEPT_ID,
        prompt=_Q10_PROMPT,
        golden_answer=_Q10_GOLDEN,
        student_answer=(
            "A time of day clock returns the current date and time and is "
            "synchronized across machines via NTP, but can jump forwards "
            "or backwards due to NTP adjustments making it unreliable for "
            "measuring elapsed time. A monotonic clock only moves forward "
            "and is used for measuring durations like timeouts on a "
            "single machine. NTP can slew a monotonic clock by speeding "
            "it up or slowing it down but cannot cause it to jump. "
            "Monotonic clock values cannot be compared across machines."
        ),
        metric_name="Clocks Judgment Quality",
        spec=Q10_CLOCKS,
    )


def test_ch8_clocks_partially_correct_missing_slewing_and_cross_machine() -> None:
    assert_evaluator_judgment(
        question_id=_Q10_ID,
        concept_id=_Q10_CONCEPT_ID,
        prompt=_Q10_PROMPT,
        golden_answer=_Q10_GOLDEN,
        student_answer=(
            "A time of day clock tells you the current time and is "
            "synchronized with NTP but can jump backwards. A monotonic "
            "clock only moves forward so it is safer for measuring "
            "elapsed time like timeouts."
        ),
        metric_name="Clocks Judgment Quality",
        spec=Q10_CLOCKS,
    )


def test_ch8_clocks_clearly_wrong_confuses_the_two() -> None:
    assert_evaluator_judgment(
        question_id=_Q10_ID,
        concept_id=_Q10_CONCEPT_ID,
        prompt=_Q10_PROMPT,
        golden_answer=_Q10_GOLDEN,
        student_answer=(
            "A time of day clock is the safer option because it is "
            "synchronized across machines via NTP, making it reliable for "
            "measuring elapsed time in distributed systems. A monotonic "
            "clock can jump forwards and backwards which makes it "
            "unreliable."
        ),
        metric_name="Clocks Judgment Quality",
        spec=Q10_CLOCKS,
    )


def test_ch8_clocks_partially_correct_missing_time_of_day_dangers() -> None:
    assert_evaluator_judgment(
        question_id=_Q10_ID,
        concept_id=_Q10_CONCEPT_ID,
        prompt=_Q10_PROMPT,
        golden_answer=_Q10_GOLDEN,
        student_answer=(
            "A monotonic clock is suitable for measuring durations like "
            "timeouts because it always moves forward. A time of day "
            "clock tells you the current date and time and is "
            "synchronized across machines via NTP."
        ),
        metric_name="Clocks Judgment Quality",
        spec=Q10_CLOCKS,
    )
