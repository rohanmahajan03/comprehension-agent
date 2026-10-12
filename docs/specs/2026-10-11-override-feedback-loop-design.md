# Closing the loop on answer overrides: triage, regression cases, and one measured fix

**Status: steps 0–2 BUILT 2026-10-11** (§8). Steps 3+ wait on a pilot with real users.

### What shipped

| File | |
|---|---|
| migration `e9a1c4d37b52` | `answer_overrides.required_points` (JSONB, `none_as_null`), `evaluator_model`, `question_kind`, all nullable and not backfilled |
| `routers/study_session.py`, both stores, `AnswerOverride` | fill and round-trip the three columns; `evaluator._MODEL` → public `evaluator.MODEL` so the router can snapshot it |
| `tests/override_corpus/` | `cases.py` (data model, anonymous key, hash split, invariants), `triage.py` (classifier + `propose`/`review`/`promote`/`judges` CLI), `calibration.py` (13 fixtures), `seeds.py` (synthetic cases from those fixtures) |
| `tests/override_geval/` | verdict-only suite over promoted cases (seeds opt-in via `OVERRIDE_GEVAL_SEEDS=1`), plus the billed triage calibration |
| `tests/points_geval/support.py` | `write_points()` factored out of `generate_points()` so both suites write points one way |
| `tests/test_override_geval_wiring.py` | free, 23 tests |

**First billed run (seeds + calibration, ~2 min):**

```
triage calibration   points_overreach 4/5   paraphrase_missed 3/4   override_invalid 3/4
synthetic seeds      14/17
```

- **Triage passes its 0.6 bar on every category**, and its misses are worth reading. Two
  are the concise replication-lag answer ("the system hasn't synced yet"), which is the
  borderline case every judge in this repo has struggled with: an explicit ruling calls it
  correct, and the classifier sided with the grader both times. The third goes **the
  dangerous way.** It read the async answer that is missing acknowledgement as a paraphrase
  and sided with the student on an answer the rulings fail. That's the §2 leniency drift
  appearing in the triage step itself, and it's why proposals are never promoted without a
  human ruling.
- **All three seed misses are one finding.** Rule 10 still writes slewing and cross-machine
  points for the clocks question, which is the over-requiring pattern `points_geval`'s first
  run reported. It's still reproducible and it's the obvious first target for §6. The three
  seeds share one question and one regenerated point set, so the failures are correlated:
  per-case rates over-count findings that share a question, and §6's report should say how
  many distinct questions are behind a number.
**Builds on:** `docs/specs/2026-09-18-manual-answer-override-design.md` (the capture side —
this is its §8, "out of scope", taken up).

## 1. Goal

`answer_overrides` is the only real misgrade data the project has. `eval_geval`'s 42 variants
are hand-written fixtures, and `points_geval`'s rulings are decisions about those same
fixtures. Every row in `answer_overrides` is a student saying the grader got it wrong on a
question the pipeline actually generated. Today nothing reads those rows as data.

The deliverable is one complete loop, shown end to end:

1. **Triage.** Each override gets a failure category and the component it blames, proposed
   by an LLM and confirmed by a human.
2. **Promote.** Each confirmed ruling becomes a permanent regression case, whether the
   student was right or wrong.
3. **Fix.** One prompt or rubric change, picked by what the triage shows is most common,
   that flips the confirmed misgrades without regressing `eval_geval`, `points_geval`, or
   the rejected overrides.

The point is the loop, not the size of the fix. A small fix with honest before/after numbers
on a held-out split is the result to aim for.

## 2. What this corpus can and cannot tell you

These limits shape every later section, so they come first.

- **It sees only one direction of error.** Students override answers graded *incorrect*.
  Nobody disputes a lenient pass. So the corpus measures false negatives (too strict) and
  is blind to false positives (too lenient), which is exactly the failure `eval_geval`'s
  ACID vague-definitions case shows. A loop fed only by overrides pushes the grader toward
  leniency, run after run. **§6's regression gate is the counterweight, and it is not
  optional.**
