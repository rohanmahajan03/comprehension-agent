"""Hand-curated fixtures for the evidence_finder regression suite.

Design doc: docs/specs/2026-09-15-evidence-finder-test-strategy.md §4.

Three kinds of fixture, all built on Case 3 — Storage Engines from tests/graph_golden_set.md,
whose source text and concept set are imported from `tests/graph_geval/golden.py` rather than
restated, so a third suite cannot disagree with the other two about what the case contains.

1. **Span labels** (`_ANCHORS`) — for each concept, the regions of the chapter that are
   defensibly *about* that concept. This is what makes the suite's headline check possible
   without a judge: a returned quote is located in the chapter and tested for containment in
   its target's regions, turning "is this quote about the right concept?" into arithmetic.

2. **Negative concepts** (`ABSENT`) — plausible storage-engine ideas this chapter never
   teaches. `find_evidence` must return `found: false` for them.

3. **Edge pairs** (`LINKED_PAIRS` / `UNLINKED_PAIRS`) — for `find_edge_evidence`.

**Everything here is resolved and validated at import** (`_validate()`), so a fixture that has
drifted from the source text fails in milliseconds rather than after a billed run that then
measures the wrong thing.

## On labelling generously

A region marks text *defensibly* about a concept, not text exclusively about it. Where one
sentence genuinely serves two concepts it is labelled for both — the WAL/write-amplification
sentence ("must write every piece of data at least twice") is the clear case, since the chapter
introduces write amplification precisely by describing what the WAL costs.

That is deliberate. The check exists to catch a quote that is plainly about a *different*
concept, which is the failure mode ranked #1 in the design doc. Adjudicating genuinely
dual-purpose sentences is not its job, and a labelling scheme strict enough to do that would
generate false failures on defensible model output — the fastest way to get a suite ignored.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.text_match import normalize_ws
from tests.graph_geval.golden import CASE_3_STORAGE_ENGINES

CASE = CASE_3_STORAGE_ENGINES
SOURCE = CASE.source_text

# All span arithmetic happens in whitespace-normalized space. `text_match.is_verbatim()`
# forgives a rewrapped line, so a quote the service accepted may not appear literally in the
# raw text — normalizing both sides once is simpler and safer than mapping indices back
# through the original line breaks.
NORM_SOURCE = normalize_ws(SOURCE)

CONCEPT_LABELS = {c.id: c.label for c in CASE.concepts}


@dataclass(frozen=True)
class Region:
    """A half-open [start, end) span of NORM_SOURCE."""

    start: int
    end: int

    def contains(self, start: int, end: int) -> bool:
        return self.start <= start and end <= self.end


# concept id -> verbatim anchor strings delimiting the regions about that concept.
#
# Stored as text rather than integer offsets on purpose: offsets rot silently the moment
# anyone reflows a line in graph_golden_set.md, whereas an anchor that no longer matches fails
# loudly at import (_resolve below).
_ANCHORS: dict[str, list[str]] = {
    "append_only_log": [
        "Our db_set function has pretty good performance because appending to a file is "
        "generally very efficient. Many databases internally use a log, which is an "
        "append-only data file.",
    ],
    "hash_index": [
        "The simplest possible indexing strategy is this: keep an in-memory hash map where "
        "every key is mapped to a byte offset in the data file. Whenever you append a new "
        "key-value pair to the file, you also update the hash map to reflect the offset of "
        "the data you just wrote.",
        "The hash table index also has limitations: - The hash table must fit in memory. "
        "- Range queries are not efficient.",
    ],
    "log_segment": [
        "A good solution is to break the log into segments of a certain size by closing a "
        "segment file when it reaches a certain size, and making subsequent writes to a new "
        "segment file.",
    ],
    "compaction": [
        "We can then perform compaction on these segments. Compaction means throwing away "
        "duplicate keys in the log, and keeping only the most recent update for each key. "
        "Since compaction often makes segments much smaller, we can also merge several "
        "segments together at the same time as performing the compaction.",
        # Dual-purpose with sstable: the uniqueness guarantee is stated as something
        # compaction provides.
        "We also require that each key only appears once within each merged segment file "
        "(the compaction process already ensures that).",
    ],
    "sstable": [
        "Now we can make a simple change to the format of our segment files: we require that "
        "the sequence of key-value pairs is sorted by key. We call this format Sorted String "
        "Table, or SSTable for short. We also require that each key only appears once within "
        "each merged segment file (the compaction process already ensures that).",
    ],
    "memtable": [
        "When a write comes in, add it to an in-memory balanced tree data structure. This "
        "in-memory tree is sometimes called a memtable. When the memtable gets bigger than "
        "some threshold, write it out to disk as an SSTable file.",
    ],
    "lsm_tree": [
        "The algorithm described here is essentially what is used in LevelDB and RocksDB. "
        "Originally this indexing structure was described by Patrick O'Neil et al. under the "
        "name Log-Structured Merge-Tree (or LSM-Tree).",
        # The Bloom-filter section opens by stating an LSM-tree property, so a quote about the
        # slow-negative-lookup behaviour is defensibly about either concept. Labelled across
        # both sentences, not just the first: the first live run returned exactly this span for
        # lsm_tree and a one-sentence anchor scored it off-target under containment — a
        # labelling artifact, not a model error.
        "The LSM-tree algorithm can be slow when looking up keys that do not exist in the "
        "database. In order to optimize this kind of access, storage engines often use "
        "additional Bloom filters.",
        # The write path *is* the LSM-tree algorithm — the chapter explains the structure by
        # walking memtable → threshold → SSTable. Dual-labelled with memtable. Deliberately not
        # given to sstable: here an SSTable is only named as the destination, whereas the
        # SSTables section actually explains what one is.
        "When a write comes in, add it to an in-memory balanced tree data structure. This "
        "in-memory tree is sometimes called a memtable. When the memtable gets bigger than "
        "some threshold, write it out to disk as an SSTable file.",
        # Closing comparison — a claim about LSM-trees (and B-trees), labelled for nobody in
        # the first run, which is a gap in these fixtures rather than a wrong answer.
        "LSM-trees are typically faster for writes, whereas B-trees are thought to be faster "
        "for reads.",
    ],
    "bloom_filter": [
        "The LSM-tree algorithm can be slow when looking up keys that do not exist in the "
        "database. In order to optimize this kind of access, storage engines often use "
        "additional Bloom filters. A Bloom filter is a memory-efficient data structure for "
        "approximating the contents of a set. It can tell you if a key does not appear in "
        "the database, and thus saves many unnecessary disk reads.",
    ],
    "b_tree": [
        "The most widely used indexing structure is quite different: the B-tree. Like "
        "SSTables, B-trees keep key-value pairs sorted by key, which allows efficient "
        "key-value lookups and range queries. By contrast, B-trees break the database down "
        "into fixed-size blocks or pages, and read or write one page at a time.",
        # Same closing comparison, dual-labelled: it is a claim about both index families.
        "LSM-trees are typically faster for writes, whereas B-trees are thought to be faster "
        "for reads.",
    ],
    "write_ahead_log": [
        "In order to make the database resilient to crashes, it is common for B-tree "
        "implementations to include an additional data structure on disk: a write-ahead log "
        "(WAL, also known as a redo log). This is an append-only file to which every B-tree "
        "modification must be written before it can be applied to the pages of the tree "
        "itself.",
        # Dual-purpose with write_amplification — see the module docstring. The chapter
        # introduces amplification by describing what the WAL costs, so a quote here is
        # defensible for either.
        "A B-tree index must write every piece of data at least twice: once to the "
        "write-ahead log, and once to the tree page itself.",
    ],
    "write_amplification": [
        "A B-tree index must write every piece of data at least twice: once to the "
        "write-ahead log, and once to the tree page itself. Log-structured indexes also "
        "rewrite data multiple times due to repeated compaction and merging of SSTables. "
        "This effect—one write to the database resulting in multiple writes to the disk over "
        "the course of the database's lifetime—is known as write amplification.",
    ],
}

# Plausible storage-engine concepts this chapter never teaches. `find_evidence` must return
# found: false for each — the zero-tolerance check (design doc §2, failure #2).
#
# **Verified absent by substring search, not by intuition.** Case 3 covers more than its title
# suggests: B-trees, write-ahead logs, Bloom filters and write amplification are all in here,
# and an early draft of the design doc proposed `b_tree` as a negative, which is wrong.
# `_validate()` re-checks each term below on every import.
#
# These are also deliberately *adjacent* rather than absurd — several are concepts in other
# cases of the same golden set — so a model matching on subject area rather than content has
# something to fail on.
ABSENT: list[tuple[str, str, str]] = [
    (
        "replication",
        "Replication",
        "Keeping copies of the same data on several nodes so it survives node failure.",
    ),
    (
        "partitioning",
        "Partitioning",
        "Splitting a dataset across nodes so each record belongs to exactly one partition.",
    ),
    (
        "consensus",
        "Consensus",
        "An algorithm letting several nodes agree on a value despite failures.",
    ),
    (
        "secondary_index",
        "Secondary index",
        "An index on a non-primary attribute, allowing lookups by a field other than the key.",
    ),
    (
        "transaction",
        "Transaction",
        "A group of reads and writes executed as one atomic unit that either commits or aborts.",
    ),
    (
        "column_oriented_storage",
        "Column-oriented storage",
        "Storing all values from each column together rather than row by row.",
    ),
]

# Words that must not appear anywhere in the chapter for the corresponding ABSENT entry to be
# a fair negative. Checked at import.
_ABSENCE_MARKERS = {
    "replication": ["replicat"],
    "partitioning": ["partition", "shard"],
    "consensus": ["consensus"],
    "secondary_index": ["secondary index"],
    "transaction": ["transaction"],
    "column_oriented_storage": ["column"],
}

# Prerequisite pairs (prereq_id, concept_id) the chapter genuinely links, drawn from the
# golden edge set, restricted to those with a sentence that actually names both.
LINKED_PAIRS: list[tuple[str, str]] = [
    ("log_segment", "compaction"),
    ("memtable", "lsm_tree"),
    ("b_tree", "write_ahead_log"),
    ("append_only_log", "hash_index"),
]

# Pairs the chapter never connects. `find_edge_evidence` must return None — same
# precision-over-recall weighting as ABSENT: a fabricated edge quote reaches
# question_generator as a `prerequisite_link` passage, i.e. as source-text provenance.
UNLINKED_PAIRS: list[tuple[str, str]] = [
    ("bloom_filter", "append_only_log"),
    ("write_ahead_log", "hash_index"),
    ("memtable", "b_tree"),
]


def _resolve(anchor: str) -> Region:
    normalized = normalize_ws(anchor)
    start = NORM_SOURCE.find(normalized)
    if start == -1:
        raise AssertionError(
            f"anchor is not verbatim in the Case 3 source text: {anchor[:90]!r}"
        )
    if NORM_SOURCE.find(normalized, start + 1) != -1:
        # A non-unique anchor would resolve to an arbitrary one of its occurrences, making
        # span containment mean something different than intended.
        raise AssertionError(f"anchor appears more than once, so it is ambiguous: {anchor[:90]!r}")
    return Region(start, start + len(normalized))


SPANS: dict[str, list[Region]] = {
    concept_id: [_resolve(a) for a in anchors] for concept_id, anchors in _ANCHORS.items()
}


def locate(quote: str) -> tuple[int, int] | None:
    """Where `quote` sits in the normalized chapter, or None if it isn't there at all."""
    normalized = normalize_ws(quote)
    if not normalized:
        return None
    start = NORM_SOURCE.find(normalized)
    if start == -1:
        return None
    return start, start + len(normalized)


