# Diagnoser agentic pipeline — design

**Status:** approved, not yet implemented
**Scope:** `backend/app/services/diagnoser.py`

## 1. Context

`diagnoser.py` is the last of the four services in the diagnostic loop still stubbed. Given a wrong answer to `question` about `concept`, it's supposed to find the prerequisite concept the misunderstanding most likely traces back to, and produce a new question that isolates that prerequisite — the root-cause step of the pipeline, not the grading step (that's `evaluator.py`).

The current stub (see `diagnoser.py`'s own docstring) always picks `concept.depends_on[0]` and generates a templated, non-grounded question. This doc designs the real replacement: an agentic, tool-calling loop (not a single structured LLM call, unlike `evaluator.py` / `graph_builder.py` / `question_generator.py`) that reasons over the wrong answer and the concept's prerequisite chain before committing to a suspect.

Two behavioral requirements drove the shape below, both explicit user decisions:

- The agent must be able to walk **multiple levels** of the prerequisite chain within a single `diagnose()` call (not just the immediate parents), so it isn't forced to always report a first-hop suspect when the real gap is deeper.
- The agent must not settle on a suspect because it "feels right" — the certainty requirement has to be **code-enforced**, not just a prompt instruction, and the whole loop needs a **hard turn budget** so it can't run away.

## 2. Orchestration shape

**Manual loop over `client.messages.create()`, not `client.beta.messages.tool_runner`.**

The Tool Runner is the normal default for a custom-tool agent, but this design needs precise control over what tools are *offered* on a specific turn (forcing `submit_diagnosis` on the last permitted turn — see §4) rather than gating a call the model already made. That's outside what the Tool Runner's per-turn hooks (`set_messages_params`, tool-result interception) are built for. A hand-rolled loop costs maybe 30 extra lines and gets exact control over both the turn budget and the forced-final-turn behavior.

**Model:** `claude-sonnet-4-6` — matches the existing convention (`question_generator.py` already uses this exact model string). Not upgraded to a newer Sonnet as a side effect of this change.

**Loop mechanics:**

- `turns_used` counts API round-trips (one `messages.create()` call), not individual tool invocations within a turn.
- **Parallel tool use is disabled** (`tool_choice: {"type": "any", "disable_parallel_tool_use": true}` on ordinary turns). This is a sequential investigation — each `get_prereqs` result should inform the next choice — not a fan-out, and disabling parallel calls keeps the budget accounting exact (1 tool call = 1 turn).
- **Default budget: 8 turns** (7 investigative + 1 forced-final). Tunable; not load-bearing on any other part of the system.
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

Returns the concept's current question set, so the agent can judge whether an existing question already isolates the gap it suspects rather than always synthesizing a new one.

```json
{
  "name": "pull_question_from_storage",
  "description": "Return the existing question set for a concept, if one has already been generated. Use this before generate_question — reuse an existing question only if it precisely isolates the specific understanding gap you suspect, not merely because a question for this concept exists.",
  "input_schema": {
    "type": "object",
    "properties": {
      "concept_id": { "type": "string" }
    },
    "required": ["concept_id"]
  }
}
```

**Stubbed for now.** `diagnose()` gains an optional parameter:

```python
def diagnose(
    concept: Concept,
    graph: DependencyGraph,
    question: Question,
    answer: Answer,
    question_lookup: Callable[[str], list[Question]] | None = None,
) -> DiagnosisResult:
```

Default `question_lookup` is a no-op (`lambda _: []`) — the tool always reports "nothing in storage." Real wiring (passing `store.get_questions`, or an equivalent, from the router) is an explicit follow-up, not part of this change. Keeps this task scoped to the orchestration shape rather than a storage-access refactor.

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
        "description": "What specifically to probe — the exact gap you suspect, in your own words."
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
  "description": "Submit your final diagnosis. Only call this with confidence 'high' if you have concrete evidence — specific wording in the wrong answer that connects to specific wording in the suspect prerequisite's evidence. A gut feeling is not enough; if you are not certain, keep investigating with get_prereqs instead.",
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
        "description": "The specific wording in the wrong answer and the specific wording in the suspect's evidence that connect them."
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

- **Signature:** `diagnose(concept, graph, question, answer, question_lookup=None)` — the added parameter is additive and optional; existing callers compile unchanged if they don't pass it.
- **`DiagnosisResult` is unchanged.** `confidence` and `evidence_basis` are internal to the tool-call trace and get folded into `DiagnosisResult.reasoning` as prose, not added as new schema fields — no changes needed to `backend/app/models/schemas.py` or `frontend/src/types/index.ts`.
- **Router-level recursion composes for free.** [study_session.py:106](../../../backend/app/routers/study_session.py#L106) already resolves `concept` from `question.concept_id` on every wrong answer, so if a student answers the *targeted* diagnostic question wrong too, `diagnose()` runs again scoped to the suspect concept — a fresh agentic walk one level deeper than the previous call. Nothing in `study_session.py` needs to change for this to work.
- **`targeted_question.prompt` must never contain `suspect.summary`.** This constraint (already noted in the current stub's docstring) is preserved: it's a rule enforced in the `generate_question` tool's own system prompt (§3.3), not a new mechanism.

## 6. Testing consequence

Today, `diagnoser.diagnose()` is pure deterministic Python, so `backend/tests/test_flow.py` exercises it directly at no cost. Once it makes real LLM calls, it needs the same treatment the other three services already got: a `stub_diagnoser` autouse fixture in `backend/tests/conftest.py` (mirroring today's "pick first prerequisite" logic, so it can be swapped in with no other test changes) so `test_flow.py` stays free and deterministic.

**Explicitly out of scope for this change**, left as follow-ups:

- Wiring `question_lookup` to the real store in `study_session.py`.
- A `tests/diagnoser_geval`-style regression suite (real, billed LLM calls) following the pattern established by `tests/geval`, `tests/graph_geval`, and `tests/question_geval`.