- **The person filing it has a stake in the outcome.** An override is a claim, not a label.
  Some overrides will be wrong: the student really did miss a required point. Those are as
  valuable as the right ones (§5), but only after a human has ruled on them. An LLM triage
  pass proposes; it never decides.
- **It may be nearly empty.** There have been no real users so far. §7 deals with cold
  start. The pipeline can be built and tested against seeded rows, but the *demonstration*
  needs real overrides. Synthetic ones prove the plumbing works, not that the loop does.

## 3. Stage 0: close the snapshot gap

The override row snapshots `question_prompt`, `expected_answer_notes`, `student_answer`,
`evaluator_explanation`, and `student_note`. **It does not snapshot `required_points`**,
and since the leniency work, `required_points` is what the evaluator actually grades
against. `expected_answer_notes` is only labelled `MODEL ANSWER:` and used to interpret the
points. A misgrade can't be reproduced without the rubric that produced it, and the join
back to `questions` is exactly what the no-FK design gives up once the document is deleted.

Add, in one migration:

| column | type | why |
|---|---|---|
| `required_points` | JSONB, nullable | the actual rubric at grading time. `NULL` for overrides written before this migration; `[]` is meaningful (a diagnostic probe or a pre-points question, where the evaluator chose the points itself) |
| `evaluator_model` | text, nullable | so a case graded by `claude-haiku-4-5` isn't silently compared with a later model's grade |
| `question_kind` | text, nullable | `pipeline1` / `diagnostic`, read from `is_diagnostic_question_id` at write time. Diagnostic probes come from `diagnoser.py`, not `question_generator`, which changes which component a misgrade blames |

Wire it through `AnswerOverride`, both stores, and `override_answer()`. Extend
`test_answer_override.py`'s field-by-field snapshot test and `test_postgres_store.py`'s
round trip. **Do this first, even if the rest waits:** every override captured before it
lands is missing the field that explains it.

## 4. Stage 1: triage

### Why a fixed taxonomy, not clustering

The proposal said "cluster". At realistic volume (tens of rows, not thousands), unsupervised
clustering over embeddings gives groups with no name and no owner. What the fix step needs
is a label that points to **a component to change**. So the LLM *classifies* into a fixed
taxonomy, and "clusters" are just the counts per label.

| category | meaning | component it blames |
|---|---|---|
| `points_overreach` | a required point demands something the question didn't ask for, or bundles an optional idea with an essential one | `question_generator` rule 10 |
| `paraphrase_missed` | the student expressed the point in different words and the evaluator didn't credit it | `evaluator` prompt |
| `type_misread` | graded as the wrong question type, e.g. an `open_ended_example` held to one specific example | `evaluator` or `question_generator` (decided per case) |
| `rubric_wrong` | the model answer or points are factually wrong or unsupported by the chapter | `question_generator` |
| `probe_unanswerable` | a diagnostic probe whose rubric the student couldn't reasonably meet | `diagnoser` |
| `override_invalid` | the evaluator was right; the student missed something required | none (it becomes a guard case, §5) |
| `unclear` | can't be decided from the snapshot | none (excluded) |

`points_overreach` is listed first on purpose. `points_geval`'s first run found all three
of its misses over-requiring, with bundled points as the main pattern. The prediction is that
real overrides will show the same thing. If they don't, that's a finding in its own right.

### Mechanics

`backend/tests/override_corpus/triage.py`, run as a module like the existing probes:

```bash
cd backend && set -a && source ../.env && set +a && \
  .venv/bin/python -m tests.override_corpus.triage propose   # LLM pass → proposals.jsonl
.venv/bin/python -m tests.override_corpus.triage review      # interactive confirm/edit → rulings.jsonl
```

- `propose` reads `Store.list_answer_overrides()` (already exists and is unused), skips rows
  already in `rulings.jsonl`, and asks `claude-opus-4-5` for `{category, component,
  rationale, quoted_point}` under a JSON schema. Opus because, as with the other judges, it
  shouldn't be the model whose output it's judging. `quoted_point` is the specific required
  point at issue, quoted from the snapshot, so the human can verify the claim in seconds.
