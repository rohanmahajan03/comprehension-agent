"""Hand-curated golden data for the question_generator regression suite.

Covers Case 3 — Storage Engines (see tests/graph_golden_set.md) end to end: all 11
concepts, wired into the same DependencyGraph shape `graph_builder.build_graph()`
would have produced (concept ids/labels/edges reused from
tests/graph_geval/golden.py so the two suites can't drift apart on what the graph
looks like), plus hand-written `summary`/`evidence` text and, per concept, the set of
question *types* (not specific question text) genuinely appropriate given that
concept's evidence.

Deliberately no reference question text: question_generator.py's own prompt (rule 3)
grants the model real freedom in framing and which types to use per concept, so
comparing generated wording against one hand-picked example conflates "different
from my example" with "wrong" — see conversation/PR history for the investigation
that motivated dropping it. What *is* checkable without picking a winner is whether
the generator explores the full space of types that genuinely fit each concept
(maximizing type coverage) rather than defaulting to the same one or two types
everywhere — GOLDEN_TYPES below is that per-concept ceiling, hand-derived by applying
question_generator.py's own appropriateness rule for each type to the Case 3 source
text (see the per-entry comments).

`summary`/`evidence` here play the role graph_builder's own LLM output would play in
production — they're what gets sent to question_generator as each concept's/
prerequisite's evidence anchor. They're deliberately close paraphrases of the source
text (not required to be verbatim, same as graph_builder's own concept summaries),
each drawn only from material actually in the Case 3 source text.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import Concept, DependencyGraph
from tests.graph_geval.golden import CASE_3_STORAGE_ENGINES

_DOC_ID = "case3"

# Shorthand for the type labels question_generator.py's schema constrains `type` to.
_CC = "conceptual_correctness"
_CD = "conceptual_distinction"
_EC = "enumeration_completeness"
_OE = "open_ended_example"
_AR = "applied_reasoning"


# concept_id -> (summary, {prereq_id: evidence_quote})
_CONCEPT_TEXT: dict[str, tuple[str, dict[str, str]]] = {
    "append_only_log": (
        "A log is an append-only data file: writes are handled by simply appending "
        "new key-value pairs to the end of the file, which is efficient because "
        "appending is a cheap operation compared to other kinds of writes.",
        {},
    ),
    "log_segment": (
        "To keep an ever-growing append-only log manageable, it is broken into "
        "segments by closing a segment file once it reaches a certain size and "
        "writing subsequent data to a new segment file.",
        {
            "append_only_log": (
                "A good solution is to break the log into segments of a certain size "
                "by closing a segment file when it reaches a certain size, and making "
                "subsequent writes to a new segment file."
            ),
        },
    ),
    "hash_index": (
        "The simplest indexing strategy keeps an in-memory hash map from every key "
        "to the byte offset of that key's most recent value in the data file, "
        "updated on every append; it requires the whole hash map to fit in memory "
        "and can't answer range queries efficiently.",
        {
            "append_only_log": (
                "the simplest possible indexing strategy is this: keep an in-memory "
                "hash map where every key is mapped to a byte offset in the data file"
            ),
        },
    ),
    "compaction": (
        "Compaction throws away duplicate keys across a log's segments, keeping "
        "only the most recent update for each key; compacted segments can also be "
        "merged together at the same time.",
        {
            "log_segment": (
                "We can then perform compaction on these segments. Compaction means "
                "throwing away duplicate keys in the log, and keeping only the most "
                "recent update for each key."
            ),
        },
    ),
    "sstable": (
        "An SSTable (Sorted String Table) is a segment file format that requires "
        "key-value pairs to be sorted by key and each key to appear at most once "
        "per merged segment, a property compaction already guarantees.",
        {
            "log_segment": (
                "we can make a simple change to the format of our segment files: we "
                "require that the sequence of key-value pairs is sorted by key"
            ),
            "compaction": (
                "We also require that each key only appears once within each merged "
                "segment file (the compaction process already ensures that)"
            ),
        },
    ),
    "memtable": (
        "When a write comes in, it's added to an in-memory sorted (balanced tree) "
        "data structure called a memtable; once the memtable grows past some "
        "threshold, it's written out to disk as a new SSTable file.",
        {},
    ),
    "lsm_tree": (
        "An LSM-Tree (Log-Structured Merge-Tree) is the overall indexing algorithm, "
        "used in LevelDB and RocksDB, that combines an in-memory memtable with "
        "on-disk SSTable files.",
        {
            "memtable": (
                "When a write comes in, add it to an in-memory balanced tree data "
                "structure. This in-memory tree is sometimes called a memtable. When "
                "the memtable gets bigger than some threshold, write it out to disk "
                "as an SSTable file."
            ),
            "sstable": (
                "Originally this indexing structure was described by Patrick O'Neil "
                "et al. under the name Log-Structured Merge-Tree (or LSM-Tree)."
            ),
        },
    ),
    "bloom_filter": (
        "A Bloom filter is a memory-efficient data structure that approximates the "
        "contents of a set; storage engines use one to quickly tell whether a key "
        "is definitely absent from the database, saving unnecessary disk reads on "
        "LSM-tree lookups of nonexistent keys.",
        {
            "lsm_tree": (
                "the LSM-tree algorithm can be slow when looking up keys that do not "
                "exist in the database. In order to optimize this kind of access, "
                "storage engines often use additional Bloom filters."
            ),
        },
    ),
    "b_tree": (
        "The B-tree is the most widely used indexing structure; unlike log-"
        "structured indexes, B-trees keep key-value pairs sorted by key but break "
        "the database down into fixed-size blocks or pages, reading or writing one "
        "page at a time.",
        {},
    ),
    "write_ahead_log": (
        "To make a database resilient to crashes, B-tree implementations commonly "
        "add a write-ahead log (WAL, or redo log): an append-only file that every "
        "B-tree modification must be written to before it's applied to the tree's "
        "own pages.",
        {
            "b_tree": (
                "it is common for B-tree implementations to include an additional "
                "data structure on disk: a write-ahead log (WAL, also known as a "
                "redo log)"
            ),
        },
    ),
    "write_amplification": (
        "Write amplification is the effect where one write to the database results "
        "in multiple physical writes to disk over the database's lifetime — for "
        "B-trees because each write goes to both the write-ahead log and the tree "
        "page, and for log-structured indexes because of repeated compaction and "
        "merging of SSTables.",
        {
            "lsm_tree": (
                "Log-structured indexes also rewrite data multiple times due to "
                "repeated compaction and merging of SSTables. This effect—one write "
                "to the database resulting in multiple writes to the disk over the "
                "course of the database's lifetime—is known as write amplification."
            ),
            "b_tree": (
                "A B-tree index must write every piece of data at least twice: once "
                "to the write-ahead log, and once to the tree page itself."
            ),
        },
    ),
}

# concept_id -> list of types genuinely appropriate for that concept's evidence.
# CC included everywhere (every concept here has a real explanatory summary). CD only
# where a prerequisite/sibling offers a meaningful, evidence-grounded contrast (roots
# — append_only_log, memtable, b_tree — get none, since _siblings_of() gives concepts
# with no depends_on no siblings either). EC only where the text gives an explicit
# bounded list (rare: just hash_index's two limitations, and sstable's two format
# requirements, both phrased with parallel "requires X... requires Y" structure). OE
# vs AR: picked whichever fits the concept's specific mechanic better rather than
# listing both wherever either is plausible (they overlap enough that forcing both
# everywhere would make the set uninformative) — OE where the text/mechanism is
# naturally walked through as a worked example, AR where there's a genuine
# cause-and-effect or tradeoff to reason through in a novel scenario.
GOLDEN_TYPES: dict[str, list[str]] = {
    "append_only_log": [_CC, _OE],  # OE: text gives a literal worked example (the two Bash functions)
    "log_segment": [_CC, _CD, _OE],  # CD vs sibling hash_index (both fix different append-only-log problems); OE: segment-fills-and-rolls-over is a natural walkthrough
    "hash_index": [_CC, _CD, _EC, _AR],  # CD vs sibling log_segment; EC: the two explicit limitations; AR: reasoning through an overwrite (old value stays in file, hash map points to newest)
    "compaction": [_CC, _CD, _OE],  # CD vs sibling sstable (dedup guarantee vs format requirement); OE: given segments with duplicate keys, walk through what compaction produces
    "sstable": [_CC, _CD, _EC],  # CD vs compaction (which already guarantees the uniqueness SSTable requires); EC: the two format requirements (sorted + unique-key-per-segment)
    "memtable": [_CC, _OE],  # OE: write-arrives-then-threshold-flush is a natural walkthrough
    "lsm_tree": [_CC, _CD, _AR],  # CD: memtable's role vs SSTable's role; AR: reasoning about a tuning tradeoff (e.g. threshold size)
    "bloom_filter": [_CC, _OE, _AR],  # no CD: not a meaningful contrast target for lsm_tree or write_amplification; OE: a lookup-with/without-filter example; AR: trusting a filter's absent/present answer
    "b_tree": [_CC, _AR],  # AR: page-based I/O has real cause-and-effect for lookup/range-query cost
    "write_ahead_log": [_CC, _CD, _AR],  # CD vs sibling write_amplification (crash-recovery purpose vs performance cost); AR: reasoning through a crash occurring before/after the WAL write
    "write_amplification": [_CC, _CD, _AR],  # CD: the two distinct causes (B-tree vs LSM-tree) is the strongest contrast in the case; AR: reasoning about how an index choice affects amplification
}


@dataclass(frozen=True)
class QuestionGoldenCase:
    name: str
    doc_id: str
    golden_types: dict[str, list[str]] = field(default_factory=dict)

    def build_graph(self) -> DependencyGraph:
        """Build the DependencyGraph fed to question_generator, in the same shape
        graph_builder.build_graph() would have produced for Case 3: namespaced ids,
        depends_on/evidence folded per concept.
        """
        concepts = []
        edges_seen: set[tuple[str, str]] = set()
        for gc in CASE_3_STORAGE_ENGINES.concepts:
            summary, dep_evidence = _CONCEPT_TEXT[gc.id]
            edges_seen.update((dep, gc.id) for dep in dep_evidence)
            concepts.append(
                Concept(
                    id=f"{self.doc_id}:{gc.id}",
                    name=gc.label,
                    summary=summary,
                    depends_on=[f"{self.doc_id}:{dep}" for dep in dep_evidence],
                    evidence={f"{self.doc_id}:{dep}": quote for dep, quote in dep_evidence.items()},
                )
            )
        # Guard against this file's hand-encoded dependency structure drifting from
        # graph_geval's golden edges for the same case.
        expected_edges = {(e.frm, e.to) for e in CASE_3_STORAGE_ENGINES.edges}
        assert edges_seen == expected_edges, (
            "question_geval golden._CONCEPT_TEXT has drifted from graph_geval "
            f"CASE_3_STORAGE_ENGINES.edges: only here={edges_seen - expected_edges}, "
            f"only there={expected_edges - edges_seen}"
        )
        return DependencyGraph(doc_id=self.doc_id, concepts=concepts)


CASE_3_QUESTIONS = QuestionGoldenCase(
    name="case3_storage_engines",
    doc_id=_DOC_ID,
    golden_types=GOLDEN_TYPES,
)
