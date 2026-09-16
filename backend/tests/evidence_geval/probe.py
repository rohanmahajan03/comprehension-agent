"""Cheap iteration harness for the evidence_finder suite. Not a test — run it directly.

A full suite run is 24 scans plus a judge call per quote. That is the wrong instrument for
"did my prompt edit help?", and the wrong one for "is my judge still discriminating?".

    # One concept end to end, with every quote located against its labelled regions
    python -m tests.evidence_geval.probe case hash_index

    # One negative fixture — the zero-tolerance direction
    python -m tests.evidence_geval.probe case replication

    # Judge calibration: fixed good and bad inputs, ~6 calls
    python -m tests.evidence_geval.probe judges

The `judges` mode is the one to re-run after any judge-prompt edit. Recalibrating a judge until
the suite goes green is the easiest way to build a test that measures nothing, and at exactly
1.00 that is indistinguishable from a healthy pass. Both judges here are given inputs they must
*reject*; a judge that passes everything is a rubber stamp. This project has been bitten by that
twice (see tests/diagnoser_geval/probe.py).

Requires LLM_API_KEY:
    cd backend && set -a && source ../.env && set +a && python -m tests.evidence_geval.probe ...
"""

from __future__ import annotations

import sys

from app.models import Concept
from app.services import evidence_finder
from app.services.text_match import is_verbatim

from . import golden
from .golden import ABSENT, CONCEPT_LABELS, SOURCE
from .support import judge_explanatory, judge_summary_supported

# Fixed inputs with known right answers, for calibration. Each judge gets one it must accept
# and one it must reject; the rejections are the load-bearing half.
_EXPLANATORY_CASES: list[tuple[str, str, bool]] = [
    (
        "Compaction",
        "Compaction means throwing away duplicate keys in the log, and keeping only the most "
        "recent update for each key.",
        True,
    ),
    (
        # Verbatim, on-topic, and teaches nothing — the name-drop this judge exists to catch.
        "Compaction",
        "We can then perform compaction on these segments.",
        False,
    ),
    (
        # Terse but genuinely definitional, and self-contained. Guards the opposite error: a
        # judge that demands narrative detail would reject this, and most real evidence with it.
        "Append-Only Log",
        "Many databases internally use a log, which is an append-only data file.",
        True,
    ),
    (
        # A pure limitation passage, stating no definition. The judge prompt lists "what it
        # costs / what it cannot do" as explanatory, and the first live run showed the judge
        # rejecting exactly this case anyway — anchoring on "what it is" and ignoring its own
        # criteria. The prompt was made explicit about it; this fixture is what keeps it honest,
        # and its absence is why the miscalibration survived the first calibration pass.
        "Hash Index",
        "The hash table index also has limitations: - The hash table must fit in memory. "
        "- Range queries are not efficient.",
        True,
    ),
    (
        # Attribution only — who described it and which systems use it. Says nothing about the
        # structure, so it must stay a rejection even after the loosening above.
        "LSM-Tree (Log-Structured Merge-Tree)",
        "The algorithm described here is essentially what is used in LevelDB and RocksDB. "
        "Originally this indexing structure was described by Patrick O'Neil et al. under the "
        "name Log-Structured Merge-Tree (or LSM-Tree).",
        False,
    ),
    (
        # Anaphoric: "This in-memory tree" has no antecedent inside the quote, so judged on its
        # own — which is what the prompt instructs — it defines nothing. The first version of
        # this fixture expected True and the judge disagreed; the judge was right, and the
        # expectation was corrected rather than the prompt loosened.
        #
        # Worth knowing beyond calibration: a quote starting "This…"/"It…" is weak evidence in
        # production too, since question_generator receives passages individually with no
        # surrounding chapter. The judge penalizing them is the pipeline's interest, not a quirk.
        "Memtable",
        "This in-memory tree is sometimes called a memtable.",
        False,
    ),
]

