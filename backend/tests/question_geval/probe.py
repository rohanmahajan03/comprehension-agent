"""Stage 0 premise probe for concept evidence. Not a test — run it directly.

Design doc: docs/specs/2026-09-14-concept-evidence-measurement-and-generalization.md §3.

`tests/question_geval`'s check 6 (target focus) fails at 0.86: four of 28 at-risk questions
assess a prerequisite or sibling rather than the concept they were written for. The standing
explanation is that every drifting concept has a 1-2 sentence summary sitting beside rich
neighbour passages, so rule 4 (only ask what the evidence fully supports) makes the
neighbour's question the best-supported one available. **That explanation has never been
tested.** A prompt-level fix aimed at the same problem was tried and failed (rule 10: target
focus 0.86 → 0.85 while evidence basis fell 0.94 → 0.82), which is reason enough not to
assume this one works either.

This probe tests it for about eight generation calls:

    # One concept, full question-by-question comparison
    python -m tests.question_geval.probe thicken write_ahead_log

    # All four drifting concepts plus a summary table
    python -m tests.question_geval.probe thicken

    # Repeat the whole A/B and report the spread — READ THIS BEFORE BELIEVING ONE RUN
    python -m tests.question_geval.probe thicken --trials=4

For each concept it generates questions twice — once from the graph exactly as
`golden.build_graph()` produces it, once with hand-picked verbatim chapter passages attached
as `Concept.source_quotes` — and runs both sets through `judge_target_focus` and
`judge_evidence_basis`.

**The quotes are hand-picked, not produced by `evidence_finder`.** That is the whole point of
running this before anything else: it isolates "does more target evidence reduce drift" from
"can a scan find that evidence", so a null result means the hypothesis is wrong rather than
that the scan picked badly.

**Only the target concept is thickened.** Production (that doc's stage 2) would thicken every
concept, including the neighbours a question drifts onto, so what this measures is the
*isolated* effect — an upper bound. If drift doesn't fall here, it will not fall in
production, and stage 2 has no justification.

**One run cannot answer this.** The first two runs of this probe disagreed: pooled target
focus moved +0.21 on the first and +0.02 on the second, with `bloom_filter` reversing outright
(0.67 → 1.00, then 1.00 → 0.67) on identical inputs. `temperature=0` does not make these calls
deterministic — the same is on record for `evaluator.py`'s verdicts and for `question_generator`
corrupting a passage differently on each run. With ~15 binary judgments per variant one flip is
~7 points, so use `--trials` and read the spread; a mean delta smaller than the range straddling
zero is the noise floor, not a result.

**Read the delta column before reading the rates.** Case 3 is an abridged excerpt and its
golden summaries are already close paraphrases of it, so for some concepts there is very
little left in the chapter to add. A concept whose thickened variant carries barely more
information than its baseline cannot test the hypothesis either way, and the per-concept
`+chars` figure is what says whether the comparison was real.

Requires LLM_API_KEY:
    cd backend && set -a && source ../.env && set +a && python -m tests.question_geval.probe ...
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from app.models import Concept, DependencyGraph
from app.services import question_generator
from app.services.question_generator import RawQuestion
from app.services.text_match import is_verbatim
from tests.graph_geval.golden import CASE_3_STORAGE_ENGINES

from .golden import CASE_3_QUESTIONS
from .support import (
    _target_focus_context,
    judge_evidence_basis,
    judge_target_focus,
    source_passages,
)

# Verbatim Case 3 passages about each drifting concept, in chapter order — what
# `evidence_finder.find_evidence()` would ideally return for it, picked by hand so the
# probe doesn't depend on the scan working.
#
# Chosen by one rule: include a passage if it is *about this concept* and says something the
# concept's golden summary does not already state. Passages that merely restate the summary
# verbatim are included too, since that is what a real scan would return and excluding them
# would model a scan nobody will build — but they are why `+chars` matters more than
# `+passages` when reading the result.
THICKENING: dict[str, list[str]] = {
    "hash_index": [
        "The simplest possible indexing strategy is this: keep an in-memory hash map where "
        "every key is mapped to a byte offset in the data file. Whenever you append a new "
        "key-value pair to the file, you also update the hash map to reflect the offset of "
        "the data you just wrote.",
        "The hash table index also has limitations: - The hash table must fit in memory. "
        "- Range queries are not efficient.",
    ],
    "compaction": [
        "We can then perform compaction on these segments. Compaction means throwing away "
        "duplicate keys in the log, and keeping only the most recent update for each key.",
        "Since compaction often makes segments much smaller, we can also merge several "
        "segments together at the same time as performing the compaction.",
        # New relative to the summary: ties compaction to the SSTable uniqueness guarantee.
        "We also require that each key only appears once within each merged segment file "
        "(the compaction process already ensures that).",
    ],
    "bloom_filter": [
        "The LSM-tree algorithm can be slow when looking up keys that do not exist in the "
        "database. In order to optimize this kind of access, storage engines often use "
        "additional Bloom filters.",
        "A Bloom filter is a memory-efficient data structure for approximating the contents "
        "of a set. It can tell you if a key does not appear in the database, and thus saves "
        "many unnecessary disk reads.",
    ],
    "write_ahead_log": [
        "In order to make the database resilient to crashes, it is common for B-tree "
        "implementations to include an additional data structure on disk: a write-ahead log "
        "(WAL, also known as a redo log).",
        "This is an append-only file to which every B-tree modification must be written "
        "before it can be applied to the pages of the tree itself.",
        # The sharpest fixture in the set, and the one to read most carefully. This sentence
        # is the anchor for `write_amplification`, WAL's sibling — and the recorded drift is
        # a WAL question asking how many physical writes a logical write causes, judged
        # off-target for being write_amplification's question. Attaching it to WAL's own
        # evidence is a genuine test of the hypothesis (the chapter really does discuss WAL
        # here), but it is also exactly the judge-contamination risk the design doc's §6
        # warns about: a bigger target blob can make the judge call the same question
        # on-target without the question having changed. If WAL improves and the others
        # don't, suspect the instrument before believing the result.
        "A B-tree index must write every piece of data at least twice: once to the "
        "write-ahead log, and once to the tree page itself.",
    ],
}

# The four concepts question_geval recorded as drifting. Probed together because each
# contributes only three or four questions — a single concept is a sample of three or four
# binary judgments, where one flip is 25-33%.
DRIFTING = ["write_ahead_log", "compaction", "bloom_filter", "hash_index"]


def _check_fixtures() -> None:
    """Fail loudly at import if a fixture quote isn't really in the chapter.

    A paraphrase here would make the probe measure the effect of *invented* evidence, which
    is both a different question and one production can never reproduce — `source_quotes` is
    verbatim-only by construction everywhere else (app/services/text_match.py).
    """
    source = CASE_3_STORAGE_ENGINES.source_text
    known = {c.id for c in CASE_3_STORAGE_ENGINES.concepts}
    for slug, quotes in THICKENING.items():
        assert slug in known, f"THICKENING names unknown concept {slug!r}"
        for quote in quotes:
            assert is_verbatim(quote, source), (
                f"THICKENING[{slug!r}] quote is not verbatim in the Case 3 source text: {quote[:80]!r}"
            )
    for slug in DRIFTING:
        assert slug in THICKENING, f"no thickening fixture for drifting concept {slug!r}"


_check_fixtures()


@dataclass
class Variant:
    """One side of the A/B for one concept."""

    label: str
    questions: list[RawQuestion]
    target_chars: int
    target_passages: int
    on_target: list[bool]
    grounded: list[bool]
    focus_reasons: list[str]

    @property
    def focus_rate(self) -> float:
        return sum(self.on_target) / len(self.on_target) if self.on_target else float("nan")

    @property
    def grounded_rate(self) -> float:
        return sum(self.grounded) / len(self.grounded) if self.grounded else float("nan")

    def focus_count(self) -> str:
        return f"{sum(self.on_target)}/{len(self.on_target)}"

    def grounded_count(self) -> str:
        return f"{sum(self.grounded)}/{len(self.grounded)}"


def _graph_with_quotes(slug: str | None) -> DependencyGraph:
    """The Case 3 graph, optionally with `slug`'s hand-picked quotes attached to it alone."""
    graph = CASE_3_QUESTIONS.build_graph()
    if slug is not None:
        target = next(c for c in graph.concepts if c.id.split(":", 1)[1] == slug)
        target.source_quotes = list(THICKENING[slug])
    return graph


