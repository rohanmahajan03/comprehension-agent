# Concept evidence: measurement, then generalization — design

**Status:** proposed (nothing built)
**Picks up from:** `docs/specs/2026-09-13-concept-evidence-generation.md`, implemented
2026-09-14, which added `Concept.source_quotes` and filled it for **hand-added** concepts via
`evidence_finder.py`.

**Scope:** the three things that document deliberately left open, in the order they should
happen — a premise probe, then measurement of the mechanism that shipped, then extending it to
extracted concepts (its §9). Each stage gates the next, and the whole point of the sequencing
is that **stage 2 is the expensive, risky one, and stages 0 and 1 exist to decide whether it is
worth doing at all.**

## 1. Why this is a separate document

The evidence pass shipped with a gap its own §8 names: *"nobody has yet shown that a concept
with `source_quotes` gets better questions than one without."* The mechanism is built,
live-verified, and unmeasured. Meanwhile the problem it was ultimately aimed at — questions
drifting onto a concept's neighbours, `question_geval` check 6 at **0.86, 4 of 28 off-target**
— is entirely a problem with *extracted* concepts, which the pass never touches.

So there are two distinct open questions, and they are easy to conflate:

1. **Does more target evidence reduce drift?** An untested hypothesis about
   `question_generator`'s behavior. Cheap to test.
2. **Can `graph_builder` produce that evidence at extraction time?** An engineering question
   about the one service every other stage depends on. Expensive, and pointless if (1) is no.

The previous document answered neither and said so. This one sequences them.

## 2. What is actually known

| | Status |
|---|---|
| Hand-added concepts reach the generator with 1 passage | **Measured** (previous doc §1) |
| `source_quotes` reach the generator as separate `target_concept` passages | **Built + unit-tested** (`test_question_generator.py`) |
| `evidence_finder` returns verbatim quotes, and `found: false` when it should | **Spot-checked live**, one excerpt, three concepts. No suite. |
| Extracted concepts drift onto neighbours | **Measured**: check 6, 0.86, 4/28 |
| Drift is *caused* by thin target evidence | **Hypothesis.** Never tested. |
| A prompt rule fixes drift | **Tested and false** — rule 10 moved 0.86 → 0.85 while knocking evidence basis 0.94 → 0.82 |
| `source_quotes` improve any generator metric | **Unknown** |

The last row is the one everything else waits on.

## 3. Stage 0 — the premise probe (~8 calls, seconds)

Carried over verbatim from the previous document's §9, which called it "the cheapest thing on
this page" and said it gates the most work. It is still not built and should be first.

**Build `tests/question_geval/probe.py`**, copying `tests/diagnoser_geval/probe.py`'s shape (a
runnable module, not a test — that file's docstring explains why a full suite run is the wrong
instrument for "did my change help?").

```
python -m tests.question_geval.probe thicken write_ahead_log
python -m tests.question_geval.probe thicken          # all four drifting concepts
```

For one concept, generate its questions twice — once from the graph exactly as
`golden.build_graph()` produces it, once with **hand-picked verbatim passages from the Case 3
source text added as `source_quotes`** — and run both sets through `judge_target_focus` and
`judge_evidence_basis`. Print the questions side by side, not just the rates: with three or
four questions per variant the rates are coarse, and the actual question text is what says
whether a drifting question moved back onto its target.

**The quotes are hand-picked on purpose.** That is what separates question (1) from question
(2) in §1: the probe must test whether *more target evidence helps*, with no dependence on
whether `graph_builder` can find it. If the probe used `evidence_finder` to source them, a
negative result would be ambiguous between "the hypothesis is wrong" and "the scan picked bad
passages."

**Run all four drifting concepts** (`write_ahead_log`, `compaction`, `bloom_filter`,
`hash_index`), not just one. Each contributes three or four questions, so a single concept is
a sample of three or four binary judgments — one flip is 25-33%. Four concepts is still under
ten generation calls.

**Reading the result:**

- *Drift drops, evidence basis holds.* The hypothesis survives. Proceed to stage 1.
- *Drift drops, evidence basis falls.* A trade, not a win. Look at which questions became
  ungrounded — more passages meaning looser citation is a different failure from the one being
  fixed, and it would show up again at scale in stage 2.