def is_on_target(concept_id: str, quote: str) -> bool:
    """Whether `quote` lies inside a region labelled for `concept_id`.

    Containment, not overlap: a quote that starts inside the target's region and runs on into a
    neighbour's is carrying material the target cannot claim, and that material is what the
    question generator would then be grounded in.
    """
    located = locate(quote)
    if located is None:
        return False
    start, end = located
    return any(region.contains(start, end) for region in SPANS.get(concept_id, []))


def _validate() -> None:
    """Fail at import on any fixture that has drifted from the source text or the golden set."""
    known = {c.id for c in CASE.concepts}

    unlabelled = known - set(_ANCHORS)
    assert not unlabelled, f"concepts with no span labels: {sorted(unlabelled)}"
    unknown = set(_ANCHORS) - known
    assert not unknown, f"span labels for concepts not in Case 3: {sorted(unknown)}"

    lowered = NORM_SOURCE.lower()
    for slug, _, _ in ABSENT:
        for marker in _ABSENCE_MARKERS[slug]:
            assert marker not in lowered, (
                f"negative fixture {slug!r} is not actually absent — the Case 3 text contains "
                f"{marker!r}. Negatives are per-chapter; re-verify before reusing them."
            )

    golden_edges = {(e.frm, e.to) for e in CASE.edges}
    for prereq, concept in LINKED_PAIRS:
        assert (prereq, concept) in golden_edges, (
            f"LINKED_PAIRS has {prereq} -> {concept}, which is not a golden Case 3 edge"
        )
    for prereq, concept in UNLINKED_PAIRS:
        assert (prereq, concept) not in golden_edges, (
            f"UNLINKED_PAIRS has {prereq} -> {concept}, which IS a golden Case 3 edge"
        )
        assert prereq in known and concept in known, "UNLINKED_PAIRS names an unknown concept"


_validate()