- `review` shows the snapshot, the proposal, and the student's note, and takes
  accept / change category / reject. **The human's ruling is the only thing that gets
  promoted.** Record whether the proposal was accepted unchanged: the agreement rate between
  the proposed and confirmed category is the triage classifier's own accuracy, measured for
  free.
- The triage prompt must not reuse rule 10's or the evaluator's wording, for the same reason
  the points judge doesn't: a classifier that shares the generator's instructions shares its
  blind spots.

### Calibrate before trusting

Same discipline as the points judge: before running triage on real rows, build ~10 fixtures
from `points_geval`'s calibration perturbations (a *bundled* point is a known
`points_overreach`, a *thinned* set paired with its ruled-incorrect answer is a known
`override_invalid`) plus hand-written `paraphrase_missed` cases. Add a `probe judges`-style
command. Proposals only need to be good enough to speed up review, not to be trusted on
their own, so the bar is lower than the points judge's. But one that always says
`points_overreach` is useless, and only fixtures would reveal that.

## 5. Stage 2: promote rulings into a regression suite

### A new suite, not new files in the old ones

`eval_geval` cases need hand-derived G-Eval `criteria` and hardcoded `evaluation_steps` per
question (`criteria.py`). They can't be generated automatically, and pretending otherwise
would undercut the rule that file exists to enforce. `points_geval` regenerates the points,
which is the wrong thing to hold fixed when the case blames the evaluator. So:

**`backend/tests/override_geval/`**: data-driven, verdict-only, no judge. It has the same
shape as `points_geval`'s ruling check, which is the cheapest billed suite that touches the
evaluator.

- `cases.jsonl` is written by `triage.py promote` from confirmed rulings, one line per case:
  the snapshot fields, the confirmed category and component, and the **expected verdict**.
- **Every confirmed ruling becomes a case, in both directions.** A confirmed misgrade
  expects `correct: true`. A confirmed `override_invalid` expects `correct: false`. That
  second set is the only real-user evidence the project will ever have about *where the
  bar should stay*, and it's the in-corpus counterweight to §2's leniency drift. Treat it as
  equally important.
- Test parametrization by case id. A case whose component is `evaluator` grades against its
  **snapshotted** `required_points` (the rubric is held fixed, the evaluator is under test).
  A case whose component is `question_generator` regenerates points the way `points_geval`
  does (the generator is under test) and then grades. That needs `question_type`, which
  isn't snapshotted: take it from triage (the reviewer sets it) rather than adding another
  column the app can't fill.
- **Split, fixed at promotion time.** Each case is assigned `split: tune | holdout` by a
  stable hash of its override id, roughly 50/50. Fixes are developed against `tune` only;
  `holdout` is reported, never iterated on. The points judge's calibration already ran into
  why this matters: with no held-out set, tuning to the fixtures makes the score measure the
  tuning.
- Terminal summary in the house style: rates split by direction (misgrades flipped,
  invalid overrides still failing) and by split, and each failing case printed with its
  points, since those are what a failure has to be read against.
- `tests/test_override_geval_wiring.py`: the free smoke test, driving the suite with a fake
  evaluator, plus fixture invariants (every case has a verdict and a split, no duplicate
  override ids, `required_points` present for every `evaluator`-component case).

### Privacy: the corpus contains student writing

`cases.jsonl` holds real student answers and notes, copied into a repository. Before
committing any real case: anonymize (`study_session_id` → hash, drop `created_at`), and
**get permission from whoever wrote it** (§7's pilot is the natural place to ask). If
permission isn't given, keep `cases.jsonl` gitignored and commit only the aggregate numbers.
The suite has to work either way; this decides what's public, not what's measured.

## 6. Stage 3: one fix, and the gate it has to pass

Choose the target from the triage counts: the category with the most confirmed misgrades in
`tune`. If the prediction in §4 holds, that's `points_overreach` and the change is to rule 10.
Otherwise it's the evaluator prompt. One category, one change, so the before/after is
attributable.

**Acceptance gate.** Every line has to hold, measured as the mean of **3 runs** per suite,
because `temperature=0` isn't deterministic across these models (CLAUDE.md records ±1 fixture
of noise on the points judge and a run-to-run flip on clocks):

