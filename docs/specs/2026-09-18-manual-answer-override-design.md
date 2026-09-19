# Manual answer override — design

**Status:** implemented
**Scope:** one new table (`answer_overrides`) and its migration, one `Store` pair, one endpoint on `backend/app/routers/study_session.py`, one domain model in `backend/app/models/schemas.py`, and the frontend affordance in `frontend/src/pages/StudySessionPage.tsx`. **Depends on `docs/specs/2026-09-17-study-loop-remediation-design.md` being implemented first** — §3 explains why. Captures disagreements only; it does not review them and does not tune anything.

## 1. Context — the evaluator is wrong often enough to need a channel

`evaluator.py` grades with `claude-haiku-4-5` and its `temperature=0` call parameter **commented out**, so the same question/answer pair can flip between `correct: true/false` across calls. `tests/eval_geval` sits at 39/42, and the 3 failures are recorded as genuine evaluator leniency gaps rather than suite bugs. Grading is the one place in this app where a model error is immediately, personally wrong at the student: a correct answer marked wrong drags them into a diagnostic drill on a prerequisite they have just demonstrated.

Today nothing records that. The student has no way to disagree, and the project has no corpus of real misgrades to tune against — `eval_geval`'s 42 answer variants are hand-written fixtures, not production traffic.

This design adds the channel and the corpus. It is deliberately **capture only**: a student asserts the grade was wrong, the session moves on, and a self-contained record of the disagreement is written for later human validation. Deciding whether the student was actually right, and feeding that back into the prompt or the model, is out of scope (§8).

## 2. What a record has to contain to be worth keeping

The unit is a disagreement, and validating one months later means reconstructing what the evaluator saw. That is five things: the question asked, the rubric it was graded against (`expected_answer_notes`), the student's answer, what the evaluator said, and why the student thinks it was wrong.

The last one is new information that exists nowhere else in the system, and it is the most valuable column in the table — it is the difference between "somebody disagreed" and "somebody disagreed *because the rubric demanded an example the question never asked for*". Optional, because forcing prose behind a disagreement button suppresses the disagreements.

## 3. Advancing the session, and why this waited on the remediation

Overriding means the session proceeds as though the answer had been graded correct. That reuses `submit_answer`'s correct-branch rule — and before the 09-17 remediation, that branch advanced `current_concept_id` unconditionally, including when the student was answering a *diagnostic* question. Building on it then would have meant overriding a misgraded diagnostic on prerequisite P silently marked concept X complete without X ever being answered.

With the remediation in place, the rule is sound in both cells, so the override is allowed on **any** incorrect answer:

| session status at override | result |
| --- | --- |
| `ACTIVE` (main-track question) | `_advance(...)` — move past this concept |
| `DIAGNOSING` (diagnostic probe) | status → `ACTIVE`, `current_concept_id` unchanged — back to the concept that failed |

Allowing it on diagnostics matters more than it first appears. A misgraded diagnostic is the more irritating failure — the student is being drilled on a prerequisite specifically to prove they know it — and misgrades on diagnostic questions are exactly the ones `eval_geval`'s fixtures cannot represent, since diagnostic questions are model-generated at runtime.

## 4. The history entry is left exactly as graded

`history_entries` keeps `eval_correct = false` and the evaluator's explanation verbatim. The override is a **second, separate record** asserting the first one is wrong, not an edit of it.

Rewriting the entry would destroy the only in-session evidence of the disagreement and make a session replay show agreement where there was none — while the thing being disputed is precisely what the evaluator said. Two consequences, both accepted:

- **The overridden attempt still counts toward `_MAX_CONCEPT_ATTEMPTS`.** A student who overrides twice on one concept and then genuinely fails it once hits the cap. Correct under the remediation's own accounting (the cap bounds how much the *loop* spends on a concept), and rare enough not to warrant a second counter.
- `completed_concepts` counts an overridden concept as passed, since it is the topological position of `current_concept_id` and the session did advance. That is the intended reading.

## 5. A snapshot row with no foreign keys

```
answer_overrides
  id                     bigserial PK
  study_session_id       text      -- soft reference, no FK
  history_seq            int
  question_id            text      -- soft reference, no FK
  concept_id             text
  doc_id                 text
  question_prompt        text      -- snapshot
  expected_answer_notes  text      -- snapshot
  student_answer         text      -- snapshot
  evaluator_explanation  text      -- snapshot
  student_note           text NULL
  created_at             timestamptz
  UNIQUE (study_session_id, history_seq)
```

