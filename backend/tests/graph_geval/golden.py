"""Hand-curated golden data for the graph_builder G-Eval-style regression suite.

Structured (not parsed) from tests/graph_golden_set.md's Expected Concepts / Expected
Edges / Tricky Cases tables — if you change expectations there, update this file too.
Source text is *not* duplicated here: it's read straight out of the markdown's fenced
code blocks, so it can never drift from what the evidence-verbatim check in support.py
validates against.

Only concept id/label and (from, to) edge pairs are encoded — golden *evidence* quotes
aren't needed here, since the evidence check validates the LLM's own quotes against the
source text, not against a golden quote.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_GOLDEN_MD = Path(__file__).resolve().parent.parent / "graph_golden_set.md"


@dataclass(frozen=True)
class GoldenConcept:
    id: str
    label: str


@dataclass(frozen=True)
class GoldenEdge:
    frm: str
    to: str


@dataclass(frozen=True)
class GoldenCase:
    name: str
    md_title: str
    concepts: list[GoldenConcept]
    edges: list[GoldenEdge]
    # Ideas the source text explicitly says should NOT become their own concept node
    # (aliases, anti-patterns, implementation details, cross-chapter mentions, etc).
    forbidden: list[str] = field(default_factory=list)

    @property
    def source_text(self) -> str:
        return _source_texts()[self.md_title]


@lru_cache
def _source_texts() -> dict[str, str]:
    """Map each case's markdown title to its fenced Source Text block."""
    content = _GOLDEN_MD.read_text(encoding="utf-8")
    parts = re.split(r"^## Case \d+ — (.+)$", content, flags=re.MULTILINE)
    texts: dict[str, str] = {}
    # parts[0] is the preamble before the first "## Case" heading; after that, titles
    # and bodies alternate.
    for title, body in zip(parts[1::2], parts[2::2]):
        match = re.search(r"```\n(.*?)\n```", body, flags=re.DOTALL)
        if match:
            texts[title.strip()] = match.group(1)
    return texts


CASE_1_PARTITIONING = GoldenCase(
    name="case1_partitioning",
    md_title="Partitioning",
    concepts=[
        GoldenConcept("partitioning", "Partitioning"),
        GoldenConcept("replication", "Replication"),
        GoldenConcept("skew", "Skew"),
        GoldenConcept("hot_spot", "Hot Spot"),
        GoldenConcept("key_range_partitioning", "Key Range Partitioning"),
        GoldenConcept("hash_partitioning", "Hash Partitioning"),
        GoldenConcept("secondary_index", "Secondary Index"),
        GoldenConcept("document_partitioned_index", "Document-Partitioned Index"),
        GoldenConcept("term_partitioned_index", "Term-Partitioned Index"),
        GoldenConcept("rebalancing", "Rebalancing"),
        GoldenConcept("fixed_partition_rebalancing", "Fixed Number of Partitions"),
        GoldenConcept("dynamic_partitioning", "Dynamic Partitioning"),
        GoldenConcept("proportional_partitioning", "Partitioning Proportional to Nodes"),
    ],
    edges=[
        GoldenEdge("partitioning", "skew"),
        GoldenEdge("skew", "hot_spot"),
        GoldenEdge("hot_spot", "key_range_partitioning"),
        GoldenEdge("hot_spot", "hash_partitioning"),
        GoldenEdge("key_range_partitioning", "hash_partitioning"),
        GoldenEdge("secondary_index", "document_partitioned_index"),
        GoldenEdge("secondary_index", "term_partitioned_index"),
        GoldenEdge("document_partitioned_index", "term_partitioned_index"),
        GoldenEdge("key_range_partitioning", "dynamic_partitioning"),
        GoldenEdge("hash_partitioning", "proportional_partitioning"),
        GoldenEdge("rebalancing", "fixed_partition_rebalancing"),
        GoldenEdge("rebalancing", "dynamic_partitioning"),
        GoldenEdge("rebalancing", "proportional_partitioning"),
    ],
    forbidden=[
        "Consistent hashing as a node separate from hash partitioning — the text "
        "explicitly says to call it hash partitioning instead and treat them as the "
        "same concept.",
        "hash mod N as a concept to learn — it is presented only as an anti-pattern.",
        "Scatter/gather as a standalone concept — it is a label for a consequence of "
        "document-partitioned reads and belongs folded into that concept's summary.",
        "Replication having any prerequisite edges to or from it — it is a "
        "cross-chapter reference (Ch5) that should appear only as a node.",
    ],
)

