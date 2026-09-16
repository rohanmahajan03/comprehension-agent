# Test strategy for the concept-evidence pipeline (`evidence_finder.py`)

**Status: BUILT 2026-09-16.** All three tiers plus the probe. Live run below.
**Subject:** `backend/app/services/evidence_finder.py` — `find_evidence()`,
`find_edge_evidence()`, `_propose_raw_evidence()`, shipped 2026-09-14
(`docs/specs/2026-09-13-concept-evidence-generation.md`).

**Why now:** it is live on the graph-review path, it makes real LLM calls, and **its own
function body is executed by no test in the repo.** Every reference to it in `tests/` either
monkeypatches it (`stub_evidence_finder`) or patches it to raise. `text_match.verbatim_only()`
is well covered; the code in `find_evidence` that *calls* it — deciding `found`, counting
`dropped`, clearing the summary — has never run under test, free or billed.

### What shipped

| File | |
|---|---|
| `app/services/evidence_finder.py` | `_MAX_QUOTES` now **enforced in code**, applied after the verbatim filter; trimming is deliberately not counted in `dropped` |
| `tests/test_evidence_finder.py` | Tier 0 — 16 tests against a fake client |
| `tests/evidence_geval/{golden,support,conftest,test_case3,probe}.py` | Tiers 1 and 2 |
| `tests/test_evidence_geval_wiring.py` | Free smoke test, 5 tests |

**Live run, second attempt — 9/9 passing (165s, all `claude-haiku-4-5`):**

```
span accuracy    0.83  (>= 0.75)     found recall     1.00  (>= 0.8)
explanatory      0.87  (>= 0.7)      summary supported 1.00  (>= 0.8)
dropped rate     0.00  (prompt health — no bar)
false positives  0     (zero tolerance)    non-verbatim raw 0  (zero tolerance)
edges            0 missed, 0 invented, 0 non-verbatim
```

**Every zero-tolerance check held on the first run and the second.** All six negative concepts
came back `found: false`; no quote the model returned was non-verbatim; no edge was invented.
The prompt is doing what §2 #5 hoped — `dropped` is 0.00, so the verbatim filter is a safety net
that has not had to catch anything.

**The four surviving off-target quotes are genuine model errors**, spot-checked individually:
`log_segment` twice returned compaction's passage, `sstable` returned the memtable paragraph,
and `b_tree` returned the write-ahead-log paragraph. That is failure #1 occurring at ~17% —
exactly the rate nothing previously measured.

### Two corrections the build produced, both worth keeping

**The first run's numbers were partly wrong, and the fixtures were at fault.** Span accuracy
came in at 0.70 with six off-target quotes; three were labelling gaps, not model errors — the
chapter's closing LSM-tree/B-tree comparison was labelled for nobody, and one `lsm_tree` anchor
was a single sentence where the model returned that sentence plus its continuation, failing
containment. Fixed in `golden.py` with the reasoning recorded inline. **Triage each failure
against the raw output before believing a rate**; two of the other three suites carry the same
warning.

**`probe judges` caught a miscalibration on its first run, and then a second one.** Its initial
fixture expected "This in-memory tree is sometimes called a memtable" to be explanatory; the
judge disagreed, and **the judge was right** — "This" has no antecedent inside the quote, so
judged alone it defines nothing. The fixture was corrected rather than the prompt loosened.
Then the live run exposed the reverse error: the judge was rejecting pure-limitation passages
("the hash table must fit in memory; range queries are not efficient") even though its own
criteria listed "what it costs, or what it cannot do" as explanatory. The prompt was made
explicit, and two fixtures were added — a limitation passage that must pass, an
attribution-only passage that must still fail — so the loosening is pinned in both directions.
Explanatory went 0.65 → 0.87 across that change, with the name-drops still being rejected.

**Note on the two 1.00s.** `summary supported` at exactly 1.00 is the reading this suite's own
doctrine treats as suspicious — indistinguishable from a judge that has stopped discriminating.
Here it is trustworthy specifically because `probe judges` shows that judge rejecting a
deliberately overreaching summary. That is the whole reason the probe exists; do not read a
1.00 without it.

---

## 1. Why this pipeline is not like the other four

Every other LLM service here produces **generated** text: a question, a rubric, a diagnosis, a
graph. There is no ground truth to diff against, so all three existing billed suites lean on a
judge model, and all three carry the same standing hazard — a judge that stops discriminating
makes the suite green while measuring nothing.

