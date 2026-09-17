# Study-loop remediation — design

**Status:** proposed
**Scope:** fixes the diagnostic loop's missing return step and gives it a termination rule. Touches `backend/app/routers/study_session.py` (nearly all of it), `backend/app/models/schemas.py` (one response-model field), `backend/tests/conftest.py` (a scriptable evaluator stub), `backend/tests/test_flow.py`, `frontend/src/types/index.ts`, `frontend/src/pages/StudySessionPage.tsx`. **No Alembic migration, no `Store` change, no new service, no new LLM call.**

## 1. Context — three defects in one loop

Pipeline 2's premise is: a wrong answer on concept X is traced back to the prerequisite at fault, the student repairs that prerequisite, and then returns to X. The last step does not exist.

**(a) Answering a diagnostic correctly skips the concept that failed.** `submit_answer`'s correct-branch (`routers/study_session.py:191-199`) advances unconditionally. On a wrong answer `current_concept_id` is left on X and the status becomes `DIAGNOSING`; when the student then answers the diagnostic on prerequisite P correctly, the branch computes `current_index` from X and moves to X+1. X is marked done without the student ever having demonstrated it. The comment at :191 asserts the opposite — "this simply resumes the main track from the study session's current concept" — which is what the code was meant to do and does not.

The fallout reaches the menu screen: `completed_concepts` is the topological position of `current_concept_id` (`list_study_sessions()`), so every skipped concept inflates the progress count.

**(b) The drill has no floor.** A wrong answer to a diagnostic re-enters the same else-branch with `concept = by_id[question.concept_id]` — now P — and diagnoses deeper. At a root concept the diagnoser names the concept itself; `tests/diagnoser_geval` records exactly this on `hash_index` and `wal_missing_btree_pages`, and the stub in `tests/conftest.py` reproduces it (`suspect = ... , concept`). So a student who keeps answering wrong at the bottom of the graph is served a question about the same concept indefinitely, with no cap, no hint, and no exit.

**(c) A concept with no questions deadlocks the session.** `question_generator`'s rule 3 tells the model to skip any type that does not genuinely fit, so `concept.questions` can legitimately come back empty. `_pending_question` then evaluates `(store.get_questions(X) or [None])[0]` — an empty list is falsy — and returns `None`. The UI renders "No question available", there is no answer to submit, and nothing can advance the session. Latent today because the stub always generates two questions per concept; reachable in production.

All three live in the same twenty lines of transition logic, which is why they are one design and not three.

## 2. The transition rule

The discriminator is `status` **as read at request entry**, before any mutation. It already encodes which track the student was on, so nothing needs to inspect the question's id or provenance.

| entry status | evaluation | result |
| --- | --- | --- |
| `ACTIVE` | correct | advance — the concept is mastered |
| `ACTIVE` | wrong | diagnose → `DIAGNOSING`; unless the attempt cap trips (§3) |
| `DIAGNOSING` | correct | → `ACTIVE`, **current concept unchanged** — X is re-served |
| `DIAGNOSING` | wrong | diagnose deeper; unless the chain cap trips (§3) |

Returning to X requires no change to `_pending_question`. An `ACTIVE` session on X already serves `store.get_questions(X)[0]`, and that is the question the student failed — diagnostic questions are appended after the generated set, so index 0 stays the main-track question. The one-line bug is the unconditional advance, not the question lookup.

**The student is re-asked the same question, deliberately.** They have already seen the evaluator's explanation naming the rubric elements they missed, so this is not a clean re-test and a determined student can parrot it back. It is chosen anyway: it is the only variant that isolates the thing the loop is supposed to establish — whether repairing P changed their ability to answer *this* question — and it needs no rule for what happens when a concept's question pool is exhausted. Serving a different question from the pool is a separate change (§8).

No new `StudySessionStatus` member. `ACTIVE`/`DIAGNOSING`/`COMPLETED` already express every state above, so nothing changes in the Postgres `study_sessions.status` column, the TypeScript union, or the badge rendering.

## 3. Two bounds, because one cannot close both doors

```python
_MAX_CONCEPT_ATTEMPTS = 3   # wrong answers on a concept's own question
_MAX_DIAGNOSTIC_CHAIN = 2   # consecutive diagnostics in one drill before forcing a return
```