**This deliberately departs from the convention `history_entries` sets** — FK into `questions`, never an embedded copy. Two reasons, both about lifetime rather than style:

1. **Cascades would delete the corpus.** `DELETE /api/study-session/{id}` is a live button in `SessionList.tsx` and cascades `history_entries`; `delete_document` cascades documents → concepts → questions. A record whose entire purpose is to outlive the session that produced it cannot hang off either chain. Soft string references keep the join *possible* while the rows still exist, without making survival conditional on them.
2. **The rubric is the disputed artifact.** Reading `expected_answer_notes` through a join returns it as it is at export time. A tuning corpus needs it as it read at grading time.

The cost is duplicated text, which is the right trade for a table that grows one row per disagreement.

`history_seq` is the index into `StudySession.history`, matching `history_entries.seq`. It is the identity of the *attempt*, which `question_id` alone is not: after the remediation a concept's question is re-served on retry, so one question id can appear in a session's history several times.

## 6. Idempotency, and the double-advance it prevents

**The override does not append to history.** So the entry it targets remains the session's most recent one, and a second POST — a double-click, a retried request — would find the same entry, pass the same checks, and advance the session a second time.

The unique constraint is the guard, surfaced through the store rather than the router:

```python
def save_answer_override(self, override: AnswerOverride) -> bool:
    """True if a new row was written, False if this entry was already overridden."""
```

`PostgresStore` gets both the write and the answer from one statement (`ON CONFLICT DO NOTHING ... RETURNING id`); `InMemoryStore` checks a dict keyed on `(study_session_id, history_seq)`. The router treats `False` as "already done" and returns the session untouched, so a repeat POST is a true no-op rather than an error the client has to interpret. A returning `bool` from a `save_*` method is unusual for this codebase and is called out in the docstring for that reason.

One accepted consequence: a re-POST also discards a changed note. Editing an override is not a use case — there is no UI that can reach it twice with different text.

## 7. Only the most recent history entry can be overridden

The endpoint 409s when `question_id` does not name the session's last history entry.

The transition in §3 branches on `study_session.status`, and status describes the latest entry alone. Applying it to an older entry would run the current rule against a different point in the session — overriding a main-track answer from three concepts ago while the session sits mid-drill would advance from wherever it happens to be now. Restricting to the newest entry also makes `history_seq` unambiguous (`len(history) - 1`) with no search.

This is not a limitation in practice: the UI only ever offers the button on the result card for the answer just given.

## 8. Out of scope

- **Any review UI or read endpoint.** `Store.list_answer_overrides()` exists (the write cannot otherwise be verified against real Postgres, and it is the seam a route would sit on), but nothing exposes it over HTTP. Review is `psql` for now.
- **Deciding whether the student was right.** That is the human step this corpus feeds.
- **Re-tuning `evaluator.py`.** Note that the cheapest available win is unrelated to this feature and already identified: re-enabling the commented-out `temperature=0`, which `eval_geval` validates.
- **Durability without Postgres.** With `DATABASE_URL` unset the app runs `InMemoryStore` and overrides are lost on restart — the codebase-wide pattern, not a gap here. The corpus only accumulates when Postgres is configured.
- **Rate limiting or abuse control.** There is no auth (see CLAUDE.md), so there is no actor to limit. A student who overrides everything produces a useless corpus and skips their own chapter; neither is a system problem.

## 9. Testing

All free and stub-backed; no billed suite runs or is affected, since all five exercise services below this router.

`backend/tests/test_answer_override.py` drives the endpoint over HTTP, using the `evaluator_script` fixture the 09-17 work added to force a wrong answer on demand. It covers: the main-track override advancing and writing one snapshot row; **the diagnostic override returning to the concept that failed** (the case §3 depends on the remediation for); history left untouched; the double-POST no-op; 409 on an already-correct entry; 409 on a stale `question_id`; 404 on an unknown session and on one with no history; and the note round-tripping, null included.

`backend/tests/test_postgres_store.py` covers the round-trip and the conflict case against real Postgres.

> One trap worth recording: that suite's `_clean_tables` fixture truncates a hardcoded table list, and `answer_overrides` has **no foreign keys**, so `CASCADE` does not reach it. It must be named explicitly in the `TRUNCATE` or override rows leak between tests — a failure that shows up as a passing suite measuring polluted state.