`evidence_finder` is **extractive**. The correct answer is a set of spans in a document we
already have, in full, at test time. That single fact should drive the whole strategy:

> **Push everything that can be checked against the document into deterministic checks, and
> spend a judge only on the two things that are genuinely interpretive.**

Two consequences worth stating, because they invert assumptions carried over from the other
suites:

- **Cheaper and faster.** Most of this suite is substring and offset arithmetic over one API
  call per fixture. No Sonnet generation, no Opus judging.
- **Largely immune to the non-determinism that just derailed the stage 0 probe**
  (`2026-09-15-stage0-probe-progress.md`: two identical runs disagreed by 0.21 on a judged
  rate). A judge's *opinion* of a varying output varies twice over; a substring check over a
  varying output varies once. "Is this string in the chapter" does not flap. That is why this
  work is a better use of effort than settling the probe, and it should be said plainly rather
  than discovered again.

## 2. The failure modes, ranked

Ranked by damage × how invisible it currently is — which is the order the suite should be built
in, not the order they appear in the code.

| # | Failure | Damage | Caught today? |
|---|---|---|---|
| 1 | **Wrong-concept quote** — verbatim, really in the chapter, but about a *neighbour* | Silently poisons the thing `source_quotes` exists to fix | **No. Nothing checks it.** |
| 2 | **False `found: true`** on a concept the chapter never teaches | Manufactures provenance for an idea the chapter doesn't support | No |
| 3 | **Name-drop quote** — in the chapter, about the concept, teaches nothing | Burns a passage slot; degrades questions quietly | No |
| 4 | **Over-cap** — more than `_MAX_QUOTES` returned | Crowds out neighbour context in the generator prompt | **No — the cap is prompt-only** (§3) |
| 5 | **Fabricated quote** — a paraphrase presented as source text | Would be severe, but `verbatim_only()` discards it in code | **Yes, structurally** |
| 6 | **False `found: false`** | Mild and self-correcting — the reviewer sees the notice and can re-scan | n/a |

**#1 is the headline.** A passage that is verbatim, contiguous, and genuinely in the chapter
passes every gate the code has — and if it is about a prerequisite rather than the target, it
feeds the generator exactly the neighbour-weighted evidence that
`question_geval`'s check 6 already measures going wrong. The one failure mode this feature was
built to *remove* is the one nothing currently detects in its own pipeline.

**#5 is the inverse case and shapes what to measure.** The verbatim filter means a fabricated
quote can't reach storage, so "does it leak" is not a useful test. The useful signal is the
**`dropped` rate on the raw seam**: how often the model *tried*. That is prompt health —
a rising `dropped` rate is the early warning that the prompt has decayed, visible long before
anything user-facing breaks.

## 3. Tier 0 — free, no API key (build first)

The largest gap, the cheapest to close, and it needs no fixtures. Drive the real
`find_evidence` / `find_edge_evidence` against a fake Anthropic client, the way
`tests/test_question_geval_wiring.py` already fakes `question_generator._client`.

What to pin — each is a branch that currently has no coverage:

| Case | Expected |
|---|---|
| Model returns all-verbatim quotes | `found=True`, all kept, `dropped=0` |
| Some quotes paraphrased | Those dropped, `dropped=N`, `found` stays `True` |
| **All quotes paraphrased** | **`found` flips to `False`, `summary` cleared, `dropped=N`** |
| Model returns `found=False` but non-empty quotes | Quotes ignored, `dropped=0` (not counted as discards) |
| Duplicate quotes | Deduped, order preserved |
| More than `_MAX_QUOTES` returned | **Decide — see below** |
| Edge: `found=True`, quote not verbatim | `find_edge_evidence` returns `None` |
| Edge: `found=False` | Returns `None` without consulting the quote |

The third row is the subtle one and the reason this tier matters: `found` is *recomputed* from
what survives verification rather than taken from the model, so a proposal whose every quote
was a paraphrase must come back as "found nothing". That is a deliberate hardening recorded in
the design doc, and nothing currently proves it works.

> **Decided: yes, and done.** (Kept below as written for the reasoning.) It was prompt-only (rule 6) while
> every other invariant in this service is code-enforced — verbatim by `verbatim_only()`,
> `found` by recomputation. **Recommend enforcing it** (truncate after filtering, so the cap
> counts surviving quotes rather than attempted ones) and pinning it here. A prompt-only
> constraint in a service whose entire design principle is "verify, don't ask" is an
> inconsistency, and §2 #4 is a real cost — passage slots crowd out the neighbour context the
> generator also needs.

