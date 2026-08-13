# Diagnoser agentic pipeline — design

**Status:** approved, not yet implemented
**Scope:** `backend/app/services/diagnoser.py`

## 1. Context

`diagnoser.py` is the last of the four services in the diagnostic loop still stubbed. Given a wrong answer to `question` about `concept` — and the evaluator's precise account of what was wrong with it (`EvaluationResult.explanation`) — it's supposed to find the prerequisite concept the misunderstanding most likely traces back to, and produce a new question that isolates that prerequisite. It's the root-cause step of the pipeline, picking up exactly where `evaluator.py` leaves off: the evaluator identifies *which rubric elements were missing or wrong* and explicitly does not speculate about why (see its system prompt: "do not speculate about the student's understanding — that is handled downstream"); the diagnoser is that downstream step.

The current stub (see `diagnoser.py`'s own docstring) always picks `concept.depends_on[0]` and generates a templated, non-grounded question. This doc designs the real replacement: an agentic, tool-calling loop (not a single structured LLM call, unlike `evaluator.py` / `graph_builder.py` / `question_generator.py`) that reasons over the wrong answer and the concept's prerequisite chain before committing to a suspect.

Two behavioral requirements drove the shape below, both explicit user decisions:

- The agent must be able to walk **multiple levels** of the prerequisite chain within a single `diagnose()` call (not just the immediate parents), so it isn't forced to always report a first-hop suspect when the real gap is deeper.
- The agent must not settle on a suspect because it "feels right" — the certainty requirement has to be **code-enforced**, not just a prompt instruction, and the whole loop needs a **hard turn budget** so it can't run away.

## 2. Orchestration shape

**Manual loop over `client.messages.create()`, not `client.beta.messages.tool_runner`.**

The Tool Runner is the normal default for a custom-tool agent, but this design needs precise control over what tools are *offered* on a specific turn (forcing `submit_diagnosis` on the last permitted turn — see §4) rather than gating a call the model already made. That's outside what the Tool Runner's per-turn hooks (`set_messages_params`, tool-result interception) are built for. A hand-rolled loop costs maybe 30 extra lines and gets exact control over both the turn budget and the forced-final-turn behavior.

**Model:** `claude-sonnet-4-6` — matches the existing convention (`question_generator.py` already uses this exact model string). Not upgraded to a newer Sonnet as a side effect of this change.

**Loop mechanics:**

- The loop's opening user message carries `question.prompt`, `answer.text`, and `evaluation.explanation` — the evaluator's rubric-grounded statement of what was specifically missing or wrong. This is the diagnoser's starting signal ("here's what the answer failed to show"); investigation via `get_prereqs` is what connects that signal to a specific prerequisite.
- `turns_used` counts API round-trips (one `messages.create()` call), not individual tool invocations within a turn.
- **Parallel tool use is disabled** (`tool_choice: {"type": "any", "disable_parallel_tool_use": true}` on ordinary turns). This is a sequential investigation — each `get_prereqs` result should inform the next choice — not a fan-out, and disabling parallel calls keeps the budget accounting exact (1 tool call = 1 turn).
- **Default budget: 5 turns** (4 investigative + 1 forced-final). Tunable; not load-bearing on any other part of the system.
- On the final permitted turn, `tool_choice` is forced to `{"type": "tool", "name": "submit_diagnosis"}` with only that tool declared — guarantees a structured result even at low confidence, rather than falling back to a code-side default.

## 3. Tool surface

Four tools, all executed locally (no server-side tools needed).

### 3.1 `get_prereqs`

Pure lookup, no LLM call. Given a `concept_id`, returns its immediate `depends_on` entries.

```json
{
  "name": "get_prereqs",
  "description": "Return the immediate prerequisites of a concept, each with the evidence quote that justifies the dependency. Call this on a prerequisite's own id to walk one level deeper into the chain. An empty list means this concept has no further prerequisites (a leaf).",
  "input_schema": {
    "type": "object",
    "properties": {
      "concept_id": { "type": "string" }
    },
    "required": ["concept_id"]
  }
}
```

Implementation: `[{"id": dep.id, "name": dep.name, "summary": dep.summary, "evidence": concept.evidence[dep.id]} for dep in ...]` — the same `_describe()`-style shape `question_generator.py` already uses for prerequisite context. This is how multi-level drilling happens: the model can call `get_prereqs` again on any id it has already seen.

### 3.2 `pull_question_from_storage`

Checks whether an existing question already targets the specific deficiency the model has traced to a prerequisite — called only once the model has a candidate suspect and can state the deficiency in terms of *that concept*, not as a general "does anything exist for this concept" check.

```json
{
  "name": "pull_question_from_storage",
  "description": "Check whether an existing question for this concept already targets the given deficiency. Call this once you have a candidate suspect concept and can state the deficiency in terms of it. Returns the matching question if one adequately targets this exact deficiency, or none if nothing does — in which case use generate_question instead.",
  "input_schema": {
    "type": "object",
    "properties": {
      "concept_id": { "type": "string" },
      "focus": {
        "type": "string",
        "description": "The deficiency to check for, stated in terms of this concept — same content you'd pass to generate_question."
      }
    },
    "required": ["concept_id", "focus"]
  }
}
```

**No new parameter on `diagnose()`.** `diagnose()` already receives `graph: DependencyGraph`, and every concept on it already carries its pipeline-1-generated question set (`Concept.questions`, populated by `question_generator.generate_questions()` during ingestion). The tool starts from data already in scope: `by_id[concept_id].questions`. There's no storage access to wire up and no stub to swap out later.

**The match itself is judged by a dedicated internal helper, not left to the orchestrator to eyeball.** Whether an existing question "precisely isolates" a deficiency is a semantic judgment (a question can share a topic with the deficiency while testing something else about it entirely — the same failure mode `tests/question_geval` already hit and fixed once, see `support.judge_similarity()`), so it needs a judge, not a string/keyword comparison. The tool's implementation calls a small helper:

```python
def _find_matching_question(candidates: list[Question], focus: str) -> Question | None:
    """Judge whether any candidate question already adequately targets `focus`.

    A narrowly-scoped nested LLM call (claude-haiku-4-5 — this is a mechanical
    match/no-match judgment over a handful of candidates, the same tier of
    task as question_geval's judge_similarity() and graph_geval's structural
    alignment call, not open-ended quality grading). Given the deficiency
    description and each candidate's prompt, returns the id of the one
    question that targets it precisely, or none if no candidate does.
    """
```

This keeps the top-level orchestrating model from having to read and judge every candidate question's fit itself inside the main loop — `pull_question_from_storage` returns a decisive answer (a matched question, or explicitly none) in one tool call, backed by one small judge call, rather than a raw list the orchestrator has to reason over on its own turn.

**Known scope boundary:** the candidate set is still only each concept's original pipeline-1 questions. A diagnostic question generated for the same concept in an *earlier* wrong-answer round this session lives only in the store's separate question index ([study_session.py](../../../backend/app/routers/study_session.py)'s `store.save_questions(...)` calls) — the in-memory `graph` object is never mutated with it, so neither the candidate list nor the matching helper ever sees it. That's a real, narrow limitation, not something worth designing around now; if it matters later, whatever needs it can pass the store's question list in at that point.

### 3.3 `generate_question`

The one tool with a nested LLM call.

```json
{
  "name": "generate_question",
  "description": "Generate one new question that isolates a specific understanding gap within a concept, grounded strictly in that concept's own evidence. Use this only when pull_question_from_storage has nothing that precisely isolates the gap you suspect.",
  "input_schema": {
    "type": "object",
    "properties": {
      "concept_id": { "type": "string" },
      "focus": {
        "type": "string",
        "description": "What specifically to probe — the deficiency you've traced to this concept, stated in terms of what the evaluator's explanation flagged as missing or wrong."
      }
    },
    "required": ["concept_id", "focus"]
  }
}
```

Internally, this reuses `question_generator`'s grounding discipline (system-prompt rule 7 — "quote passages in full, never truncate mid-clause, redundancy is never a reason to shorten") scoped down to producing exactly one question about `concept_id`, grounded only in that concept's `summary`, that does **not** reveal the summary in the question text itself (same constraint the current stub's docstring already calls out — the summary belongs in `expected_answer_notes`, not the prompt shown to the student).

### 3.4 `submit_diagnosis`

The mandatory terminal tool — the only way the loop ends.

```json
{
  "name": "submit_diagnosis",
  "description": "Submit your final diagnosis. Only call this with confidence 'high' if you have concrete evidence — a specific element the evaluator's explanation flagged as missing or wrong, connected to specific wording in the suspect prerequisite's evidence. A gut feeling is not enough; if you are not certain, keep investigating with get_prereqs instead.",
  "input_schema": {
    "type": "object",
    "properties": {
      "suspected_gap_concept_id": { "type": "string" },
      "confidence": { "type": "string", "enum": ["high", "medium", "low"] },
      "reasoning": {
        "type": "string",
        "description": "Why this concept, in plain terms suitable for the diagnosis record."
      },
      "evidence_basis": {
        "type": "string",
        "description": "The specific element from evaluation.explanation (what the evaluator flagged as missing or wrong) and the specific wording in the suspect's evidence that connect them."
      },
      "question_source": { "type": "string", "enum": ["storage", "generated"] },
      "question_id": { "type": "string", "description": "Required when question_source is 'storage'." },
      "question_text": { "type": "string", "description": "Required when question_source is 'generated'." },
      "grounding": { "type": "string", "description": "Required when question_source is 'generated'." }
    },
    "required": ["suspected_gap_concept_id", "confidence", "reasoning", "evidence_basis", "question_source"]
  }
}
```

**Code-enforced certainty gate:** the tool's own Python implementation inspects `confidence`. If it is not `"high"` **and this is not the forced final turn**, the tool returns a `tool_result` with `is_error: true` and a message telling the model to keep investigating (e.g. via another `get_prereqs` call). This is what makes the certainty requirement real rather than aspirational — the model cannot end the loop by simply asserting confidence; the code checks the value before accepting it. A rejected attempt still consumes a turn, so repeatedly proposing low-confidence answers to stall is not a way around the budget.

On the forced final turn (§2), the same tool accepts whatever confidence value comes back — the loop must terminate either way, and `reasoning`/`confidence` will honestly reflect that the answer is a best-effort guess under budget pressure.

## 4. Termination

Exactly two ways the loop ends:

1. `submit_diagnosis` is called with `confidence: "high"` (or on the forced final turn, any confidence) and the code accepts it.
2. The budget (§2) is exhausted, at which point the forced final turn requires the model to call `submit_diagnosis` regardless of certainty.

There is no code-side fallback (e.g. "just return the deepest concept examined") that bypasses asking the model — every path ends with an actual model-produced `DiagnosisResult`, per the earlier decision to always prefer a real (if less certain) model judgment over a mechanical default.

## 5. Integration with the existing contract

- **Signature:** `diagnose(concept, graph, question, answer, evaluation: EvaluationResult)` — `evaluation` is a required new parameter, not optional. Unlike a storage lookup, this is real data the router already computes immediately before calling `diagnose()` (`evaluation = evaluator.evaluate(question, answer)` at [study_session.py:87](../../../backend/app/routers/study_session.py#L87)), so the only change needed at the call site is passing it through — no new I/O, no stub.
- **`DiagnosisResult` is unchanged.** `confidence` and `evidence_basis` are internal to the tool-call trace and get folded into `DiagnosisResult.reasoning` as prose, not added as new schema fields — no changes needed to `backend/app/models/schemas.py` or `frontend/src/types/index.ts`.
- **Drilling across multiple wrong answers composes for free — this is not `diagnose()` calling itself.** `diagnose()` never recurses in the Python sense; its turn-budget loop (§2) is a single function call, one process, one call stack. The drilling-deeper behavior instead comes from `submit_answer()` in `study_session.py` being invoked again by a **separate HTTP request** each time the student submits another answer — the frontend calls `POST /api/study-session/{id}/answer` anew, paced entirely by the student actually responding, not by any server-side loop. Each invocation is independent, sharing no in-process state with the last; the only thing carried across calls is whatever got persisted to the store in between (the targeted question, the session's `DIAGNOSING` status).

  What makes repeated calls drill *deeper* rather than repeat the same concept is that [study_session.py:106](../../../backend/app/routers/study_session.py#L106) derives `concept` fresh from `question.concept_id` on every call — never from a remembered "original concept." So: student answers wrong on concept A → `diagnose(concept=A, ...)` investigates A's prerequisites and returns a targeted question about concept C. If the student then answers *that* question wrong too, `_find_question` resolves it back to C, so this next `submit_answer()` call sees `question.concept_id = C` and calls `diagnose(concept=C, ...)` — a fresh, independent invocation scoped one level deeper than before. Nothing in `study_session.py` needs to change for this to work; it falls out of code that already existed for an unrelated reason (resolving which question a given answer belongs to).
- **`targeted_question.prompt` must never contain `suspect.summary`.** This constraint (already noted in the current stub's docstring) is preserved: it's a rule enforced in the `generate_question` tool's own system prompt (§3.3), not a new mechanism.

## 6. Testing consequence

Today, `diagnoser.diagnose()` is pure deterministic Python, so `backend/tests/test_flow.py` exercises it directly at no cost. Once it makes real LLM calls, it needs the same treatment the other three services already got: a `stub_diagnoser` autouse fixture in `backend/tests/conftest.py` (mirroring today's "pick first prerequisite" logic, updated to accept the new `evaluation` parameter, so it can be swapped in with no other test changes) so `test_flow.py` stays free and deterministic. `study_session.py`'s existing call site also needs the one-line change noted in §5 (pass `evaluation` through).

**Explicitly out of scope for this change**, left as a follow-up:

- A `tests/diagnoser_geval`-style regression suite (real, billed LLM calls) following the pattern established by `tests/geval`, `tests/graph_geval`, and `tests/question_geval`.