- *Drift unchanged.* **Stop.** The thin-evidence hypothesis is wrong, stage 2 has no
  justification, and both this document and the previous one's §9 need rethinking. This is the
  outcome the probe exists to catch cheaply, and it should be treated as a real possibility
  rather than a formality — the one prompt-level fix that was tried for this also failed.
- *Drift gets worse.* Worth understanding before anything else: the most likely mechanism is
  §6's judge-contamination problem, and it would invalidate check 6 as an instrument.

## 4. Stage 1 — measure what shipped

Two independent pieces. 1a decides whether stage 2 is worth its cost; 1b covers a service
that is live and untested today, which stays true whatever the probes say.

### 1a. The `question_geval` A/B (~2 full runs, one time)

Stage 0 tests four concepts with hand-picked quotes. This tests all eleven, and reports every
metric rather than two.

**Add a `ab` mode to the same probe**, not a second test file. This is a one-time decision
instrument, not a regression detector: the permanent end state (if stage 2 ships) is that
`question_geval`'s golden concepts simply *have* `source_quotes`, because that is what
production produces — a permanent second suite would double every future run's cost to
re-answer a question already settled.

Two mechanical notes for whoever builds it:

- **`support.score_case()` is `lru_cache`d with no arguments.** It assumes one case and one
  graph. The A/B needs it parameterized — `score_case(with_quotes: bool = False)`, cache keyed
  on the flag — and `golden.QuestionGoldenCase.build_graph()` needs the same flag, folding in a
  new `_SOURCE_QUOTES: dict[str, list[str]]` table. Keep the existing no-arg behavior as the
  default so `test_case3.py` is untouched.
- **`_SOURCE_QUOTES` entries must be verbatim** slices of the Case 3 source text in
  `tests/graph_golden_set.md` — unlike `_CONCEPT_TEXT`'s summaries, which that file's docstring
  explicitly allows to be close paraphrases. Assert it at import with
  `text_match.is_verbatim()`, the same way `build_graph()` already asserts its edge structure
  hasn't drifted from `graph_geval`. A golden fixture that isn't verbatim would be testing a
  shape production cannot produce.

**Report all six checks both ways.** Type recall and target focus are the two expected to
move; evidence basis, answer quality, source-citation and expected-answer gradeability are
there to catch the cost. The interesting failure is a rise in type recall paid for with a fall
in evidence basis — more passages letting the model reach for types the evidence still doesn't
really support.

### 1b. An `evidence_finder` regression suite (`tests/evidence_geval/`)

`evidence_finder` is the only service making real LLM calls with no billed suite. What it
would grade, in the shape of the existing four:

- **Verbatim rate**, deterministic, on the `_propose_raw_evidence()` seam rather than on
  `find_evidence()`. Post-filter the rate is 1.00 by construction, which measures nothing; the
  seam exposes what the model actually returned, so the real number is how often it needed
  filtering at all. A `dropped` rate creeping up is the early warning that the prompt has
  stopped working, long before anything user-visible breaks.
- **Found-recall**: concepts the excerpt genuinely teaches must come back `found: true` with at
  least one quote.
- **Found-precision, zero tolerance**: concepts the excerpt never teaches must come back
  `found: false`. This is the check that carries the weight, for the same reason
  `diagnoser_geval` asserts only the false-positive direction of its disclosure flag — a
  fabricated quote enters the pipeline as chapter provenance and nothing downstream can tell it
  from the real thing, whereas a missed one leaves prior behavior in place.

  The negative fixtures have to be chosen against the excerpt rather than by intuition: Case 3
  covers more than its title suggests, including B-trees, write-ahead logs, Bloom filters and
  write amplification, so the obvious-looking "a storage chapter wouldn't cover that" guesses
  are mostly wrong. Verified absent from the source text, and each topically adjacent enough to
  tempt a model pattern-matching on subject rather than content: **replication**,
  **partitioning/sharding**, **consensus**, **secondary indexes**, **transactions**, and
  **column-oriented storage**. Check any new fixture with a substring search before trusting
  it — this document's first draft proposed `b_tree`, which the excerpt teaches in full.
