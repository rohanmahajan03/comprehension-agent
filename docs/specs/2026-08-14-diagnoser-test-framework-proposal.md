# Testing `diagnoser.py` — proposed framework

**Status:** proposal, nothing implemented
**Scope:** a `backend/tests/diagnoser_geval/` suite, plus one free test file and one seam in `diagnoser.py`

## 1. Why this one is harder than the other three suites

The existing suites all grade a **single call's output**. The diagnoser is an agentic loop, which breaks three assumptions they were built on.

**The output isn't the whole behavior.** `evaluator`, `graph_builder`, and `question_generator` are one call in, one structure out — grade the structure and you've graded the service. The diagnoser's contract includes things that never appear in `DiagnosisResult`: that it *investigated* before concluding, that the certainty gate actually held, that it stayed inside its turn budget. Those live in the trajectory. Grading only the returned object would pass a diagnoser that guessed correctly on turn one for bad reasons — which is precisely the failure mode the certainty gate exists to prevent.

**Ground truth is interpretive.** `graph_builder`'s concepts are objectively present in the source text; `question_generator`'s `type` is a closed vocabulary. But "this student's misunderstanding stems from concept X" is a judgment, and often more than one answer is defensible. A wrong answer about `sstable` might reasonably trace to `compaction` *or* `log_segment`. A golden set that names one right answer per case would fail the diagnoser for being differently-reasonable, which is the same mistake question_geval made with its original per-question similarity metric and later dropped.

**Trajectories vary more than outputs.** `temperature=0` pins each individual call, but the loop feeds tool results back into the next request, so one different tool choice on turn 2 changes everything downstream. Per-case trajectory assertions will be flaky. Aggregate thresholds are the safer shape — the same conclusion question_geval reached when it moved from per-pair to average scoring.

## 2. Prerequisite: a trace seam in `diagnoser.py`

`diagnose()` currently returns only `DiagnosisResult`, so the trajectory is unobservable. This suite needs the same "internal seam, not stable public API" treatment `graph_builder._extract_raw_graph()` and `question_generator._generate_raw_for_concept()` already have:

```python
@dataclass(frozen=True)
class DiagnosisTrace:
    turns_used: int
    tool_calls: list[tuple[str, dict]]        # (tool_name, input) in order
    rejected_submissions: list[dict]          # payloads the certainty gate refused
    concepts_inspected: list[str]             # ids passed to get_prereqs, in order
    forced_final: bool                        # did it hit the budget?


def _diagnose_with_trace(...) -> tuple[DiagnosisResult, DiagnosisTrace]: ...
```

`diagnose()` becomes a thin wrapper returning only the result, so production is unchanged. Everything in §5's Tier 1 and Tier 3 reads the trace.

This is worth doing regardless of the suite — right now a diagnosis that took five turns and three rejected submissions is indistinguishable from one that took one turn, in production logs as well as tests.

## 3. Fixtures

Reuse the **Case 3 Storage Engines** graph already in `tests/question_geval/golden.py`, the same way question_geval reused graph_geval's shape. It's real, it's already curated, and its dependency chain is unusually deep:

```
bloom_filter → lsm_tree → sstable → compaction → log_segment → append_only_log
                       ↘ memtable
write_amplification → lsm_tree, b_tree
write_ahead_log     → b_tree
```

Five hops from `bloom_filter` to `append_only_log` is enough to test multi-level drilling for real rather than one hop and a claim.

```python
@dataclass(frozen=True)
class DiagnosisCase:
    name: str
    answered_concept: str          # slug of the concept the question was about
    question_prompt: str
    student_answer: str            # engineered to exhibit ONE specific gap
    evaluation_explanation: str    # hand-written, in evaluator.py's voice
    acceptable_suspects: set[str]  # any of these is a pass
    preferred_suspect: str         # the sharpest answer; reported, not asserted
    forbidden_suspects: set[str]   # diagnosing these is clearly wrong
    hops_to_preferred: int         # 1 = immediate prereq; ≥2 exercises drilling
```

**`evaluation_explanation` is hand-written, not produced by running the real evaluator.** That's deliberate: chaining the two services means a diagnoser failure and an evaluator failure look identical, and you can't attribute the regression. `tests/geval` makes the same choice by hand-writing `golden_answer` instead of generating it. Worth flagging as an open question (§7) since hand-written explanations may be cleaner than production ones.

**Authoring the wrong answers is the real work here**, and it's editorial, not mechanical. Each `student_answer` has to be wrong in a way that genuinely traces to one prerequisite — a plausible answer from someone who understood everything except that concept. A generically bad answer ("I don't know") diagnoses to nothing and tests nothing. Budget real time for this; it's the fixture equivalent of `geval_test_suite.md`'s 42 hand-written answer variants.

Suggested starting spread — 8 cases, weighted toward depth since that's the capability with no coverage at all today:

| # | Answered concept | True gap | Hops | What it tests |
|---|---|---|---|---|
| 1-2 | `compaction`, `write_ahead_log` | immediate prereq | 1 | The baseline the old stub also passed |
| 3-5 | `sstable`, `lsm_tree`, `bloom_filter` | 2-3 hops down | 2-3 | Multi-level drilling — the whole point of the agentic design |
| 6 | `append_only_log` | itself (no prereqs) | 0 | The leaf case: diagnose the concept itself |
| 7 | `write_amplification` | one of two prereqs | 1 | Choosing between branches (`lsm_tree` vs `b_tree`) |
| 8 | `hash_index` | genuinely ambiguous | 1-2 | `acceptable_suspects` with >1 member — does it pick *a* defensible one |

## 4. Cost — the reason to keep this small