| check | bar |
|---|---|
| `override_geval` misgrades, `tune` | majority flip to correct (the fix works on what it was built for) |
| `override_geval` misgrades, `holdout` | improves over baseline, reported with its n (the honest number) |
| `override_geval` `override_invalid` cases, both splits | **no new passes** (the fix didn't buy leniency from the cases where the bar was right) |
| `eval_geval` | ≥ 40/42 and no ruled-incorrect variant newly passing |
| `points_geval` | 28/28 ruled-incorrect answers still fail; ruled-correct misses don't increase |

The asymmetry is deliberate: the gate is stricter in the lenient direction because §2's
corpus pushes that way. Report the result as a before/after table across all five rows,
including any that got worse. A fix that improves `tune` and does nothing on `holdout` is a
finding worth writing up, not one to hide.

**Cost per evaluation of a candidate fix**, roughly: `points_geval` ~2.5 min, `eval_geval`
~6 min / $0.40, `override_geval` (Haiku only, n small) under a minute; ×3 runs. That's about
half an hour per candidate. Iterate with a `probe case <override_id>` command (same pattern
as the diagnoser and evidence probes) and run the full gate only on a finalist.

## 7. Cold start: getting real overrides

The loop is only convincing on real data, and the corpus is probably near empty. Plan:

- **Pilot.** 5–10 students, one or two chapters they're actually studying, `DATABASE_URL`
  set so overrides persist (`InMemoryStore` loses them on restart). This needs a deployed
  instance; there's no auth, so share it privately. Ask for case-promotion permission (§5)
  up front. Target **~30 overrides**: fewer and the `holdout` split is too small to say
  anything.
- **Stage 0 must ship before the pilot.** Overrides captured without `required_points` can
  be triaged but not reproduced.
- **Seed rows for development only.** Build and test triage/promotion against a handful of
  synthetic overrides generated from `points_geval`'s observed misses (its first run gave
  three real over-requiring cases on real generated points). Mark them `synthetic: true` in
  `cases.jsonl` and exclude them from every reported number.

## 8. Build order

| step | billed? | depends on |
|---|---|---|
| 0. snapshot migration + tests | free | — |
| 1. `override_geval` suite + wiring test, against seeded cases | free (wiring) | 0 |
| 2. triage `propose`/`review`/`promote` + calibration fixtures | ~10 Opus calls | 0 |
| 3. pilot, collect ~30 overrides | — | 0 deployed |
| 4. triage the real corpus | ~30 Opus calls + human time | 2, 3 |
| 5. baseline: all three suites ×3 | ~$1.50, ~30 min | 1, 4 |
| 6. one fix + gate | ~30 min per candidate | 5 |
| 7. write-up: triage distribution, before/after table, triage agreement rate | — | 6 |

Steps 0–2 can be done now. Everything after step 3 waits on users.

## 9. Out of scope

- **A review UI or read endpoint.** Triage is a CLI on purpose; the reviewer is one person.
- **Automated prompt optimization** (DSPy-style search over prompt variants). With ~15
  tuning cases it would overfit immediately, and a hand change the triage justifies is
  easier to explain than one found by search.
- **The lenient direction from live traffic.** The real fix for §2's blind spot is an
  online audit: sample a few percent of *passing* grades and have a judge flag likely false
  positives. That's the natural next design after this one, and it reuses the triage
  taxonomy. It's left out here because it needs volume the pilot won't have.
- **Diagnostic probes as `points_overreach`.** Probes have no `required_points`, so a
  misgraded probe is either `paraphrase_missed` or `probe_unanswerable`. Teaching
  `diagnoser.py` to write points is its own change.