def _run_variant(label: str, graph: DependencyGraph, slug: str) -> Variant:
    by_id = {c.id: c for c in graph.concepts}
    concept: Concept = by_id[f"{CASE_3_QUESTIONS.doc_id}:{slug}"]

    questions = question_generator._generate_raw_for_concept(concept, by_id, graph)
    passages = source_passages(concept, by_id, graph)
    target_text, neighbour_text = _target_focus_context(passages)
    evidence_context = " ".join(p["text"] for p in passages)

    on_target: list[bool] = []
    grounded: list[bool] = []
    focus_reasons: list[str] = []
    for q in questions:
        ok, why = judge_target_focus(
            q["question"], q["type"], concept.name, target_text, neighbour_text
        )
        on_target.append(ok)
        focus_reasons.append(why)
        grounded.append(judge_evidence_basis(q["question"], q["type"], evidence_context)[0])

    return Variant(
        label=label,
        questions=questions,
        target_chars=len(target_text),
        target_passages=sum(1 for p in passages if p["role"] == "target_concept"),
        on_target=on_target,
        grounded=grounded,
        focus_reasons=focus_reasons,
    )


def _print_variant(v: Variant) -> None:
    print(f"\n  {v.label}  —  {v.target_passages} target passage(s), {v.target_chars} chars")
    # Counts, not just rates. Thickening changes how many questions get generated, so a
    # rate can fall while the absolute number of good questions rises — that happened on the
    # first real run and read as a regression until the counts were checked by hand.
    print(
        f"  target focus {v.focus_rate:.2f} ({v.focus_count()})"
        f"   evidence basis {v.grounded_rate:.2f} ({v.grounded_count()})"
    )
    for q, ok, ground, why in zip(
        v.questions, v.on_target, v.grounded, v.focus_reasons, strict=True
    ):
        flag = "  on-target" if ok else "OFF-TARGET"
        print(f"    [{flag}] [{'grounded' if ground else '  UNGROUNDED'}] ({q['type']})")
        print(f"        {q['question']}")
        if not ok:
            print(f"        judge: {why}")