Per case: up to 5 orchestrator turns (`claude-sonnet-4-6`), plus 1-2 `generate_question` (sonnet), plus 1-2 `_find_matching_question` (haiku), plus the suite's own judges. Call it ~8 sonnet calls per case against question_geval's 11 for its *entire* run.

Eight cases is therefore roughly **5-8× question_geval's cost per run**, plausibly 10-20 minutes. Concretely: start at 6-8 cases, `lru_cache` the whole scored run exactly as `score_case()` does so all assertions share one execution, and expect to iterate with the §6 probe rather than the full suite.

## 5. Checks, cheapest first

### Tier 0 — free, no API, runs in CI

Promote the ad-hoc fake-client harness used while building the diagnoser into a real test file (`tests/test_diagnoser_loop.py`, alongside `test_question_geval_wiring.py`). Scripted tool_use responses through a fake client, asserting: the turn budget holds; the final turn forces `tool_choice: {"type": "tool", "name": "submit_diagnosis"}` with only that tool offered; sub-`"high"` confidence is rejected and the loop continues; each rejection states its *specific* reason; unknown concept ids come back as recoverable `is_error` results; diagnostic ids increment rather than collide.

These are the mechanics most likely to break silently under refactor and they cost nothing, so they belong in the free suite, not the billed one.

### Tier 1 — deterministic checks on real output

No judge needed; these are invariants, and each should be zero-tolerance rather than a rate.

- **No answer leak**: `suspect.summary` must not appear in `targeted_question.prompt`. This is the constraint the original stub docstring called load-bearing, and it has never been tested. Check normalized substring, and also a high token-overlap threshold to catch near-verbatim paraphrase.
- **Suspect is reachable**: the diagnosed concept must be the answered concept itself or reachable from it via `depends_on`. Diagnosing an unrelated concept is always wrong regardless of how good the reasoning sounds.
- **Internal consistency**: `targeted_question.concept_id == suspected_gap_concept_id`; question id matches `{concept_id}:{suffix}`; `expected_answer_notes` clears `MIN_EXPECTED_ANSWER_CHARS` and carries no pointer phrases (reuse `question_geval`'s `_ANSWER_POINTER_RE`).
- **Budget respected**: `trace.turns_used <= _MAX_TURNS`.

### Tier 2 — diagnostic accuracy (the core metric)

- `suspected_gap_concept_id ∈ acceptable_suspects` — aggregate rate across cases, threshold to be calibrated on the first live run rather than guessed now (question_geval's thresholds were all set this way, and the one number I guessed in advance — `ANSWER_QUALITY_THRESHOLD` — is the one never yet stress-tested).
- `suspected_gap_concept_id ∉ forbidden_suspects` — **zero tolerance**, not a rate.
- Report accuracy **split by `hops_to_preferred`**. If 1-hop cases pass and 3-hop cases fail, the agentic design isn't earning its cost over the old `depends_on[0]` stub, and that's the single most important thing this suite can tell us.

### Tier 3 — LLM-judged quality

Two judges, both `claude-haiku-4-5` (mechanical comparisons, matching question_geval's tier choice):

- **Does the targeted question actually probe the suspect?** Given the suspect's summary and the question, would answering it correctly demonstrate understanding of that concept? Guards against a correct suspect paired with an irrelevant question.
- **Is the reasoning evidence-backed or generic?** Given `evaluation_explanation`, the suspect's evidence, and `DiagnosisResult.reasoning`, does the reasoning connect a *specific* stated deficiency to *specific* concept evidence — or is it a plausible-sounding assertion? This is the certainty requirement made observable: the code gate enforces that the model *claimed* high confidence, and only a judge can check whether the claim was earned.

**Both judges need the anti-rubber-stamp discipline from this session**: verify each discriminates by probing it on hand-written bad examples (a question about the wrong concept; generic reasoning like "the student seems confused about the basics") and confirming it rejects them. Do this before trusting any green run, and re-do it after any judge-prompt edit.

## 6. Two practices to carry over from question_geval

**Always print the metrics.** Add a `pytest_terminal_summary` mirroring `tests/question_geval/conftest.py`: accuracy overall and per hop-depth, turn distribution, rejected-submission counts, and every case that missed. A passing assertion prints nothing, and for judged checks an exact `1.00` means the judge stopped discriminating — indistinguishable from a healthy pass without the number.

**Build the cheap probe first.** A standalone script that runs *one* case, or re-judges a handful of fixed inputs, cost pennies and seconds during this session where full runs cost minutes and real money. For the diagnoser — where a full run may be 10-20 minutes — this matters considerably more. Build it alongside the suite, not after.

## 7. Open questions

1. **Hand-written vs. real `evaluation_explanation`.** Isolation says hand-write it; realism says run the real evaluator. Proposal: hand-write by default, add an opt-in end-to-end mode later, and compare the two once to see whether the diagnoser is sensitive to explanation style. If it is, that's a finding about robustness worth knowing.
2. **Is `preferred_suspect` assertable, or only reportable?** Started as reportable. If accuracy against `acceptable_suspects` turns out near-ceiling, tightening to `preferred_suspect` may be the more informative metric — but that's a call to make on data, not now.
3. **Multi-round drilling across HTTP requests is not covered.** The router-level behavior (wrong answer → diagnostic question → wrong again → deeper diagnosis, §5 of the diagnoser design doc) needs repeated `submit_answer` calls with an evaluator in the loop. That's an integration test, several times the cost, and I'd defer it until single-round diagnosis is known to work.
4. **What does a *failed* diagnosis look like?** No case here covers a wrong answer that stems from no prerequisite at all — careless reading, or a gap outside the graph. Right now the diagnoser must always name a suspect, so it will confabulate one. Whether that's acceptable is a product question, not a testing one, and worth deciding before writing a fixture that asserts either way.
