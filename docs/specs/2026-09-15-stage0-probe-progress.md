# Stage 0 premise probe — progress note (paused mid-experiment)

**Status: DEFERRED.** Probe **built and working**; experiment **run twice, inconclusive**; a
four-trial run to settle it was **killed by the OS (low memory) before producing any output**.
**Do not act on either run's numbers** — see §3.

**Why deferred:** the question this answers ("does more evidence yield better questions")
matters less right now than whether the evidence-generation service works at all, which no
test currently checks — see `docs/specs/2026-09-15-evidence-finder-test-strategy.md`. That work
also does not depend on this: its checks are deterministic, so the non-determinism recorded in
§3 here largely washes out rather than blocking it. Everything below stays valid and resumable;
§5 is the pick-up point.

**Belongs to:** `docs/specs/2026-09-14-concept-evidence-measurement-and-generalization.md` §3
(stage 0), which gates stages 1a and 2 of that document.

**Question being answered:** does giving a concept more of its own chapter evidence reduce
`question_geval` check 6's drift (questions that assess a neighbour rather than their own
concept)? Currently 0.86, 4 of 28 off-target.

---

## 1. What is built

Two files, **uncommitted** in the working tree (everything from the evidence-generation pass
itself is already committed in `fbd68ad` / `947d7d2`):

| File | State |
|---|---|
| `backend/tests/question_geval/probe.py` | New. Complete and exercised against the real API. |
| `backend/tests/test_question_geval_wiring.py` | +3 free tests covering the probe. All 5 pass. |

```bash
cd backend && set -a && source ../.env && set +a
PYTHONPATH=. .venv/bin/python -m tests.question_geval.probe thicken                  # all four concepts
PYTHONPATH=. .venv/bin/python -m tests.question_geval.probe thicken hash_index       # one concept
PYTHONPATH=. .venv/bin/python -m tests.question_geval.probe thicken --trials=4       # the unfinished one
```

**How it works.** For each of the four concepts `question_geval` recorded as drifting
(`write_ahead_log`, `compaction`, `bloom_filter`, `hash_index`) it generates questions twice —
once from the graph as `golden.build_graph()` produces it, once with hand-picked verbatim Case
3 passages attached as that concept's `source_quotes` — then runs both sets through
`judge_target_focus` and `judge_evidence_basis`.

Three design choices worth not re-litigating:

- **Quotes are hand-picked, not from `evidence_finder`.** This isolates "does more target
  evidence help" from "can a scan find it", so a null result blames the hypothesis rather than
  the scan. `_check_fixtures()` asserts all ten are verbatim at import, and a free test pins
  that.
- **Only the target concept is thickened**, so the neighbour imbalance genuinely changes.
  Production would thicken everything, making this an *upper bound* on the isolated effect.
- **Counts are printed alongside rates.** Thickening changes how many questions get generated,
  so a rate can fall while the absolute number of good questions rises — which is exactly what
  happened in run 1 and read as a regression until the counts were checked by hand.

## 2. The data so far

Both runs are single-trial, all four concepts, `temperature=0` throughout.

**Run 1**

```
concept                +chars            focus         grounded
write_ahead_log          +454    0.75 → 0.80      0.75 → 0.60
compaction               +432    0.50 → 0.80      0.75 → 0.80
bloom_filter             +380    0.67 → 1.00      0.67 → 0.67
hash_index               +385    0.75 → 1.00      1.00 → 1.00
POOLED                           0.67 → 0.88      0.80 → 0.76
```

**Run 2** — identical inputs, identical code path apart from added count reporting

```
concept             +chars    questions            focus         grounded
write_ahead_log       +454     4 → 5        0.75 → 0.80      0.75 → 0.80
compaction            +432     4 → 4        0.50 → 0.75      0.75 → 0.75
bloom_filter          +380     3 → 3        1.00 → 0.67      1.00 → 1.00
hash_index            +385     4 → 4        0.75 → 0.75      1.00 → 0.75
POOLED                        15 → 16       0.73 → 0.75      0.87 → 0.81
  baseline : 15 questions, 11 on-target, 13 grounded,  2 ungrounded
  thickened: 16 questions, 12 on-target, 13 grounded,  3 ungrounded
```

## 3. Why neither run is usable — this is the actual finding so far