def probe_concept(slug: str, verbose: bool = True) -> tuple[Variant, Variant]:
    if verbose:
        print(f"\n{'=' * 78}\n{slug}\n{'=' * 78}")
    baseline = _run_variant("baseline  ", _graph_with_quotes(None), slug)
    thickened = _run_variant("thickened ", _graph_with_quotes(slug), slug)

    if verbose:
        _print_variant(baseline)
        _print_variant(thickened)
        added = thickened.target_chars - baseline.target_chars
        print(
            f"\n  delta: +{thickened.target_passages - baseline.target_passages} passages, "
            f"+{added} chars ({added / max(baseline.target_chars, 1):+.0%})"
            f"   focus {baseline.focus_rate:.2f} → {thickened.focus_rate:.2f}"
            f"   grounded {baseline.grounded_rate:.2f} → {thickened.grounded_rate:.2f}"
        )
    return baseline, thickened


def probe_thicken(slug: str | None, trials: int = 1, verbose: bool = True) -> int:
    slugs = [slug] if slug else DRIFTING
    if slug and slug not in THICKENING:
        print(f"no thickening fixture for {slug!r}. Available: {', '.join(THICKENING)}")
        return 1

    if trials > 1:
        return _probe_trials(slugs, trials)

    results = [(s, *probe_concept(s, verbose=verbose)) for s in slugs]
    if len(results) < 2:
        return 0

    _print_summary(results)
    return 0


def _rates(results: list[tuple[str, Variant, Variant]]) -> tuple[float, float, float, float]:
    """Pooled (baseline focus, thickened focus, baseline grounded, thickened grounded)."""

    def pool(idx: int, field: str) -> float:
        fs = [f for r in results for f in getattr(r[idx], field)]
        return sum(fs) / len(fs) if fs else float("nan")

    return pool(1, "on_target"), pool(2, "on_target"), pool(1, "grounded"), pool(2, "grounded")