Module constants in `routers/study_session.py`, not settings — nothing about them is deployment-specific, and a knob invites tuning without measurement.

A single "wrong answers per concept" number fails in both directions. Count only attempts on X and the student can loop forever through prerequisite diagnostics without ever returning to X — the unbounded path re-enters through a different door. Count every wrong answer while X is current and a student with a genuine deep gap spends the entire budget on prerequisites, so X is never retried and the fix in §2 buys nothing.

The ceiling is `A + (A-1) × C` questions on one concept, where `A` is the attempt cap and `C` the chain cap — the final attempt triggers no drill, so it is not `A × (1 + C)`. At `3`/`2` that is **7 questions and 4 diagnoser runs**. **Each wrong answer that is not a give-up costs one evaluator call plus a full `diagnoser` agentic loop** (up to 5 Sonnet round-trips, plus its nested question-generation and question-matching calls), so the diagnoser term `(A-1) × C` dominates the bill. `2`/`2` halves it to 4 questions and 2 diagnoser runs; the shape of the design does not change.

**Giving up reveals the answer, by one uniform rule:** whenever either cap trips, the response carries the `expected_answer_notes` of the question being abandoned, and the loop moves on. The same code path covers abandoning X and abandoning a prerequisite chain, so there is one behavior to reason about and one to test.

`expected_answer_notes` is used as-is, with no new LLM call. Since the `expected_answer` fix it is the ideal student response in prose, and `question_geval`'s checks 4 and 5 already assert that it answers its own question completely and stands alone for a reader who cannot see the evidence — very nearly the constraint "readable by a student who just failed it". The residual risk is register: it is phrased for a grader, not for a learner. Accepted for now; writing a targeted explanation is §8.

## 4. Everything is derived from history — no migration

The rule needs two quantities: how many times the student has failed X's own question, and how deep the current drill is. Both are already persisted. `HistoryEntryRow` carries `question_id` (FK), `eval_correct`, and `diagnosis_targeted_question_id`, and `submit_answer` already loads the full session with its history, so the derivation is free on the read path.

It is sound because concepts are visited exactly once. `current_concept_id` only ever moves forward through `topological_order`, and nothing moves it back, so every history entry naming X belongs to X's single visit. There is no "which visit was this" ambiguity to disambiguate with stored state.

**Identifying a diagnostic answer without relying on the id convention.** Question ids do carry a `:diagnostic{n}` suffix, and that convention is load-bearing elsewhere, but the session already records the same fact exactly: a diagnostic question is one some earlier entry's diagnosis targeted.

```python
def _diagnostic_question_ids(study_session: StudySession) -> set[str]:
    """Every question this session served as a diagnostic probe.

    Derived from the diagnoses themselves rather than from the `:diagnostic{n}` id suffix:
    the suffix is minted in `diagnoser._next_diagnostic_id()` and parsing it here would put
    a second reader on a convention with one owner. The session already holds the fact.
    """
    return {
        entry.diagnosis.targeted_question.id
        for entry in study_session.history
        if entry.diagnosis is not None
    }


def _failed_main_track_attempts(study_session: StudySession, concept_id: str) -> int:
    """Wrong answers to `concept_id`'s own question, excluding diagnostic probes.

    The exclusion matters: the diagnoser may name the answered concept itself as the
    suspect (a documented outcome for concepts with no prerequisites), so an entry can
    carry `question.concept_id == concept_id` and still be a diagnostic.
    """
    diagnostics = _diagnostic_question_ids(study_session)
    return sum(
        1
        for entry in study_session.history
        if not entry.evaluation.correct
        and entry.question.concept_id == concept_id
        and entry.question.id not in diagnostics
    )


def _current_chain_length(study_session: StudySession) -> int:
    """How many diagnostics deep the *current* drill is.

    Trailing diagnostic entries only — a main-track entry ends the chain, which is what
    makes this the current drill rather than the session's total.
    """
    diagnostics = _diagnostic_question_ids(study_session)
    length = 0
    for entry in reversed(study_session.history):
        if entry.question.id not in diagnostics:
            break
        length += 1
    return length
```