- **Explanatory quality**, LLM-judged: does each quote *explain* the concept — mechanism,
  purpose, what distinguishes it — or merely name it? This is prompt rule 3's target, and it is
  the thing that decides whether a quote is worth a passage slot downstream.
- **Edge evidence**: `find_edge_evidence` on pairs the excerpt does link (`compaction` /
  `log_segment`) and pairs it doesn't (`bloom_filter` / `append_only_log`), same
  precision-over-recall weighting.

Reuse `tests/graph_geval/golden.py`'s `CASE_3_STORAGE_ENGINES` for concept ids and labels, the
way `question_geval` already does, so a third suite can't disagree with the other two about
what the case contains. Include a `probe judges` mode from the start and re-run it after any
judge-prompt edit — `diagnoser_geval`'s docstring records that hazard twice over, and a judge
that has stopped discriminating is indistinguishable from a healthy pass at exactly 1.00.

## 5. Stage 2 — extracted concepts get `source_quotes`

Only if stage 0 says the hypothesis holds and stage 1a says the effect is real at scale.

### The choice: extend the extractor, or add a pass

**(a) Extend `graph_builder`'s schema** so `_extract_raw_graph()` returns `source_quotes` per
concept in the same call. Free in call count. But it loads a prompt that is already carrying
the concept-selection bar *and* the edge rules *and* a verbatim requirement it does not
currently meet — `graph_geval` sits at 8/16 with edge recall the weakest area and two edges
already quoting non-verbatim. It also changes the output shape of the one service every other
stage depends on, which is precisely the objection the previous document's §9 raised.

**(b) A second pass**: after `build_graph()`, call `evidence_finder.find_evidence()` once per
concept and fill `source_quotes` from what it returns, dropping proposals with `found: false`.

**Recommend (b).** The §9 objection is entirely an argument against (a) and evaporates under
(b): `graph_builder` is untouched, so `graph_geval` cannot regress, and the work is done by a
service that already exists, already enforces the verbatim rule in code, and has been checked
live. The cost is N extra Haiku calls per chapter — against N Sonnet question-generation calls
already being spent per chapter, that is noise. (a) is the option to revisit only if (b)'s
latency turns out to matter.

One consequence worth stating: under (b) the auto-fill and the review-mode "Find evidence"
button are **the same code path**, so a reviewer re-running the scan on an extracted concept
gets exactly what ingestion would have produced. Under (a) they would be two different
mechanisms that could silently disagree.

### Where it runs

At extraction time, on both paths — immediately after `build_graph()` in `upload_textbook`,
before the `review` branch. Not at finalize.

The reason is review mode's whole purpose: if the quotes exist by the time the review screen
loads, the reviewer **sees the evidence each concept will be questioned from and can prune it**,
which is strictly more valuable than the alternative and needs no new UI — `ReviewGraphPage`
already renders stored `source_quotes` and already has the per-row re-scan button. The cost is
that a concept the reviewer subsequently deletes wasted one Haiku call. That is a rounding
error, and it buys the human a look at the evidence before it grounds anything.

### Latency, and what not to do about it

N sequential Haiku calls added to ingestion. `generate_questions()` is already N sequential
Sonnet calls, so this follows existing precedent rather than setting a new one, and the Haiku
calls are the cheaper half. If ingestion latency becomes a real complaint, **parallelize both
loops together** — fixing this one alone would be optimizing the smaller cost while leaving the
larger one untouched.

### Then re-measure

Re-run `question_geval` and update its golden `_SOURCE_QUOTES` to what `evidence_finder`
actually produces for Case 3, rather than the hand-picked set stage 1a used — at that point the
suite is testing production's real shape. If target focus has genuinely risen, consider raising
`TARGET_FOCUS_THRESHOLD`, but read `diagnoser_geval`'s note on thresholds first: with 28
judgments one flip is ~3.5%, so a threshold set flush against observed performance turns a
regression detector into a flake generator. The per-question list the terminal summary prints
is the real detector; the threshold only catches a collapse.

