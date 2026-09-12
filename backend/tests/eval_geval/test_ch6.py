"""Chapter 6 — Q7 (partition hotspot), Q8 (GSI node layout).

See tests/geval_test_suite.md for question text, golden answers, and
G-Eval criteria this suite is built from.
"""

from .criteria import Q7_PARTITION_HOTSPOT, Q8_GSI_LAYOUT
from .support import assert_evaluator_judgment

# --- Q7: Twitter-like system partitioned by user_id, celebrity hotspot -----

_Q7_ID = "ddia:ch6-partitioning:q1"
_Q7_CONCEPT_ID = "ddia:ch6-partitioning"
_Q7_PROMPT = (
    "Given a Twitter-like system partitioned by user_id, explain what "
    "issue arises when a celebrity with 10 million followers posts a "
    "tweet that receives a high volume of interactions."
)
_Q7_GOLDEN = (
    "When a celebrity with a large following posts a tweet, all "
    "interactions with that tweet map to the same partition since the "
    "system is partitioned by user_id. That partition receives a "
    "disproportionately high volume of requests compared to all other "
    "partitions, becoming a hotspot. The load is not evenly distributed "
    "because one key generates far more traffic than others."
)


def test_ch6_partition_hotspot_clearly_correct() -> None:
    assert_evaluator_judgment(
        question_id=_Q7_ID,
        concept_id=_Q7_CONCEPT_ID,
        prompt=_Q7_PROMPT,
        golden_answer=_Q7_GOLDEN,
        student_answer=(
            "Since the system is partitioned by user_id, all interactions "
            "with the celebrity's tweet map to the same partition. That "
            "partition gets overwhelmed with requests while all other "
            "partitions sit idle. The load is uneven because one key "
            "generates far more traffic than the others, creating a "
            "hotspot."
        ),
        metric_name="Partition Hotspot Judgment Quality",
        spec=Q7_PARTITION_HOTSPOT,
    )


def test_ch6_partition_hotspot_partially_correct_missing_why() -> None:
    assert_evaluator_judgment(
        question_id=_Q7_ID,
        concept_id=_Q7_CONCEPT_ID,
        prompt=_Q7_PROMPT,
        golden_answer=_Q7_GOLDEN,
        student_answer=(
            "The celebrity's partition becomes a hotspot because too many "
            "people are interacting with their tweet at once. This causes "
            "performance issues."
        ),
        metric_name="Partition Hotspot Judgment Quality",
        spec=Q7_PARTITION_HOTSPOT,
    )


def test_ch6_partition_hotspot_clearly_wrong_confuses_replication() -> None:
    assert_evaluator_judgment(
        question_id=_Q7_ID,
        concept_id=_Q7_CONCEPT_ID,
        prompt=_Q7_PROMPT,
        golden_answer=_Q7_GOLDEN,
        student_answer=(
            "The issue is that the celebrity's tweet needs to be "
            "replicated to 10 million followers' feeds simultaneously, "
            "overwhelming the replication pipeline."
        ),
        metric_name="Partition Hotspot Judgment Quality",
        spec=Q7_PARTITION_HOTSPOT,
    )


def test_ch6_partition_hotspot_correct_conclusion_wrong_justification() -> None:
    assert_evaluator_judgment(
        question_id=_Q7_ID,
        concept_id=_Q7_CONCEPT_ID,
        prompt=_Q7_PROMPT,
        golden_answer=_Q7_GOLDEN,
        student_answer=(
            "The partition becomes a hotspot because the system is not "
            "using consistent hashing, which would distribute the "
            "celebrity's interactions evenly across all partitions."
        ),
        metric_name="Partition Hotspot Judgment Quality",
        spec=Q7_PARTITION_HOTSPOT,
    )


# --- Q8: Example node layout partitioned on both primary key and GSI -------