_SUMMARY_CASES: list[tuple[str, list[str], str, bool]] = [
    (
        "Bloom Filter",
        [
            "A Bloom filter is a memory-efficient data structure for approximating the "
            "contents of a set."
        ],
        "A Bloom filter is a memory-efficient structure that approximates a set's contents.",
        True,
    ),
    (
        # Overreach: the false-positive rate is real domain knowledge and is nowhere in the
        # passage. This is the failure mode the check exists for.
        "Bloom Filter",
        [
            "A Bloom filter is a memory-efficient data structure for approximating the "
            "contents of a set."
        ],
        "A Bloom filter is a memory-efficient set approximation with a tunable false-positive "
        "rate, typically around 1% at ten bits per key.",
        False,
    ),
    (
        # Condensing two passages into one sentence is expected, not overreach. Guards against
        # a judge that penalizes any rewording.
        "Hash Index",
        [
            "The simplest possible indexing strategy is this: keep an in-memory hash map "
            "where every key is mapped to a byte offset in the data file.",
            "The hash table index also has limitations: - The hash table must fit in memory. "
            "- Range queries are not efficient.",
        ],
        "A hash index maps each key to a byte offset in the data file, but must fit in memory "
        "and cannot serve range queries efficiently.",
        True,
    ),
]


def probe_case(name: str) -> int:
    negative = next((entry for entry in ABSENT if entry[0] == name), None)
    if negative is not None:
        slug, label, summary = negative
        concept = Concept(id=f"case3:{slug}", name=label, summary=summary)
        expectation = "MUST be found: false — this chapter never teaches it"
    elif name in CONCEPT_LABELS:
        concept = Concept(
            id=f"case3:{name}",
            name=CONCEPT_LABELS[name],
            summary=f"{CONCEPT_LABELS[name]}, as described in this chapter.",
        )
        expectation = "should be found: true, with quotes inside its labelled regions"
    else:
        print(f"unknown concept {name!r}.")
        print(f"  positives: {', '.join(CONCEPT_LABELS)}")
        print(f"  negatives: {', '.join(slug for slug, _, _ in ABSENT)}")
        return 1

    print(f"\n{'=' * 78}\n{name}  —  {expectation}\n{'=' * 78}")
    raw = evidence_finder._propose_raw_evidence(SOURCE, concept)
    proposal = evidence_finder.find_evidence(SOURCE, concept)

    print(f"\nraw:      found={raw['found']}  quotes={len(raw['quotes'])}")
    for quote in raw["quotes"]:
        print(f"  [{'verbatim' if is_verbatim(quote, SOURCE) else 'NOT VERBATIM'}] {quote[:100]!r}")

    print(f"\nfiltered: found={proposal.found}  quotes={len(proposal.quotes)}  dropped={proposal.dropped}")
    print(f"summary:  {proposal.summary!r}")
    for quote in proposal.quotes:
        located = golden.locate(quote)
        on_target = golden.is_on_target(name, quote)
        where = f"@{located[0]}-{located[1]}" if located else "unlocatable"
        print(f"  [{'on-target' if on_target else 'OFF-TARGET'}] {where:>16}  {quote[:90]!r}")
        if not on_target and located:
            owners = [cid for cid in golden.SPANS if golden.is_on_target(cid, quote)]
            print(f"      labelled for: {owners or 'no concept — unlabelled chapter text'}")
    return 0


def probe_judges() -> int:
    print(f"\n{'=' * 78}\nJUDGE CALIBRATION\n{'=' * 78}")
    failures = 0

    print("\nexplanatory (does the quote teach the concept, or just name it?)")
    for concept_name, quote, expected in _EXPLANATORY_CASES:
        got, why = judge_explanatory(concept_name, quote)
        ok = got == expected
        failures += not ok
        print(f"  [{'OK  ' if ok else 'MISS'}] expected {expected}, got {got}  ({concept_name})")
        print(f"         {quote[:88]!r}")
        if not ok:
            print(f"         judge said: {why}")

    print("\nsummary supported (does the summary overreach its quotes?)")
    for concept_name, quotes, summary, expected in _SUMMARY_CASES:
        got, why = judge_summary_supported(concept_name, quotes, summary)
        ok = got == expected
        failures += not ok
        print(f"  [{'OK  ' if ok else 'MISS'}] expected {expected}, got {got}  ({concept_name})")
        print(f"         {summary[:88]!r}")
        if not ok:
            print(f"         judge said: {why}")

    print()
    if failures:
        print(f"{failures} calibration case(s) wrong — the judge prompts need work before the")
        print("suite's numbers mean anything.")
    else:
        print("Both judges discriminate on fixed inputs, including the ones they must reject.")
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "judges":
        return probe_judges()
    if len(argv) >= 3 and argv[1] == "case":
        return probe_case(argv[2])
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