Consequences worth stating plainly: **no Alembic migration, no `Store` ABC change, no `PostgresStore` or `InMemoryStore` change, no new persisted field on `StudySession`.** The change is confined to one router, one response model, and the frontend.

**The one thing this cannot do cheaply.** Showing "2 concepts unmastered" in the *session list* needs per-session aggregates, and `list_unfinished_sessions()` deliberately returns `StudySessionSummaryRow` without history. Deriving it there means either an N+1 load of every session's history or a stored counter and a migration. Deferred (§8). `completed_concepts` becomes honest as "concepts passed through" the moment §2 lands, since a concept is only left behind after either mastery or a cap — it just does not distinguish the two.

## 5. Advancing, and the empty-question-set skip

Advancing gains one responsibility: never park on a concept that has no question to serve (§1c).

```python
def _advance(store: Store, study_session: StudySession, graph: DependencyGraph) -> None:
    """Move to the next concept in prerequisite order that actually has a question.

    Concepts with an empty question set are skipped rather than parked on: reaching one
    leaves `_pending_question` returning None with no answer the client can submit, which
    deadlocks the session permanently. `question_generator` is told to skip question types
    that do not fit the evidence, so an empty set is a legitimate output, not a failure.
    """
    ordered = topological_order(graph)
    index = next(
        (i for i, c in enumerate(ordered) if c.id == study_session.current_concept_id), -1
    )
    for candidate in ordered[index + 1 :]:
        if store.get_questions(candidate.id):
            study_session.current_concept_id = candidate.id
            study_session.status = StudySessionStatus.ACTIVE
            return
    study_session.status = StudySessionStatus.COMPLETED
```

`current_concept_id` is left where it was on completion, matching current behavior.

`start_study_session` needs the same guard — `ordered[0]` can be question-less, which deadlocks a session at birth. It selects the first concept in topological order that has questions, and if none do, the session is created `COMPLETED` rather than 201-ing into a dead state. (A chapter in that condition is a question-generation failure; §8 notes rejecting it at finalize instead.)

## 6. `submit_answer`, assembled

```python
entry_status = study_session.status          # read before anything mutates it
evaluation = evaluator.evaluate(question, answer)
diagnosis: DiagnosisResult | None = None
revealed_answer: str | None = None

if evaluation.correct:
    if entry_status is StudySessionStatus.DIAGNOSING:
        # The prerequisite gap is closed. Return to the concept that exposed it — do NOT
        # advance. This is the step the loop was missing: without it, repairing P counts
        # as passing X (see the design doc, §1a).
        study_session.status = StudySessionStatus.ACTIVE
    else:
        _advance(store, study_session, graph)
else:
    if entry_status is StudySessionStatus.ACTIVE:
        # +1 for the attempt being recorded now; it is appended to history below.
        give_up = _failed_main_track_attempts(study_session, question.concept_id) + 1 >= _MAX_CONCEPT_ATTEMPTS
    else:
        give_up = _current_chain_length(study_session) + 1 >= _MAX_DIAGNOSTIC_CHAIN

    if give_up:
        revealed_answer = question.expected_answer_notes
        if entry_status is StudySessionStatus.ACTIVE:
            _advance(store, study_session, graph)      # left unmastered, deliberately
        else:
            study_session.status = StudySessionStatus.ACTIVE   # stop drilling, back to X
    else:
        concept = by_id.get(question.concept_id)
        if concept is None:
            raise HTTPException(404, f"Unknown concept '{question.concept_id}'")
        diagnosis = diagnoser.diagnose(concept, graph, question, answer, evaluation)
        ...  # register the targeted question, unchanged
        study_session.status = StudySessionStatus.DIAGNOSING
```

History is appended and the session saved exactly as today, and `next_question` still comes from `_pending_question` after the transition, so "what question comes next" stays answered in one place for both the answer path and the resume path.

## 7. API and frontend

`AnswerResponse` gains one field:

```python
class AnswerResponse(BaseModel):
    evaluation: EvaluationResult
    diagnosis: DiagnosisResult | None = None
    next_question: Question | None = None
    study_session: StudySession
    revealed_answer: str | None = Field(
        default=None,
        description="The abandoned question's model answer, set only when a cap tripped "
        "and the loop moved on without the student getting it right",
    )
```