**The two runs disagree, on identical inputs.** Pooled target focus moved **+0.21** on run 1
and **+0.02** on run 2. `bloom_filter` reversed outright: 0.67 → 1.00 on the first run,
1.00 → 0.67 on the second. Its baseline focus alone moved 0.67 → 1.00 between runs *with
nothing changed at all*.

`temperature=0` does not pin these calls, which is consistent with what this project has
already recorded twice: `evaluator.py`'s verdicts flip between calls on the same input, and
`question_generator` corrupted the same passage differently on each live run at `temperature=0`.

The arithmetic makes it worse. With ~15 binary judgments per variant, **one flipped judgment is
~7 points**. Run 2's entire +0.02 effect is one-third of a single judgment. For reference, the
prompt fix that was tried and correctly dismissed as noise (rule 10) moved target focus −0.01.

**So: the instrument's run-to-run spread is at least as large as the effect it is trying to
measure.** Run 1 in isolation looks like strong confirmation; run 2 in isolation looks like a
null result. Reporting either alone would be picking a conclusion.

One detail that survives both runs and is worth keeping: **`write_ahead_log` moved least**
(0.75 → 0.80 in both). That is the concept whose fixture deliberately includes
write_amplification's anchor sentence — the judge-contamination risk flagged in the design
doc's §6. If contamination were driving gains, WAL should have moved *most*. Weak evidence
against the contamination worry, not a clearance.

## 4. What was in flight when this stopped

`probe thicken --trials=4` — repeat the whole A/B four times and report mean and range of the
delta, so the effect can be compared against the noise floor. **Killed by the OS for low
memory after ~10 minutes, before writing any output.** The trials code path itself is written,
wiring-tested, and unexercised against the real API.

Likely cause of the OOM is machine pressure rather than the probe: the full docker stack
(postgres + backend + frontend) was running at the time. Before resuming:

```bash
docker compose down          # or at least stop frontend/backend
```

and consider `--trials=2` twice rather than `--trials=4` once, so a kill loses less. Each trial
is ~8 Sonnet generations + ~60 Haiku judge calls and takes roughly 8–10 minutes, so four trials
is ~40 minutes — it needs to run in the background with output tee'd to a file.

## 5. How to resume

1. Free memory (`docker compose down`), then run `probe thicken --trials=4`, tee'd to a file,
   in the background.
2. Read the `ACROSS N TRIALS` block, not the per-trial lines. The decision rule is already
   printed there: **a mean delta smaller than a range that straddles zero is the noise floor,
   not a result.**
3. Then apply §3's decision rule from the parent spec:
   - Mean focus delta clearly positive and range not straddling zero → hypothesis holds,
     proceed to stage 1a.
   - Mean near zero, or range straddling it → **stop; stage 2 has no justification**, and both
     the parent spec's §5 and `2026-09-13`'s §9 need rethinking.
   - Focus up but evidence basis consistently down → a trade; read the ungrounded questions
     before deciding.

If four trials still straddle zero, the honest read is not "run more trials" — it is that the
effect, if any, is smaller than this suite can resolve, and that **check 6 at 28 judgments is
too coarse an instrument to drive a build decision.** That conclusion would itself be worth
writing down, because stage 1a is specified as a single pair of full runs and would inherit
exactly the same problem.

## 6. Amendments the parent spec needs regardless of the outcome

These follow from §3 and are true whichever way the experiment lands:

- **§3 (stage 0) understates the sample problem.** It says four concepts is enough because one
  concept is "a sample of three or four binary judgments". Four concepts is ~15 judgments,
  where one flip is still ~7 points. Repeated trials are not optional here; they are the
  experiment.
- **§4 stage 1a inherits the same flaw.** "~2 full runs, one time" cannot distinguish a real
  effect from sampling noise for the same reason. It needs either repeated runs or a
  substantially larger judgment pool.
- **§6's judge-contamination risk should record the WAL observation** from §3 above as weak
  counter-evidence.
- **Non-determinism at `temperature=0` deserves naming as a project-wide property** rather than
  being rediscovered per suite. It is already recorded for `evaluator.py` and
  `question_generator`; this is the third instance, and the first where it invalidated a
  measurement.

## 7. Decisions explicitly NOT made

- Whether the thin-evidence hypothesis holds. **Unresolved.**
- Whether stage 2 (extracted concepts get `source_quotes`) should be built. Gated on the above.
- Whether to commit the probe. It is complete and useful independent of the outcome; the
  argument for committing now is that the two run logs above are not reproducible, so the tool
  that produced them should exist in history alongside this note.
