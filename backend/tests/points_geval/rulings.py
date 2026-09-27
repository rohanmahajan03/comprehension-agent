"""Ground truth for the required-points suite: the verdict each eval_geval answer must get.

Keyed by eval_geval test name, so the answers themselves are never copied here — see
support.collect_ruled_answers(). Verdicts follow the variant labels in
tests/geval_test_suite.md: "Clearly correct" and "Correct — …" are correct; everything
else is incorrect, including "Correct but vague" and "Correct conclusion, wrong
justification", which that file's criteria say must not get credit.

`EXPLICIT_RULINGS` marks the verdicts decided case by case during the leniency work
rather than read off a label. They are the borderline cases, and the reason this suite
exists: each one is a place where the generated points could set the bar too high or
too low.
"""

# The type question_generator would have given each question. Rule 10 treats types
# differently (every item is a point for enumeration_completeness; open-ended types state
# what any valid answer must show), so points can't be generated without one.
QUESTION_TYPES: dict[str, str] = {
    "ddia:ch1-fault-tolerance:q1": "conceptual_distinction",
    "ddia:ch1-reliability:q1": "applied_reasoning",
    "ddia:ch2-data-models:q1": "applied_reasoning",
    "ddia:ch3-storage-retrieval:q1": "conceptual_correctness",
    "ddia:ch4-encoding-evolution:q1": "conceptual_correctness",
    "ddia:ch5-replication:q1": "open_ended_example",
    "ddia:ch6-partitioning:q1": "applied_reasoning",
    "ddia:ch6-secondary-indexes:q1": "open_ended_example",
    "ddia:ch7-transactions:q1": "enumeration_completeness",
    "ddia:ch8-distributed-troubles:q1": "conceptual_distinction",
}

VERDICTS: dict[str, bool] = {
    # Q1 fault vs failure
    "test_ch1_fault_vs_failure_clearly_correct": True,
    "test_ch1_fault_vs_failure_partially_correct_missing_causal_link": False,
    "test_ch1_fault_vs_failure_clearly_wrong_conflates_fault_and_failure": False,
    "test_ch1_fault_vs_failure_reversed_causal_direction": False,
    # Q2 reliability violation
    "test_ch1_reliability_violation_clearly_correct": True,
    "test_ch1_reliability_violation_partially_correct_weak_justification": False,
    "test_ch1_reliability_violation_clearly_wrong_identifies_scalability": False,
    "test_ch1_reliability_violation_correct_conclusion_wrong_justification": False,
    # Q3 relational vs document
    "test_ch2_relational_vs_document_clearly_correct": True,
    "test_ch2_relational_vs_document_partially_correct_weak_justification": False,
    "test_ch2_relational_vs_document_clearly_wrong_picks_document": False,
    "test_ch2_relational_vs_document_correct_conclusion_wrong_justification": False,
    # Q4 indexing
    "test_ch3_indexing_clearly_correct": True,
    "test_ch3_indexing_partially_correct_misses_tradeoff": False,
    "test_ch3_indexing_clearly_wrong_conflates_sorting": False,
    "test_ch3_indexing_correct_but_vague": False,
    # Q5 async
    "test_ch4_async_clearly_correct_includes_sync": True,
    "test_ch4_async_partially_correct_missing_acknowledgement": False,
    "test_ch4_async_clearly_wrong_conflates_parallelism": False,
    "test_ch4_async_correct_but_vague": False,
    # Q6 replication lag
    "test_ch5_replication_lag_correct_message_board_scenario": True,
    "test_ch5_replication_lag_correct_banking_scenario": True,
    "test_ch5_replication_lag_correct_concise_mechanism": True,
    "test_ch5_replication_lag_clearly_wrong_quorum_rollback": False,
    "test_ch5_replication_lag_clearly_wrong_disk_crash": False,
    # Q7 partition hotspot
    "test_ch6_partition_hotspot_clearly_correct": True,
    "test_ch6_partition_hotspot_partially_correct_missing_why": False,
    "test_ch6_partition_hotspot_clearly_wrong_confuses_replication": False,
    "test_ch6_partition_hotspot_correct_conclusion_wrong_justification": False,
    # Q8 GSI layout
    "test_ch6_gsi_layout_clearly_correct_range_partitioned": True,
    "test_ch6_gsi_layout_correct_hash_partitioned_different_attribute": True,
    "test_ch6_gsi_layout_partially_correct_describes_local_index": False,
    "test_ch6_gsi_layout_clearly_wrong_confuses_sorting": False,
    "test_ch6_gsi_layout_partially_correct_missing_pointer_structure": False,
    # Q9 ACID
    "test_ch7_acid_clearly_correct": True,
    "test_ch7_acid_partially_correct_missing_durability": False,
    "test_ch7_acid_clearly_wrong_wrong_definitions": False,
    "test_ch7_acid_partially_correct_vague_definitions": False,
    # Q10 clocks
    "test_ch8_clocks_clearly_correct": True,
    "test_ch8_clocks_correct_omits_slewing_and_cross_machine": True,
    "test_ch8_clocks_clearly_wrong_confuses_the_two": False,
    "test_ch8_clocks_partially_correct_missing_time_of_day_dangers": False,
}

EXPLICIT_RULINGS: frozenset[str] = frozenset({
    # Correct: "they clearly understood", without the leader/follower detail.
    "test_ch5_replication_lag_correct_concise_mechanism",
    # Incorrect: "not specific enough".
    "test_ch7_acid_partially_correct_vague_definitions",
    # Correct: slewing and cross-machine comparison are elaboration.
    "test_ch8_clocks_correct_omits_slewing_and_cross_machine",
    # Incorrect: never says a time-of-day clock can jump.
    "test_ch8_clocks_partially_correct_missing_time_of_day_dangers",
})