## 6. What could go wrong in stage 2

**The judge could be measuring its own contamination.** This is the most important risk here
and the easiest to miss. `support._target_focus_context()` folds *every* `target_concept`-role
passage into the blob it shows the judge as "the target", and `source_quotes` land in exactly
that role. So a quote that happens to mention a sibling makes the sibling's subject matter part
of what the judge believes the target is about — and a question that drifts onto that sibling
now reads as on-target. **Check 6 could improve without any question improving.** Two
mitigations, both cheap: stage 0's side-by-side question printout, where a human reads the
actual questions; and, if the rate moves a lot, re-judging a handful of the previously
off-target questions in isolation — the `probe judges` pattern that has already caught a
miscalibrated judge twice in this project.

**Evidence basis could fall.** Every previous change to this prompt's inputs or rules has
destabilized it (rules 8–9, then rule 10 knocking it 0.94 → 0.82). More passages is a change to
its inputs. The mechanism to watch for: longer passage lists inviting looser citation, where a
question draws on four sources and is fully supported by none.

**Duplicate passages.** A concept's `source_quotes` may contain the same sentence that already
reaches the generator as a `prerequisite_link` quote on an edge into it, or as a sibling's
quote. `verbatim_only()` dedupes within one list, not across roles. The result is the same text
sent twice under two roles — probably harmless, possibly a nudge toward over-weighting it.
Worth a look at the assembled passage list for one concept before assuming it doesn't matter.

**Quote-hoarding by well-covered concepts.** `_MAX_QUOTES = 4` caps each concept, but a chapter
section that explains one concept thoroughly gives it four strong passages while a concept the
chapter treats in a sentence still gets one. The imbalance this whole line of work is about
could reappear *between* concepts rather than between a concept and its neighbours. Only
visible in the per-concept breakdown, not in the aggregate rate.

## 7. Backfill

Once stage 2 ships, a chapter ingested before it has permanently empty `source_quotes` and
quietly worse questions than an identical chapter ingested after. The previous document's §10
deferred this; it is now this document's call.

**Recommend still not building it**, but recording the reason rather than leaving it implicit:
those chapters are `FINALIZED`, their questions are already written and referenced by study
sessions and history entries, so a backfill that changed their evidence without regenerating
their questions would change nothing a student sees — and regenerating questions post-finalize
is explicitly out of scope (`2026-09-12-human-in-the-loop` §8, questions/sessions/history all
reference concepts by id by then). A backfill is therefore not a small job hiding behind a
migration; it is the post-finalize editing capability, which is a separate design. Re-uploading
the chapter is the supported answer.

## 8. Sequencing

| Stage | What | Cost | Gate |
|---|---|---|---|
| 0 | `probe thicken` on the four drifting concepts | ~8 calls, seconds | **Stop here if drift doesn't drop.** |
| 1a | `probe ab`, all 11 concepts, all six metrics | ~2 full runs, one time | Effect real at scale, no metric collapses |
| 1b | `tests/evidence_geval/` | new suite, run on demand | Independent — do it regardless |
| 2 | `evidence_finder` pass wired into ingestion | N Haiku calls per chapter | Stage 0 + 1a both positive |
| 2′ | Re-measure, update goldens, revisit thresholds | 1 full run | — |

Stage 1b is the only item not gated on anything: it covers a service that is live and untested
today, and that stays true whatever the probes say.

## 9. Out of scope

- **Changing `graph_builder`'s prompt or output schema.** Option (a) above, rejected for stage
  2. It stays available if (b)'s latency ever becomes the binding constraint.
- **Backfilling existing chapters.** §7 — it is the post-finalize editing capability wearing a
  disguise.
- **Proposing graph structure.** Unchanged from the previous document's §10: this line of work
  produces *evidence*, never edges. The human stays the authority on structure.
- **Parallelizing ingestion.** Named in §5 only to say that if it happens, both per-concept
  loops go together.
- **Raising `question_geval` thresholds as a goal.** A threshold is a collapse detector here,
  not a target; the per-case tables are what catch regressions.
