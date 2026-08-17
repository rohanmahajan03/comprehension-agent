"""Hand-curated diagnosis cases for the diagnoser regression suite.

Each case is a student answer engineered to be wrong in a way that traces to ONE specific
prerequisite gap, paired with the concepts a correct diagnosis may name.

Two things about the shape are deliberate:

**`acceptable_suspects` is a set, not a single answer.** Unlike graph_geval (concepts are
objectively present in the source text) or question_geval (`type` is a closed vocabulary),
"this misunderstanding stems from concept X" is interpretive, and more than one answer is
often defensible — a gap on `sstable` can reasonably be pinned on `compaction` or on
`log_segment`. Asserting one right answer would fail the diagnoser for being
differently-reasonable, the same mistake question_geval made with per-question similarity
before dropping it. `preferred_suspect` records the sharpest answer for reporting; it is
not asserted.

**`forbidden_suspects` carries most of the discriminating power.** For several cases the
student answer demonstrates mastery of a neighbouring concept — case 6 explains B-tree
write amplification perfectly and omits the log-structured half entirely — so diagnosing
that concept is not merely suboptimal, it contradicts the evidence in front of the model.
Those are asserted at zero tolerance.

`evaluation_explanation` is hand-written in `evaluator.py`'s voice rather than produced by
running the real evaluator. Chaining the two services would make an evaluator regression
and a diagnoser regression indistinguishable; `tests/geval` makes the same choice by
hand-writing `golden_answer`. The tradeoff is that these may be cleaner than production
explanations — see the design proposal's open questions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import DependencyGraph, Question
from tests.question_geval.golden import CASE_3_QUESTIONS

DOC_ID = CASE_3_QUESTIONS.doc_id


def _cid(slug: str) -> str:
    return f"{DOC_ID}:{slug}"


# One plausible pipeline-1 question per concept, in the shape question_generator produces
# (prose model answer passed through verbatim as expected_answer_notes). Without these the
# graph has no questions, `pull_question_from_storage` can never match, and the reuse half
# of the diagnoser's tool surface would go untested.
_PIPELINE_1_QUESTIONS: dict[str, tuple[str, str]] = {
    "append_only_log": (
        "What does it mean for a data file to be append-only, and why is that efficient?",
        "An append-only log handles writes by adding new key-value pairs to the end of the "
        "file rather than modifying existing data. Appending is efficient because it is a "
        "cheap operation compared with other kinds of writes.",
    ),
    "log_segment": (
        "How is an ever-growing append-only log kept manageable?",
        "The log is broken into segments: a segment file is closed once it reaches a certain "
        "size, and subsequent writes go to a new segment file.",
    ),
    "hash_index": (
        "Describe the simplest indexing strategy for a key-value store built on a log, and "
        "state its limitations.",
        "The simplest strategy keeps an in-memory hash map from every key to the byte offset "
        "of that key's most recent value in the data file, updated on every append. Its "
        "limitations are that the whole hash map must fit in memory, and that it cannot "
        "answer range queries efficiently.",
    ),
    "compaction": (
        "What does compaction do to a log's segments?",
        "Compaction throws away duplicate keys across the log's segments, keeping only the "
        "most recent update for each key. Compacted segments can also be merged together at "
        "the same time.",
    ),
    "sstable": (
        "What requirements does the SSTable format place on a segment file?",
        "An SSTable requires that the key-value pairs in a segment file are sorted by key, "
        "and that each key appears at most once within a merged segment — a property that "
        "compaction already guarantees.",
    ),
    "memtable": (
        "Where does a write go when it first arrives, and what happens to it later?",
        "A write is first added to an in-memory sorted balanced-tree structure called a "
        "memtable. Once the memtable grows past a threshold, it is written out to disk as a "
        "new SSTable file.",
    ),
    "lsm_tree": (
        "What two structures does an LSM-tree combine?",
        "An LSM-tree combines an in-memory memtable with on-disk SSTable files. It is the "
        "overall indexing algorithm used in storage engines such as LevelDB and RocksDB.",
    ),
    "bloom_filter": (
        "What problem does a Bloom filter solve for a storage engine?",
        "A Bloom filter is a memory-efficient structure approximating the contents of a set. "
        "A storage engine uses it to tell quickly whether a key is definitely absent, which "
        "saves unnecessary disk reads when an LSM-tree looks up a key that does not exist.",
    ),
    "b_tree": (
        "How does a B-tree organize data on disk, and how does that differ from a "
        "log-structured index?",
        "A B-tree keeps key-value pairs sorted by key, like a log-structured index, but it "
        "breaks the database into fixed-size blocks or pages and reads or writes one page at "
        "a time rather than appending variable-size segments.",
    ),
    "write_ahead_log": (
        "What is a write-ahead log and when is it written to?",
        "A write-ahead log (WAL, or redo log) is an append-only file that every B-tree "
        "modification must be written to before that modification is applied to the tree's "
        "own pages. It exists to make the database resilient to crashes.",
    ),
    "write_amplification": (
        "What is write amplification, and what causes it?",
        "Write amplification is the effect where one write to the database results in "
        "multiple physical writes to disk over the database's lifetime. In a B-tree it "
        "happens because each write goes to both the write-ahead log and the tree page; in a "
        "log-structured index it happens because of repeated compaction and merging of "
        "SSTables.",
    ),
}


@dataclass(frozen=True)
class DiagnosisCase:
    name: str
    #: slug of the concept the answered question was about
    answered_concept: str
    question_prompt: str
    #: engineered to exhibit exactly one gap
    student_answer: str
    #: hand-written in evaluator.py's voice
    evaluation_explanation: str
    #: any of these is a correct diagnosis
    acceptable_suspects: set[str]
    #: the sharpest answer — reported, not asserted
    preferred_suspect: str
    #: diagnosing any of these is wrong, usually because the answer demonstrates mastery of it
    forbidden_suspects: set[str] = field(default_factory=set)
    #: depends_on hops from answered_concept to preferred_suspect (0 = the concept itself)
    hops_to_preferred: int = 1
    #: the gap is background knowledge the chapter never teaches, so the diagnoser is
    #: expected to fall back to general knowledge and disclose it
    expects_outside_graph: bool = False

    @property
    def answered_concept_id(self) -> str:
        return _cid(self.answered_concept)


CASES: list[DiagnosisCase] = [
    DiagnosisCase(
        name="compaction_missing_segments",
        answered_concept="compaction",
        question_prompt="What does compaction do to a log's segments?",
        # Gets dedup right; treats the log as one undifferentiated file, so segments —
        # and merging them — are absent.
        student_answer=(
            "Compaction goes through the log file and deletes the older copies of each key "
            "so that only the newest value for each key is left. That makes the file smaller."
        ),
        evaluation_explanation=(
            "The answer correctly states that compaction keeps only the most recent update "
            "for each key. It does not state that compaction operates on the log's segments, "
            "and it does not mention that compacted segments can be merged together."
        ),
        acceptable_suspects={"log_segment"},
        preferred_suspect="log_segment",
        forbidden_suspects={"b_tree", "write_ahead_log", "memtable", "hash_index"},
        hops_to_preferred=1,
    ),
    DiagnosisCase(
        name="wal_missing_btree_pages",
        answered_concept="write_ahead_log",
        question_prompt="What is a write-ahead log and when is it written to?",
        # Generic crash-recovery understanding with no model of what it protects.
        student_answer=(
            "The write-ahead log is a backup file. The database writes its changes there "
            "first, so if it crashes partway through you can replay the log afterwards and "
            "get back to a consistent state."
        ),
        evaluation_explanation=(
            "The answer captures that the log exists for crash recovery and is written to "
            "before the change takes effect. It never connects the log to what it protects: "
            "it does not state that every B-tree modification is written to the log before "
            "being applied to the tree's own pages."
        ),
        acceptable_suspects={"b_tree"},
        preferred_suspect="b_tree",
        forbidden_suspects={"memtable", "lsm_tree", "append_only_log", "compaction"},
        hops_to_preferred=1,
    ),
    DiagnosisCase(
        name="sstable_missing_uniqueness",
        answered_concept="sstable",
        question_prompt="What requirements does the SSTable format place on a segment file?",
        # Sorting yes, per-key uniqueness no — and no idea what would guarantee it.
        student_answer=(
            "An SSTable is a segment file where the key-value pairs are stored in sorted "
            "order by key. Sorting them makes it straightforward to merge two segment files "
            "together, since you can walk both in order."
        ),
        evaluation_explanation=(
            "The answer states the sorting requirement correctly. It omits the second "
            "requirement — that each key appears at most once within a merged segment — and "
            "so does not say what process already guarantees that property."
        ),
        acceptable_suspects={"compaction"},
        preferred_suspect="compaction",
        forbidden_suspects={"memtable", "b_tree", "write_ahead_log", "hash_index"},
        hops_to_preferred=1,
    ),
    DiagnosisCase(
        name="lsm_tree_unbounded_sstables",
        answered_concept="lsm_tree",
        question_prompt="What two structures does an LSM-tree combine?",
        # Both halves named, but the on-disk set is treated as growing without bound —
        # the gap is compaction, two hops down via sstable.
        student_answer=(
            "An LSM-tree keeps recent writes in an in-memory tree and flushes them out to "
            "sorted files on disk when it gets large. Over time you accumulate more and more "
            "of these files, and a lookup has to check each one in turn until it finds the key."
        ),
        evaluation_explanation=(
            "The answer correctly identifies the in-memory structure and the on-disk sorted "
            "files, and how a write moves between them. It treats the set of on-disk files as "
            "simply accumulating, and never accounts for what keeps that set from growing "
            "without bound."
        ),
        acceptable_suspects={"compaction", "sstable"},
        preferred_suspect="compaction",
        forbidden_suspects={"memtable", "b_tree", "write_ahead_log"},
        hops_to_preferred=2,
    ),
    DiagnosisCase(
        name="lsm_tree_missing_memtable",
        answered_concept="lsm_tree",
        question_prompt="What two structures does an LSM-tree combine?",
        # The on-disk half is solid; the in-memory half is absent. Tests branch selection
        # between two direct prerequisites, and the on-disk concepts are forbidden.
        student_answer=(
            "An LSM-tree stores its data in sorted segment files on disk and merges those "
            "files together over time so that lookups stay fast and old values get discarded."
        ),
        evaluation_explanation=(
            "The answer covers the on-disk sorted files and the merging that maintains them. "
            "It omits the in-memory half of the structure entirely — it never says where a "
            "write goes when it first arrives, before anything is written to disk."
        ),
        acceptable_suspects={"memtable"},
        preferred_suspect="memtable",
        # The answer demonstrates the on-disk side; blaming it contradicts the evidence.
        forbidden_suspects={"sstable", "compaction", "log_segment"},
        hops_to_preferred=1,
    ),
    DiagnosisCase(
        name="write_amplification_missing_log_structured_cause",
        answered_concept="write_amplification",
        question_prompt="What is write amplification, and what causes it?",
        # B-tree side explained perfectly; the log-structured cause is missing entirely.
        # The mechanism named in the evidence is "repeated compaction and merging", three
        # hops down (lsm_tree -> sstable -> compaction).
        student_answer=(
            "Write amplification is when one logical write to the database turns into several "
            "physical writes to disk. In a B-tree, every change has to be written to the "
            "write-ahead log and then again to the tree page itself, so a single update costs "
            "you at least two writes."
        ),
        evaluation_explanation=(
            "The answer defines write amplification correctly and explains the B-tree case "
            "fully, naming both the write-ahead log and the tree page. It omits the "
            "log-structured case: it never accounts for why a log-structured index rewrites "
            "the same data multiple times over the database's lifetime."
        ),
        acceptable_suspects={"compaction", "sstable", "lsm_tree"},
        preferred_suspect="compaction",
        # The answer demonstrates mastery of both of these.
        forbidden_suspects={"b_tree", "write_ahead_log"},
        hops_to_preferred=3,
    ),
    DiagnosisCase(
        name="append_only_log_is_the_root",
        answered_concept="append_only_log",
        question_prompt=(
            "What does it mean for a data file to be append-only, and why is that efficient?"
        ),
        # A leaf concept: there is nowhere deeper to go, so the diagnosis must land on the
        # concept itself rather than confabulating a prerequisite.
        student_answer=(
            "A log is the file where the database keeps its data. You write records into it "
            "and then read them back out again whenever you need them."
        ),
        evaluation_explanation=(
            "The answer describes a data file in generic terms. It does not state that writes "
            "are handled by appending new key-value pairs to the end of the file, and it does "
            "not say why appending is efficient compared with other kinds of writes."
        ),
        acceptable_suspects={"append_only_log"},
        preferred_suspect="append_only_log",
        forbidden_suspects={"log_segment", "hash_index", "compaction", "b_tree"},
        hops_to_preferred=0,
    ),
    DiagnosisCase(
        name="hash_index_stores_values_not_offsets",
        answered_concept="hash_index",
        question_prompt=(
            "Describe the simplest indexing strategy for a key-value store built on a log, "
            "and state its limitations."
        ),
        # Thinks the map holds values rather than offsets into the data file. Genuinely
        # ambiguous: it can be read as a hash_index-level error, or as not understanding
        # that the data lives in the log and the index only points into it.
        student_answer=(
            "You keep a hash map in memory that maps each key straight to its value, so any "
            "lookup is instant. The catch is that everything has to fit in memory."
        ),
        evaluation_explanation=(
            "The answer states the in-memory size requirement correctly. It describes the "
            "hash map as holding values directly, rather than the byte offset of each key's "
            "most recent value in the data file, and it omits the range-query limitation."
        ),
        acceptable_suspects={"append_only_log", "hash_index"},
        preferred_suspect="append_only_log",
        forbidden_suspects={"b_tree", "memtable", "write_ahead_log", "lsm_tree"},
        hops_to_preferred=1,
    ),
    DiagnosisCase(
        name="hash_lookup_is_background_knowledge",
        answered_concept="hash_index",
        question_prompt=(
            "Describe the simplest indexing strategy for a key-value store built on a log, "
            "and state its limitations."
        ),
        # The rare path. The chapter says to "keep an in-memory hash map where every key is
        # mapped to a byte offset" but never explains what a hash map buys you — this student
        # has substituted a linear scan, which no prerequisite in the graph accounts for.
        # `append_only_log` is upstream but the student's grasp of the log is fine; the gap is
        # data-structures background the source material simply assumes.
        student_answer=(
            "You keep a list in memory holding every key along with the place its value is "
            "stored. When a lookup comes in you go through that list comparing keys until you "
            "reach the one you want, then jump to the spot it points at."
        ),
        evaluation_explanation=(
            "The answer correctly has the in-memory structure holding a location rather than "
            "the value itself, and correctly notes it must be held in memory. It describes "
            "retrieval as scanning the entries in sequence until the key matches, rather than "
            "the direct key-to-offset lookup a hash map provides, and omits the range-query "
            "limitation."
        ),
        # Either anchor is defensible; what matters is that it discloses rather than blaming
        # a prerequisite the student demonstrably understands.
        acceptable_suspects={"hash_index", "append_only_log"},
        preferred_suspect="hash_index",
        forbidden_suspects={"b_tree", "memtable", "lsm_tree", "write_ahead_log", "compaction"},
        hops_to_preferred=0,
        expects_outside_graph=True,
    ),
]


def build_graph() -> DependencyGraph:
    """The Case 3 graph with a pipeline-1 question set attached to every concept.

    Concept shape (ids, summaries, depends_on, evidence) is imported from
    `tests/question_geval/golden.py` rather than re-declared, so the three suites cannot
    disagree about the same case. The questions are added here because that suite has no
    reason to carry them — it is testing the generator that would produce them.
    """
    graph = CASE_3_QUESTIONS.build_graph()
    for concept in graph.concepts:
        slug = concept.id.split(":", 1)[1]
        prompt, expected_answer = _PIPELINE_1_QUESTIONS[slug]
        concept.questions = [
            Question(
                id=f"{concept.id}:q1",
                concept_id=concept.id,
                prompt=prompt,
                expected_answer_notes=expected_answer,
            )
        ]
    return graph


def _validate() -> None:
    """Fail loudly at import if a case references a concept that isn't in the graph, or
    claims a hop distance the dependency structure doesn't support."""
    graph = build_graph()
    by_id = {c.id: c for c in graph.concepts}
    slugs = {c.id.split(":", 1)[1] for c in graph.concepts}

    def hops(start: str, target: str) -> int | None:
        """Shortest depends_on distance from `start` down to `target`."""
        frontier, seen, depth = [_cid(start)], {_cid(start)}, 0
        while frontier:
            if _cid(target) in frontier:
                return depth
            nxt = [d for node in frontier for d in by_id[node].depends_on if d not in seen]
            seen.update(nxt)
            frontier, depth = nxt, depth + 1
        return None

    assert slugs == set(_PIPELINE_1_QUESTIONS), (
        f"_PIPELINE_1_QUESTIONS is out of sync with the graph: "
        f"missing={slugs - set(_PIPELINE_1_QUESTIONS)}, "
        f"extra={set(_PIPELINE_1_QUESTIONS) - slugs}"
    )
    names = [c.name for c in CASES]
    assert len(names) == len(set(names)), f"duplicate case names: {names}"

    for case in CASES:
        referenced = (
            {case.answered_concept, case.preferred_suspect}
            | case.acceptable_suspects
            | case.forbidden_suspects
        )
        unknown = referenced - slugs
        assert not unknown, f"{case.name}: unknown concept slugs {unknown}"
        assert case.preferred_suspect in case.acceptable_suspects, (
            f"{case.name}: preferred_suspect {case.preferred_suspect!r} is not in "
            f"acceptable_suspects"
        )
        overlap = case.acceptable_suspects & case.forbidden_suspects
        assert not overlap, f"{case.name}: {overlap} are both acceptable and forbidden"
        actual = hops(case.answered_concept, case.preferred_suspect)
        assert actual == case.hops_to_preferred, (
            f"{case.name}: hops_to_preferred={case.hops_to_preferred} but the graph puts "
            f"{case.preferred_suspect!r} {actual} hop(s) from {case.answered_concept!r}"
        )


_validate()