**Transient, in the response only.** `StudySessionDetail` is unchanged, so reloading after a reveal loses the banner. That is the same call `ReviewGraphPage`'s "could not find evidence" notice already makes — component state, not stored — and the fact itself is not lost, since the history entry recording the final failed attempt is persisted either way. Persisting the reveal would mean a `history_entries` column and a migration to carry something the client can re-derive.

`frontend/src/types/index.ts` mirrors the field by hand, per the standing rule in `schemas.py`'s docstring. `StudySessionPage.tsx` renders it inside the existing `lastResult` card, below the evaluation explanation and above the diagnosis block: a heading naming that the loop moved on, then the answer. When the cap trips on X, one response carries both X's reveal and X+1's `next_question`, which the existing layout already handles — the result card sits above the `QuestionCard`.

## 8. Out of scope

- **Serving a different question on retry.** `_pending_question` uses index 0 unconditionally, so the 0–5 questions `question_generator` writes per concept are dead weight in the main track, reachable only as diagnoser reuse candidates. Worth fixing; independent of this design once §2's rule is "re-ask the same question", and it needs its own rule for an exhausted pool.
- **Teaching.** The reveal is a rubric, not an explanation. A service that takes the concept, the student's wrong answers and the diagnosis and writes targeted prose is the natural follow-on — and a sixth billed service needing its own regression suite.
- **Mastered vs. skipped in the session list** (§4). Needs a stored counter and a migration, or an N+1 load.
- **Rejecting a chapter whose concepts generated no questions**, at finalize. §5 makes such concepts harmless to a session; refusing to finalize a chapter that is mostly empty is a separate ingestion-side judgment.
- **`evaluator.py`'s commented-out `temperature=0`.** Non-determinism in grading directly destabilizes an attempt-counting rule — the same answer can flip across retries — so this design is more trustworthy with it re-enabled. It is a one-character change with its own `eval_geval` validation and does not belong in this diff.

## 9. Testing

All free and stub-backed. No billed suite runs, and none is affected: `eval_geval`, `graph_geval`, `question_geval`, `diagnoser_geval` and `evidence_geval` all exercise services below this router.

**A blocker first: `stub_evaluator` cannot be scripted.** It alternates correct/incorrect off a global counter, so "wrong, wrong, wrong" — the shape every cap test needs — is unreachable. Add a `evaluator_script` fixture the stub consumes:

```python
@pytest.fixture
def evaluator_script() -> list[bool]:
    """Scripted evaluator outcomes, consumed in order, for tests that need a specific
    sequence (the attempt and chain caps). Empty by default, which keeps the alternating
    behavior every existing test was written against.
    """
    return []
```

`stub_evaluator` takes it as a parameter: empty means alternate as today; non-empty means the script is authoritative and running off its end raises with a message naming how many calls were made. Failing loudly beats silently reverting to alternation halfway through a cap test.

`stub_diagnoser` needs no change. It already falls back to the answered concept when there are no prerequisites, which is the root-concept self-diagnosis shape the chain cap exists to bound.

New cases in `test_flow.py`:

1. **The regression test for §1a** — fail X, answer the diagnostic correctly, assert `current_concept_id` is still X, status is `ACTIVE`, and `next_question` is X's original question.
2. Answering X correctly on the retry advances, and only then.
3. Attempt cap: `_MAX_CONCEPT_ATTEMPTS` failures on X produce `revealed_answer == question.expected_answer_notes`, no diagnosis on the final attempt, and an advanced session.
4. Chain cap: consecutive failed diagnostics stop drilling at `_MAX_DIAGNOSTIC_CHAIN`, reveal the prerequisite's answer, and return the session to `ACTIVE` on X.
5. A concept with an empty question set is skipped by `_advance` rather than parked on, and by `start_study_session` rather than opened on.
6. Reveal and the next question arrive in the same response when the cap trips mid-chapter.

**Existing `test_flow.py` assertions will need revising, and that is the point.** Anything currently asserting that the session advances after a correct diagnostic answer is pinning the bug. Each such change should be checked individually rather than bulk-updated — an assertion that breaks for a reason other than §2's rule is a signal, not noise.