## 4. Tier 1 — billed, deterministic ground truth (`tests/evidence_geval/`)

The core of the suite, and **almost none of it needs a judge.**

### Span-labelled fixtures

For each concept in the fixture chapter, hand-label the character ranges of the source text
that are legitimately *about that concept*. Then every returned quote can be located by offset
and checked against those ranges.

Store labels as **verbatim anchor strings resolved to offsets at import**, not as raw integer
offsets — the same trick `tests/question_geval/probe.py` uses for its thickening fixtures, with
an import-time assertion. Integer offsets silently rot the moment anyone reflows the source
text in `graph_golden_set.md`; anchors fail loudly.

### The checks, all deterministic

| Check | How |
|---|---|
| **Span accuracy** (failure #1) | Every returned quote falls inside a region labelled for *this* concept |
| Verbatim rate | Every raw quote from `_propose_raw_evidence()` is in the chapter; report the `dropped` rate as prompt health |
| Found-precision (failure #2) | **Zero tolerance.** Negative fixtures must return `found=False` |
| Found-recall | Positive fixtures return `found=True` with ≥1 quote. Loose threshold |
| Contiguity | Each quote is one unbroken run — already implied by the substring check, assert it explicitly so a future "stitch the pieces" refactor fails |
| Cap adherence | ≤ `_MAX_QUOTES` (or redundant, if §3's recommendation is taken) |
| Edge evidence | Linked pairs return a quote inside a region labelled for *both*; unlinked pairs return `None` |

**Span accuracy is the point of this design.** It converts the highest-priority, currently
undetected failure into arithmetic — no judge, no calibration hazard, no run-to-run opinion
drift. It is available only because the output is extractive, which is exactly the property §1
says to exploit.

### Negative fixtures

Verified absent from the Case 3 source text by substring search, each topically adjacent enough
to tempt a model matching on subject rather than content: **replication**,
**partitioning/sharding**, **consensus**, **secondary indexes**, **transactions**,
**column-oriented storage**.

Check any new negative the same way before trusting it. Case 3 covers more than its title
suggests — B-trees, write-ahead logs, Bloom filters and write amplification are all in there,
and an earlier draft of the parent spec proposed `b_tree` as a negative, which is wrong.

## 5. Tier 2 — judged, and only these two things

| Check | Why it can't be deterministic |
|---|---|
| **Explanatory vs name-drop** (failure #3) | "Does this passage teach the concept" is a judgment about pedagogy, not about text location |
| **Summary faithfulness** | Does the proposed `summary` overreach the quotes it was drawn from? Entailment, not matching |

Both are binary plus one sentence — deliberately weak, like `question_geval`'s evidence-basis
judge. Ship a `probe judges` mode alongside them from day one, with fixed known-good and
known-bad inputs, and re-run it after any judge-prompt edit. Two judges is a small enough
surface that this stays cheap, and the hazard is on record twice in this repo.

Summary faithfulness has a known live subtlety worth encoding as a fixture: when some quotes
are dropped as non-verbatim, the surviving `summary` was written against the full pre-filter
list, so it may rest partly on text that isn't in the chapter. The service's docstring
acknowledges this and leans on human review. A fixture should pin how bad it can get.

## 6. Fixtures: do not use only Case 3

**What a "fixture chapter" is here.** `backend/tests/graph_golden_set.md` holds four DDIA
excerpts in fenced blocks. `tests/graph_geval/golden.py` parses the text straight out of that
markdown (never duplicating it) and pairs each with hand-curated expected concepts, edges and
forbidden ideas as a `GoldenCase`. `graph_geval` runs all four; `question_geval` uses Case 3
alone; this suite would add its own span labels on top of the same objects.

**Three more already exist — no new source text needs writing:**

| Case | Size | Concepts | Density | What it stresses |
|---|---|---|---|---|
| `case3_storage_engines` | 4.1 KB | 11 | 2.7 /KB | The baseline. Already used by `question_geval`. |
| `case1_partitioning` | **7.5 KB** | 13 | 1.7 /KB | **Length** — 84% more text to search |
| `case2_transactions_acid` | 4.7 KB | **15** | **3.2 /KB** | **Confusability** — the densest, and the nastiest (below) |
| `case4_oltp_olap` | 3.8 KB | 12 | 3.1 /KB | Similar to Case 3; least additional value |

**Two different things make failure #1 likely, and they are not the same axis:**

- **Length.** More text means more passages that plausibly match on topic. `case1_partitioning`
  is the test for this.
- **Confusability.** More closely-related concepts *in adjacent prose* means the right and
  wrong passages sit next to each other. `case2_transactions_acid` is the test for this, and it
  is the sharper one: its concepts include `dirty_read`, `dirty_write`, `read_skew`,
  `read_committed` and `snapshot_isolation` — a set explained in one continuous stretch of
  text, in near-identical vocabulary. A scan for `dirty_write` that returns the sentence about
  `dirty_read` is verbatim, contiguous, on-topic, and **wrong**, which is exactly the failure
  nothing currently detects. `graph_geval` already records that its extractor folds several of
  these together, so the confusion is demonstrated rather than hypothesised.

**Recommend Case 2 as the second fixture, then Case 1.** Case 2 targets the higher-priority
failure and costs less to label (4.7 KB); Case 1 adds the length dimension afterwards. Case 4
is close enough to Case 3 in size and shape to be worth skipping unless the others come back
clean.

**One caveat when the suite spans more than one chapter: negative fixtures are per-chapter, not
global.** §4's list is verified absent *from Case 3* — but `replication`, `secondary_index` and
`partitioning` are Case 1 concepts, `transaction` is a Case 2 concept, and
`column_oriented_storage` is a Case 4 concept. Reusing Case 3's negatives against another
chapter would assert `found: false` for something that chapter genuinely teaches, and the
suite would fail on correct behavior. Verify each negative against the chapter it's used with,
by substring search, exactly as §4 says.

## 7. Explicitly out of scope

- **Re-testing `text_match`.** Covered free and thoroughly in `tests/test_text_match.py`.
- **Judging whether a quote is "good evidence" in the abstract.** Only the two questions in §5.
- **The stage 0 non-determinism question.** Deferred
  (`2026-09-15-stage0-probe-progress.md`); §1 explains why deterministic checks largely absorb
  it here rather than needing it resolved first.
- **End-to-end "do better quotes produce better questions".** That is the parent spec's stage
  1a, deferred. This suite tests whether the *extractor* does its job, which is a prerequisite
  question and answerable on its own.

## 8. Sequencing

| Step | Cost | Why this order |
|---|---|---|
| Tier 0 | Free, hours | Closes a live gap with no fixtures needed; also settles the `_MAX_QUOTES` decision |
| Tier 1 on Case 3 | ~20 Haiku calls | Proves the span-label harness on the chapter already labelled for `question_geval`, before spending labelling effort on a second |
| **Second fixture chapter** (§6) | Labelling effort only — no new source text | See below |
| Tier 2 | 2 judges + probe | Last: the interpretive layer is worth least and costs most to keep honest |

**On the third row.** "Second fixture chapter" means: take one of the three DDIA excerpts that
*already sit* in `backend/tests/graph_golden_set.md` alongside Case 3 — parsed and
concept-labelled already by `tests/graph_geval/golden.py` — and add this suite's own span
labels to it, so tier 1 runs against two chapters instead of one. No prose needs writing and no
golden concepts need deriving; the work is marking which character ranges of that chapter are
legitimately about which concept, the same job §4 describes for Case 3.

It is a separate step rather than part of tier 1 because span labelling is the only genuinely
manual effort in this plan, and it is worth doing twice only once the harness has proved itself
on the chapter that is already labelled.

**Why it matters enough to be on this list at all:** Case 3 is 4 KB with 11 concepts, and a
suite that only ever sees it will report excellent span accuracy while saying nothing about the
condition the feature ships into — a real chapter, where several sections discuss related ideas
in near-identical language. §6 recommends `case2_transactions_acid` first, because its
`dirty_read`/`dirty_write`/`read_skew` cluster is the closest thing in the golden set to the
production failure this suite exists to catch.

## 9. Open decisions

- ~~**Enforce `_MAX_QUOTES` in code?**~~ Done — enforced after the verbatim filter, pinned by
  two tier 0 tests.
- **How much of the second chapter to label** — §6 now answers *which* (Case 2, then Case 1),
  but not whether every concept in it needs labelling or just the confusable cluster.
- **Threshold for span accuracy.** Set loose on first observation, per `diagnoser_geval`'s
  note — with ~11 positive fixtures one flip is ~9 points, so a threshold set flush against a
  first run is a flake generator. Found-precision stays at zero tolerance regardless.