_Q8_ID = "ddia:ch6-secondary-indexes:q1"
_Q8_CONCEPT_ID = "ddia:ch6-secondary-indexes"
_Q8_PROMPT = "Give an example node layout partitioned on both primary key and GSI."
_Q8_GOLDEN = (
    "A system partitioned by user_id might have node A holding user_ids "
    "1-1000 and node B holding user_ids 1001-2000. A GSI on "
    "favorite_color is partitioned independently — node C might hold all "
    "GSI entries for favorite_color = 'blue', which stores the user_ids "
    "of all users whose favorite color is blue regardless of which "
    "primary key partition they belong to. To retrieve the full records, "
    "those user_ids are then looked up in their respective primary key "
    "partitions on node A or node B."
)


def test_ch6_gsi_layout_clearly_correct_range_partitioned() -> None:
    assert_evaluator_judgment(
        question_id=_Q8_ID,
        concept_id=_Q8_CONCEPT_ID,
        prompt=_Q8_PROMPT,
        golden_answer=_Q8_GOLDEN,
        student_answer=(
            "A system partitioned by user_id has node A holding user_ids "
            "1-1000 and node B holding user_ids 1001-2000. A GSI on "
            "favorite_color is partitioned independently on node C, "
            "storing user_ids for all users whose favorite color is blue "
            "regardless of which primary key partition they belong to. To "
            "get the full record you look up those user_ids in their "
            "respective primary key partitions."
        ),
        metric_name="GSI Layout Judgment Quality",
        spec=Q8_GSI_LAYOUT,
    )


def test_ch6_gsi_layout_correct_hash_partitioned_different_attribute() -> None:
    assert_evaluator_judgment(
        question_id=_Q8_ID,
        concept_id=_Q8_CONCEPT_ID,
        prompt=_Q8_PROMPT,
        golden_answer=_Q8_GOLDEN,
        student_answer=(
            "A system uses hash partitioning on user_id, so user records "
            "are distributed across nodes A, B, and C based on a hash "
            "function rather than contiguous ranges. A GSI on "
            "favorite_food is partitioned independently on node D, "
            "storing user_ids for all users whose favorite food is pizza "
            "regardless of which node their primary key record lives on. "
            "To retrieve full records, those user_ids are hashed to find "
            "which node holds the primary key partition."
        ),
        metric_name="GSI Layout Judgment Quality",
        spec=Q8_GSI_LAYOUT,
    )


def test_ch6_gsi_layout_partially_correct_describes_local_index() -> None:
    assert_evaluator_judgment(
        question_id=_Q8_ID,
        concept_id=_Q8_CONCEPT_ID,
        prompt=_Q8_PROMPT,
        golden_answer=_Q8_GOLDEN,
        student_answer=(
            "Node A holds user_ids 1-1000 and node B holds user_ids "
            "1001-2000. Each node also stores a local index on "
            "favorite_color for the user_ids it contains, so node A has a "
            "favorite_color index for user_ids 1-1000 and node B has one "
            "for user_ids 1001-2000."
        ),
        metric_name="GSI Layout Judgment Quality",
        spec=Q8_GSI_LAYOUT,
    )


def test_ch6_gsi_layout_clearly_wrong_confuses_sorting() -> None:
    assert_evaluator_judgment(
        question_id=_Q8_ID,
        concept_id=_Q8_CONCEPT_ID,
        prompt=_Q8_PROMPT,
        golden_answer=_Q8_GOLDEN,
        student_answer=(
            "Node A holds user_ids 1-1000 sorted by favorite_color so "
            "that queries on favorite_color can be resolved without "
            "scanning the entire partition."
        ),
        metric_name="GSI Layout Judgment Quality",
        spec=Q8_GSI_LAYOUT,
    )


def test_ch6_gsi_layout_partially_correct_missing_pointer_structure() -> None:
    assert_evaluator_judgment(
        question_id=_Q8_ID,
        concept_id=_Q8_CONCEPT_ID,
        prompt=_Q8_PROMPT,
        golden_answer=_Q8_GOLDEN,
        student_answer=(
            "Node C holds all records where favorite_color = 'blue' "
            "copied directly from the primary key partitions, so a query "
            "on favorite_color can be resolved entirely from node C "
            "without touching node A or node B."
        ),
        metric_name="GSI Layout Judgment Quality",
        spec=Q8_GSI_LAYOUT,
    )
