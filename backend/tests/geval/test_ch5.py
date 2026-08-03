"""Chapter 5 — Q6 (replication lag / read-your-writes).

See tests/geval_test_suite.md for question text, golden answers, and
G-Eval criteria this suite is built from.
"""

from .criteria import Q6_REPLICATION_LAG
from .support import assert_evaluator_judgment

_Q6_ID = "ddia:ch5-replication:q1"
_Q6_CONCEPT_ID = "ddia:ch5-replication"
_Q6_PROMPT = (
    "Give an example where replication lag results in an issue when "
    "reading your own writes."
)
_Q6_GOLDEN = (
    "A user sees a question on a message board and replies with 'fine.' "
    "When they reload the page their reply appears to be gone. This is "
    "because the write went to the leader, but the subsequent read was "
    "served by a follower replica that had not yet caught up with the "
    "leader's replication lag. From the user's perspective they have lost "
    "their own write, even though it was successfully recorded on the "
    "leader."
)


def test_ch5_replication_lag_correct_message_board_scenario() -> None:
    assert_evaluator_judgment(
        question_id=_Q6_ID,
        concept_id=_Q6_CONCEPT_ID,
        prompt=_Q6_PROMPT,
        golden_answer=_Q6_GOLDEN,
        student_answer=(
            "A user posts a reply on a message board and immediately "
            "refreshes the page. Their reply is gone. This is because the "
            "write went to the leader but the read was served by a "
            "follower replica that hadn't yet caught up due to "
            "replication lag. The user appears to have lost their own "
            "write even though it was successfully recorded on the "
            "leader."
        ),
        metric_name="Replication Lag Judgment Quality",
        spec=Q6_REPLICATION_LAG,
    )


def test_ch5_replication_lag_correct_banking_scenario() -> None:
    assert_evaluator_judgment(
        question_id=_Q6_ID,
        concept_id=_Q6_CONCEPT_ID,
        prompt=_Q6_PROMPT,
        golden_answer=_Q6_GOLDEN,
        student_answer=(
            "A user transfers money from their checking account to their "
            "savings account and immediately checks their savings "
            "balance. The balance hasn't updated yet. This is because the "
            "write went to the leader but the subsequent read was served "
            "by a follower replica that hadn't yet caught up due to "
            "replication lag."
        ),
        metric_name="Replication Lag Judgment Quality",
        spec=Q6_REPLICATION_LAG,
    )


def test_ch5_replication_lag_partially_correct_right_scenario_wrong_mechanism() -> None:
    assert_evaluator_judgment(
        question_id=_Q6_ID,
        concept_id=_Q6_CONCEPT_ID,
        prompt=_Q6_PROMPT,
        golden_answer=_Q6_GOLDEN,
        student_answer=(
            "A user posts a reply on a message board and refreshes but "
            "the reply is gone. This is because of replication lag — the "
            "system hasn't synced yet so the user doesn't see their own "
            "write."
        ),
        metric_name="Replication Lag Judgment Quality",
        spec=Q6_REPLICATION_LAG,
    )


def test_ch5_replication_lag_clearly_wrong_quorum_rollback() -> None:
    assert_evaluator_judgment(
        question_id=_Q6_ID,
        concept_id=_Q6_CONCEPT_ID,
        prompt=_Q6_PROMPT,
        golden_answer=_Q6_GOLDEN,
        student_answer=(
            "A user posts a reply on a message board and refreshes but "
            "the reply is gone. This is because the database rolled back "
            "the transaction since it couldn't achieve a quorum of writes "
            "across all replicas."
        ),
        metric_name="Replication Lag Judgment Quality",
        spec=Q6_REPLICATION_LAG,
    )


def test_ch5_replication_lag_clearly_wrong_disk_crash() -> None:
    assert_evaluator_judgment(
        question_id=_Q6_ID,
        concept_id=_Q6_CONCEPT_ID,
        prompt=_Q6_PROMPT,
        golden_answer=_Q6_GOLDEN,
        student_answer=(
            "A user posts a reply on a message board but it is gone "
            "because the server crashed and lost the write before it "
            "could be persisted to disk."
        ),
        metric_name="Replication Lag Judgment Quality",
        spec=Q6_REPLICATION_LAG,
    )