def _probe_trials(slugs: list[str], trials: int) -> int:
    """Repeat the whole A/B `trials` times and report the spread.

    Exists because the first two single-trial runs of this probe disagreed with each other:
    pooled target focus moved +0.21 on one and +0.02 on the next, with `bloom_filter`
    reversing outright (0.67 → 1.00, then 1.00 → 0.67) on identical inputs. `temperature=0`
    pins nothing here — this project has recorded the same for `evaluator.py`'s verdicts and
    for `question_generator` corrupting a passage differently on each run — so a single pair
    of runs measures sampling noise as readily as it measures the effect.

    With ~15 binary judgments per variant, one flip is ~7 points. An effect has to clear the
    run-to-run spread to mean anything, and that spread is only observable by repeating.
    """
    print(f"Running {trials} trials over {len(slugs)} concept(s); per-question detail suppressed.\n")
    per_trial: list[tuple[float, float, float, float]] = []
    for t in range(1, trials + 1):
        results = [(s, *probe_concept(s, verbose=False)) for s in slugs]
        rates = _rates(results)
        per_trial.append(rates)
        bf, tf, bg, tg = rates
        print(
            f"  trial {t}: focus {bf:.2f} → {tf:.2f} ({tf - bf:+.2f})"
            f"    grounded {bg:.2f} → {tg:.2f} ({tg - bg:+.2f})"
        )

    print(f"\n{'=' * 78}\nACROSS {trials} TRIALS\n{'=' * 78}")
    focus_deltas = [t[1] - t[0] for t in per_trial]
    grounded_deltas = [t[3] - t[2] for t in per_trial]
    for name, deltas in (("target focus", focus_deltas), ("evidence basis", grounded_deltas)):
        mean = sum(deltas) / len(deltas)
        print(
            f"{name:<16} delta  mean {mean:+.3f}   range [{min(deltas):+.2f}, {max(deltas):+.2f}]"
            f"   {sum(1 for d in deltas if d > 0)}/{len(deltas)} trials positive"
        )
    print(
        "\nA mean delta smaller than the range straddling zero is not an effect — it is the\n"
        "noise floor of this instrument. Compare against the reverted rule-10 prompt fix,\n"
        "which moved target focus -0.01 and was correctly called noise."
    )
    return 0


def _print_summary(results: list[tuple[str, Variant, Variant]]) -> None:
    print(f"\n{'=' * 78}\nSUMMARY\n{'=' * 78}")
    print(f"{'concept':<18} {'+chars':>7} {'questions':>12} {'focus':>16} {'grounded':>16}")
    for name, base, thick in results:
        added = thick.target_chars - base.target_chars
        print(
            f"{name:<18} {added:>+7} "
            f"{len(base.questions):>5} → {len(thick.questions):<5} "
            f"{base.focus_rate:>7.2f} → {thick.focus_rate:<6.2f} "
            f"{base.grounded_rate:>7.2f} → {thick.grounded_rate:<6.2f}"
        )

    # Pooled across every question rather than averaged per concept, matching how
    # question_geval reports check 6 — a per-concept mean would weight a concept with two
    # questions the same as one with five.
    def flags(pick, field: str) -> list[bool]:
        return [f for r in results for f in getattr(pick(r), field)]

    def pooled(pick, field: str) -> str:
        fs = flags(pick, field)
        return f"{sum(fs) / len(fs):.2f}" if fs else "  nan"

    base_q = sum(len(r[1].questions) for r in results)
    thick_q = sum(len(r[2].questions) for r in results)
    print(
        f"\n{'POOLED':<18} {'':>7} "
        f"{base_q:>5} → {thick_q:<5} "
        f"{pooled(lambda r: r[1], 'on_target'):>7} → {pooled(lambda r: r[2], 'on_target'):<6} "
        f"{pooled(lambda r: r[1], 'grounded'):>7} → {pooled(lambda r: r[2], 'grounded'):<6}"
    )
    # Absolute counts, because the rates share no denominator: thickening changes how many
    # questions are generated, so "the rate fell" and "there are fewer good questions" are
    # different claims and only the second one is bad.
    for label, pick in (("baseline ", lambda r: r[1]), ("thickened", lambda r: r[2])):
        on = flags(pick, "on_target")
        gr = flags(pick, "grounded")
        print(
            f"  {label}: {len(gr):>2} questions, {sum(on):>2} on-target, "
            f"{sum(gr):>2} grounded, {len(gr) - sum(gr):>2} ungrounded"
        )
    print(
        "\nReading this: a concept with a small +chars could not test the hypothesis either\n"
        "way. Drift unchanged where +chars is large is the result that stops stage 2.\n"
        "Read the counts before the rates — more evidence generates more questions, so a\n"
        "rate can fall while the absolute number of good questions rises.\n"
        "Check that any large focus gain survives reading the questions themselves — the\n"
        "judge sees every target_concept passage as 'the target', so a bigger blob can move\n"
        "the rate without moving a question (design doc §6)."
    )
    return 0


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    trials = 1
    for flag in (a for a in argv[1:] if a.startswith("--trials=")):
        trials = int(flag.split("=", 1)[1])
    if args and args[0] == "thicken":
        return probe_thicken(args[1] if len(args) >= 2 else None, trials=trials)
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