CASE_2_TRANSACTIONS_ACID = GoldenCase(
    name="case2_transactions_acid",
    md_title="Transactions and ACID",
    concepts=[
        GoldenConcept("transaction", "Transaction"),
        GoldenConcept("acid", "ACID"),
        GoldenConcept("atomicity", "Atomicity"),
        GoldenConcept("consistency_acid", "Consistency (ACID)"),
        GoldenConcept("isolation", "Isolation"),
        GoldenConcept("durability", "Durability"),
        GoldenConcept("multi_object_transaction", "Multi-Object Transaction"),
        GoldenConcept("single_object_operation", "Single-Object Operation"),
        GoldenConcept("race_condition", "Race Condition"),
        GoldenConcept("read_committed", "Read Committed"),
        GoldenConcept("dirty_read", "Dirty Read"),
        GoldenConcept("dirty_write", "Dirty Write"),
        GoldenConcept("read_skew", "Read Skew"),
        GoldenConcept("snapshot_isolation", "Snapshot Isolation"),
        GoldenConcept("mvcc", "Multi-Version Concurrency Control (MVCC)"),
    ],
    edges=[
        GoldenEdge("transaction", "acid"),
        GoldenEdge("acid", "atomicity"),
        GoldenEdge("acid", "consistency_acid"),
        GoldenEdge("acid", "isolation"),
        GoldenEdge("acid", "durability"),
        GoldenEdge("transaction", "multi_object_transaction"),
        GoldenEdge("atomicity", "multi_object_transaction"),
        GoldenEdge("isolation", "multi_object_transaction"),
        GoldenEdge("race_condition", "isolation"),
        GoldenEdge("isolation", "read_committed"),
        GoldenEdge("isolation", "snapshot_isolation"),
        GoldenEdge("read_committed", "dirty_read"),
        GoldenEdge("read_committed", "dirty_write"),
        GoldenEdge("read_committed", "read_skew"),
        GoldenEdge("read_skew", "snapshot_isolation"),
        GoldenEdge("snapshot_isolation", "mvcc"),
    ],
    forbidden=[
        "BASE as a concept to learn — mentioned once only as \"not ACID.\"",
        "Row-level locking as its own node — it is an implementation detail of read "
        "committed.",
        "Weak isolation as its own node separate from isolation — the text's "
        "boundary between the two is blurry, so isolation levels should wire "
        "directly to isolation.",
    ],
)

CASE_3_STORAGE_ENGINES = GoldenCase(
    name="case3_storage_engines",
    md_title="Storage Engines",
    concepts=[
        GoldenConcept("append_only_log", "Append-Only Log"),
        GoldenConcept("log_segment", "Segmentation"),
        GoldenConcept("hash_index", "Hash Index"),
        GoldenConcept("compaction", "Compaction"),
        GoldenConcept("sstable", "SSTable (Sorted String Table)"),
        GoldenConcept("memtable", "Memtable"),
        GoldenConcept("lsm_tree", "LSM-Tree (Log-Structured Merge-Tree)"),
        GoldenConcept("bloom_filter", "Bloom Filter"),
        GoldenConcept("b_tree", "B-Tree"),
        GoldenConcept("write_ahead_log", "Write-Ahead Log (WAL)"),
        GoldenConcept("write_amplification", "Write Amplification"),
    ],
    edges=[
        GoldenEdge("append_only_log", "hash_index"),
        GoldenEdge("append_only_log", "log_segment"),
        GoldenEdge("log_segment", "compaction"),
        GoldenEdge("log_segment", "sstable"),
        GoldenEdge("compaction", "sstable"),
        GoldenEdge("memtable", "lsm_tree"),
        GoldenEdge("sstable", "lsm_tree"),
        GoldenEdge("lsm_tree", "bloom_filter"),
        GoldenEdge("lsm_tree", "write_amplification"),
        GoldenEdge("b_tree", "write_ahead_log"),
        GoldenEdge("b_tree", "write_amplification"),
    ],
    forbidden=[
        "A general 'index' concept — specific index types are what matter; a "
        "generic umbrella node is inflation.",
        "Secondary index, clustered index, or covering index as their own nodes — "
        "touched on only briefly, not substantively explained.",
        "Sparse in-memory index as its own node — it is an implementation detail "
        "of SSTables.",
    ],
)

CASE_4_OLTP_OLAP = GoldenCase(
    name="case4_oltp_olap",
    md_title="OLTP, OLAP, and Data Warehousing",
    concepts=[
        GoldenConcept("oltp", "OLTP (Online Transaction Processing)"),
        GoldenConcept("olap", "OLAP (Online Analytic Processing)"),
        GoldenConcept("data_warehouse", "Data Warehouse"),
        GoldenConcept("etl", "ETL (Extract-Transform-Load)"),
        GoldenConcept("star_schema", "Star Schema"),
        GoldenConcept("snowflake_schema", "Snowflake Schema"),
        GoldenConcept("fact_table", "Fact Table"),
        GoldenConcept("dimension_table", "Dimension Table"),
        GoldenConcept("column_oriented_storage", "Column-Oriented Storage"),
        GoldenConcept("column_compression", "Column Compression"),
        GoldenConcept("materialized_view", "Materialized View"),
        GoldenConcept("data_cube", "Data Cube (OLAP Cube)"),
    ],
    edges=[
        GoldenEdge("oltp", "olap"),
        GoldenEdge("olap", "data_warehouse"),
        GoldenEdge("etl", "data_warehouse"),
        GoldenEdge("data_warehouse", "star_schema"),
        GoldenEdge("star_schema", "fact_table"),
        GoldenEdge("star_schema", "dimension_table"),
        GoldenEdge("fact_table", "dimension_table"),
        GoldenEdge("star_schema", "snowflake_schema"),
        GoldenEdge("data_warehouse", "column_oriented_storage"),
        GoldenEdge("column_oriented_storage", "column_compression"),
        GoldenEdge("data_warehouse", "materialized_view"),
        GoldenEdge("materialized_view", "data_cube"),
    ],
    forbidden=[
        "Row-oriented storage as its own node — mentioned only as a contrast to "
        "column-oriented storage, never taught on its own terms.",
        "Bitmap encoding as its own node — an implementation detail that belongs "
        "folded into column compression.",
    ],
)

ALL_CASES = [
    CASE_1_PARTITIONING,
    CASE_2_TRANSACTIONS_ACID,
    CASE_3_STORAGE_ENGINES,
    CASE_4_OLTP_OLAP,
]
CASES_BY_NAME = {case.name: case for case in ALL_CASES}
