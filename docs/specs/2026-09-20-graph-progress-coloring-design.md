# Graph progress colouring — design

Colour each node of the dependency graph by what the student has actually shown about that
concept, and render the graph inside the study session so the colouring is visible while it
changes.

## Built as

Implemented. Two places diverged from the first draft, both recorded below rather than
edited out of history:

- §4 grew from "colour it a fifth colour" to "do not draw it", and then to a *stable*
  definition of drawable (`has_pipeline_one_question`) once it turned out a probed concept
  would otherwise reappear mid-session. It stays eligible for diagnosis while hidden.
- §5 was originally titled "No backend change". Making the progress denominator agree with
  the visible node count made that false; it now describes the change.
- §7/§8 originally had one clickable graph and one coloured graph on different screens.
  That split was rejected: the coloured graph is the clickable graph, on both pages.
- §6 originally held overrides in page state. Building it that way surfaced the real
  defect — the attempt cap had the same bug — so it became a derived field on
  `HistoryEntry` and the transient set was deleted.

## 1. Context — the graph is the thesis, and it is currently inert

`DependencyGraphViz` renders in exactly two places: `GraphView.tsx:62` (browsing a finalized
chapter) and `ReviewGraphPage.tsx:300` (editing a draft). Neither is a study session. During
the loop the student sees one question card and one result card; the structure the whole
project is built around — this concept depends on that one, and your wrong answer traces
back to it — is off screen.

The graph is nonetheless already loaded there. `StudySessionPage` fetches it on mount
(`getGraph(docId)`, line 64) and uses it for one thing: `conceptName()`, mapping a concept
id to a label for the status line and the "Suspected deficiency" heading. The data is in
state and unrendered.

So this is two changes that only make sense together: colour the nodes, and put the coloured
graph where the colouring means something.

## 2. The rule — last outcome wins

A concept's colour is decided by **the most recent history entry that asked about it**:

```
entries(c)      = [h for h in session.history if h.question.concept_id == c.id]
last            = entries(c)[-1]
mastered        if last.evaluation.correct
gap             otherwise
```

Both main-track and diagnostic answers count, and they count the same way. That is what
makes the rule express "unrectified" rather than "ever struggled", which is the distinction
that matters: a concept diagnosed as the root gap and then correctly answered on its
targeted question **has been rectified**, and colouring it amber afterwards would tell the
student their remediation did not land.

Three consequences worth stating, because each is a case the naive "was this ever
diagnosed?" rule gets wrong:

- **A rectified gap goes green.** `compaction` is named as the suspect behind a failed
  `lsm_tree` question; the student answers the `compaction` probe correctly; the loop
  returns to `lsm_tree` (`2026-09-17-study-loop-remediation-design.md` §2). `compaction` is
  green from that moment.
- **A regression goes back to amber.** If that same `compaction` comes up later on the main
  track and is failed, its last outcome is incorrect again. No state needs clearing; the
  rule re-reads history every render.
- **An abandoned concept stays amber.** When `_MAX_CONCEPT_ATTEMPTS` trips
  (`study_session.py:38`) the loop reveals the answer and advances. The student never got it
  right, so the last outcome is incorrect and the node stays amber — correctly, since
  `_advance()` moving past a concept is not evidence of anything.

That last case is the one the existing progress counter gets wrong and this does not.
`completed_concepts` (`routers/study_session.py`'s `list_study_sessions()`) is the
topological position of `current_concept_id`, so it counts abandoned concepts and
empty-question-set skips as completed. That is defensible for a one-line "7 of 11" progress
label and wrong for a per-node claim about what the student knows. **The two numbers will
therefore disagree, deliberately** — the session list can say 7 of 11 while the graph shows
5 green and 2 amber.

Diagnostic attribution needs no special handling: `diagnoser.py:705` already sets a targeted
question's `concept_id` to the suspect's id, so `entries(c)` picks up probe answers under
the concept they probed rather than under the concept whose failure triggered them.

## 3. The four states

| State | Colour | Derived from |
|---|---|---|
| `mastered` | green | last entry for the concept was correct |
| `current` | blue | `session.current_concept_id` |
| `gap` | amber | last entry was incorrect, **or** it is the concept the pending question targets and has no entries yet |
| `unreached` | white (today's default) | no entries, not implicated |

`current` wins over the others when they collide, since it answers "where am I" and the page
already states the current concept in prose above the graph.

The second clause of `gap` covers one transient: between a diagnosis being returned and the
student answering its targeted question, the suspect has been implicated but has no history
entry of its own. It is also not `current` — during `DIAGNOSING` the session's
`current_concept_id` deliberately stays on the concept that failed, not the suspect
(`2026-09-17` §2). Without the clause the node being probed right now is the one node with
no marking at all. Amber is the honest reading: implicated, not yet rectified.

The clause keys off the **pending question** (`StudySessionDetail.pending_question`, already
tracked by the page as `question`) rather than off the newest `diagnosis` record. A
diagnosis can be produced and then not served — `_MAX_DIAGNOSTIC_CHAIN` forces a return —
so "was named as a suspect" and "is being asked about" are not the same fact, and only the
second one should paint a node. `pending_question` is the server's own answer to "which
question is this session on", derived in one place precisely so clients do not reconstruct
it (`schemas.py`'s `StudySessionDetail` docstring).

`gap` is the state that earns this feature. It is the only place in the UI where the
project's central claim persists rather than flashing past — "Suspected deficiency: X"
currently lives in a result card that the next answer replaces.

## 4. Concepts with no questions are not drawn

A concept can legitimately end up with an empty question set. `question_generator`'s prompt
tells the model to write a question for a type only when that type genuinely fits — "it is
better to skip a type than to force one" (`question_generator.py:62`) — so a thin concept,
one whose `summary` is a sentence and which has no `source_quotes`, can fit none of the five
and come back with nothing. The loop already handles it: `_advance()` and
`start_study_session` both walk past such a concept rather than park on it, because parking
leaves `_pending_question` returning `None` with nothing the client can submit.

**These concepts are filtered out of the rendered graph entirely, not given a colour.** A
concept that can never be asked about was never tested, so every state in §3 would be a
false claim: green says demonstrated, amber says a gap was found, white says not yet
reached. None is true, and white is the worst of the three because it persists after the
session completes and reads as unfinished work.

Three constraints shape how the filter is built.

**It is per-call-site, never a component default.** `ReviewGraphPage` renders a `DRAFT`
graph, and a draft has no questions *anywhere* — question generation is what finalize does
(`ingestion.py`'s `_finalize`). A filter baked into `DependencyGraphViz` would render the
review page blank, which is the one page whose purpose is editing the graph. So the
component takes an opt-in prop and `ReviewGraphPage` does not pass it.

**Edges must bridge transitively.** Omitting a node from `graph.concepts` does not merely
hide it: edge rendering resolves each prerequisite with `positions.get(depId)` and returns
`null` when it is missing (`DependencyGraphViz.tsx:146`). Dropping `B` from `A → B → C`
therefore erases both edges, and the fact that `C` depends on `A` disappears from the
picture. The filter computes each surviving concept's effective prerequisites as the closure
over hidden ones — for each id in `depends_on`, keep it if it survives, otherwise recurse
into *its* `depends_on` — deduped, with the same cycle guard `layout()`'s `depthOf` already
carries. `A → C` is then drawn.

**The concept stays in the data model.** It is still a real prerequisite link, and
`source_passages()` feeds its `summary` and its justifying quote into its dependents'
question generation, so it is load-bearing for other concepts' questions even though it
hosts none. Nothing here deletes anything; `Store.delete_concept()` is not involved.

**A hidden concept stays eligible for diagnosis.** The graph is the *study path*; the
diagnoser reaches into machinery underneath it. Precedent already exists: `gap_is_outside_graph`
lets a diagnosis name a gap that is not a node at all and disclose it in prose through
`DiagnosisResult.reasoning`. The cost is accepted rather than worked around — a real
diagnosed gap on a hidden concept gets no amber node, and the student sees it only in the
"Suspected deficiency" line.

**Which makes "has questions" the wrong predicate, and the id the right one.** Both stores
rebuild `Concept.questions` from the question index on every `get_graph()`, so the moment
the diagnoser probes a hidden concept it would acquire a question, reappear, and bump the
denominator partway through a session — flipping the rule above by accident. Drawable is
therefore defined over **pipeline-1 questions only**: `has_pipeline_one_question`
(`app/models/question_ids.py`), mirrored in `frontend/src/lib/questionIds.ts`.

That deliberately gives the `:diagnostic{n}` suffix a second reader, which CLAUDE.md warns
against. The warning holds for `study_session._diagnostic_question_ids()`, which answers
"was this served as a probe *in this session*" and rightly consults the session's own
diagnosis records instead of parsing ids. Counting a chapter's testable concepts is a
different question — "did pipeline 1 write this" — with no session to consult. So the
convention moves to `app/models/question_ids.py`, which owns **both** sides: minting
(`diagnostic_question_id`, now used by `diagnoser._next_diagnostic_id`) and reading. It sits
in the models layer because the stores need it, and a Store importing from `app.services`
would invert the layering (the same constraint that keeps `completed_concepts` in the
router).

The pattern is anchored — `:diagnostic[0-9]+$`, not a substring test — because
`doc:diagnostic-tools:q1` is a pipeline-1 question on a concept called "diagnostic tools",
not a probe. `[0-9]` rather than `\d` so the identical string is valid in both Python's
`re` and Postgres' `~` operator, which is what stops the two implementations drifting.

The filter needs no new data on the client: `Concept.questions` is already on the graph
payload and `types/index.ts` already mirrors it as `questions: Question[]`.

## 5. The denominator, and the backend change it needs

The colouring itself needs nothing from the server. `StudySessionDetail` extends
`StudySession`, which carries `history`; every `HistoryEntry` carries `question.concept_id`
and `evaluation.correct`; and `AnswerResponse.study_session` returns the updated history on
every answer. So the derivation is a pure function of `(graph, session)`, re-runs on each
render, and survives reload because it reads persisted history rather than page state. No
new endpoint, no `schemas.py` change, no `types/index.ts` sync, no migration.

**The progress fraction is the part that does need the server.** `total_concepts` counted
every concept, so a chapter would draw nine nodes while `SessionList` said "7 of 11". Both
halves now exclude untestable concepts:

- `total_concepts` counts concepts with a pipeline-1 question — `InMemoryStore._testable_concepts`
  and, in `PostgresStore`, `_testable_concept_count()`, an `EXISTS` correlated subquery using
  Postgres' `~` against the shared `DIAGNOSTIC_ID_PATTERN`.
- `completed_concepts` (`routers/study_session.py`) counts testable concepts positioned
  before `current_concept_id`. It counts over the **full** topological order and filters,
  rather than indexing into a pre-filtered list, because `current_concept_id` is not
  guaranteed testable: `_advance` accepts any concept `get_questions` answers for, which
  includes one holding nothing but a diagnostic question generated earlier in the session.
  Indexing would silently report 0 there.

**The visibility gate stays on the raw count.** `list_documents()` uses `total_concepts > 0`
to hide zero-concept documents; narrowing that too would make a chapter whose every concept
came back question-less *vanish* from the chapter list rather than appear with 0. So
`list_documents` now runs two subqueries — one to gate, one to report.

## 6. The override case — durable, not transient

An overridden answer keeps `eval_correct = false` and the evaluator's explanation verbatim —
the disputed grade *is* the evidence, so it is never rewritten
(`2026-09-18-manual-answer-override-design.md` §4). Under §2's rule that concept's last
outcome is incorrect, so it would colour amber even though the session advanced as if it
were correct and the student has asserted they were right.

**This was first built as page state and that was wrong.** The original resolution kept a
`Set<string>` of overridden concept ids on `StudySessionPage`, lost on reload, justified by
`revealed_answer`'s precedent. It papered over a real defect: the graph was not the only
reader treating an overridden answer as a failure. `_failed_main_track_attempts` counted it
toward `_MAX_CONCEPT_ATTEMPTS`, so overriding a grade pushed the concept *closer* to being
abandoned — and `GraphView`, which has no page state to borrow, painted it amber regardless.
A per-page workaround for a backend fact is a smell, and this one was hiding a bug.

**The fix is `HistoryEntry.overridden`, derived server-side on every load.** No migration:
`answer_overrides` already keys `(study_session_id, history_seq)` and `history_seq` is the
entry's index, so `InMemoryStore._mark_overridden` resolves it by dict lookup and
`PostgresStore.get_study_session` by one query on that soft key. The effective outcome is
`evaluation.correct or overridden` — `HistoryEntry.effective_correct` in Python,
`effectiveCorrect` in `lib/conceptProgress.ts` — and both the attempt cap and the colouring
read it.

Consequences: the colour survives reload, `GraphView` gets it with no extra work, the
transient set and its plumbing are deleted, and the amendment recorded in
`2026-09-18-manual-answer-override-design.md` §4 retracts that doc's claim that an
overridden attempt still counts toward the cap.

## 7. Shape of the change

`DependencyGraphViz` gains exactly **one** optional prop:

```ts
states?: ReadonlyMap<string, ConceptState>
```

Absent, the component behaves exactly as today. Present, each node's `fill`/`stroke` comes
from its state, with `selectedId` still layered on top — the two are orthogonal (review mode
selects without any notion of progress; a session colours without selecting).

**§4's filter is deliberately not a prop.** It is a transform the caller applies to the
graph before handing it over, so the component never learns about questions at all and
opt-in is structural rather than a flag someone can forget to unset:

```
frontend/src/lib/questionIds.ts       // mirrors app/models/question_ids.py
  isDiagnosticQuestionId(id) -> boolean

frontend/src/lib/graphFilter.ts
  isTestable(concept) -> boolean
  withoutUntestableConcepts(graph) -> DependencyGraph   // drops them, bridges edges

frontend/src/lib/conceptProgress.ts
  conceptStates(graph, session, pendingQuestion, overriddenConceptIds)
    -> Map<string, ConceptState>
```

Both are pure functions of their arguments, testable with no rendering and no network, which
keeps `DependencyGraphViz` a renderer.

Call sites:

| Page | Graph passed | `states` | `onSelect` |
|---|---|---|---|
| `StudySessionPage` (new) | filtered | yes | yes |
| `GraphView` | filtered | when a session exists | yes |
| `ReviewGraphPage` | **raw** | no | yes |

`GraphView` filters for the same reason the study page does — it invites the reader to
"click a concept to preview its generated questions", and a concept with none is an empty
list presented as a result. `ReviewGraphPage` passes the raw graph because a draft has no
questions anywhere (§4).

**Colouring and clicking are the same graph, not two screens.** `GraphView` colours from
the resumable session it already looks up, fetching that session's detail for its history
(`StudySessionSummary` carries counts but no history); when there is no session to colour
from, `states` is undefined and the page renders exactly as it always did. A failed fetch
costs only the colouring and stays off the page-level error path, matching the existing
`listStudySessions` call beside it.

**Selection and progress therefore use different channels**: progress owns the node's
fill, selection owns its outline. Letting selection recolour the fill — the first
implementation, carried over from the pre-colour component — would hide the very thing a
node is coloured for the instant you clicked it. Without `states` there is no progress to
preserve, so selection falls back to the `current` swatch, which *is* the indigo a selected
node has always used, leaving the two uncoloured pages pixel-identical.

**The study screen's detail panel deliberately omits the question list** that `GraphView`'s
shows. `GET /api/questions/{concept_id}` returns `Question` objects carrying
`expected_answer_notes` — the rubric `evaluator.py` grades against — so rendering a
concept's questions mid-session is an answer key for questions not yet asked. The panel
shows the concept's state, its prerequisites, an attempt tally (`conceptAttempts`), and its
summary — with the summary covered for the concept whose question is currently open, since
that summary is the evidence the open question was written from. Keyed off the pending
question rather than `current_concept_id`, for the same reason §3's transient is: while
diagnosing, the concept being asked about is the probe's suspect, not the stalled one.

(Unrelated but adjacent: `GraphView` has always shipped `expected_answer_notes` to the
client for every concept a reader clicks. That predates this change and is left alone, but
it is the same field and worth a look.)

**One trap on the study page: `conceptName()` must keep reading the unfiltered graph.** It
resolves the status line and the "Suspected deficiency" heading, and a diagnosis can name a
concept that had no pre-generated questions — `diagnoser`'s `generate_question` tool mints
one for the suspect on the spot. The page fetches the graph once on mount and never
refetches, so that concept is absent from the filtered copy and the heading would degrade to
a raw `{doc_id}:{slug}` id. Filter what is drawn, not what is looked up.

A legend is required, not optional: four colours with no key is a puzzle. Four short
labelled swatches under the graph.

## 8. Out of scope

- **Overrides on `GraphView`.** Its colouring passes an empty override set: overrides are
  page state on `StudySessionPage` (§6) and there is no endpoint to read them back, so a
  disputed concept reads as a gap on that screen. The same follow-on in §6 fixes both.
- **Mastery across sessions.** This reads one session's history. Persistent per-learner
  mastery is a different feature with a storage question attached, and there is no auth to
  hang a learner on yet.
- **Durable override colouring** — see §6.
- **Re-laying out the graph.** The layered layout (`DependencyGraphViz.layout()`) is
  unchanged; this only changes how nodes are painted.

## 9. Testing

`conceptProgress.ts` is a pure function over two plain objects, so it is unit-testable with
no rendering and no network.

**This adds vitest**, which the frontend did not have — `package.json` had no test script
and CI ran `npm run build` alone. Setup is one devDependency, a `test` field in
`vite.config.ts` (`environment: 'node'`, `include: src/**/*.test.ts`), an `npm test` script,
and one CI step before the build.

Pinned to **vitest 2.x**, not the current major: vitest 5 requires vite ≥ 6 and this project
is on vite 5, so installing the latest fails peer resolution. Upgrading vite is not this
change's business. That is worth paying here rather than validating by hand: the eight cases below are
domain rules, not rendering details, and the second one is the entire refinement this
feature was asked for. Hand-validation of a rule that only misbehaves three answers into a
session is not validation.

Rendering stays untested — no component-testing library is added, and the "`states` omitted
changes nothing" case below is covered by reading the prop's default rather than by
snapshotting SVG.

The cases that matter are exactly §2's three consequences plus the states table:

`conceptStates`:

- a concept answered correctly on the main track is `mastered`
- a concept diagnosed as a gap and then answered correctly on its probe is `mastered`, not
  `gap` — the case this feature's refinement is about
- a concept mastered earlier and failed later is `gap` — last outcome wins, not best
- a concept abandoned by `_MAX_CONCEPT_ATTEMPTS` is `gap` while the topological progress
  counter counts it complete
- the concept the pending question targets is `gap` before that question is answered
- `current_concept_id` wins over `mastered`/`gap`
- an untouched concept is `unreached`

`withoutUntestableConcepts`:

- a concept with an empty `questions` array is dropped; one with any question survives
- `A → B → C` with `B` dropped yields `A → C`, not a disconnected `C` — the §4 bridging
  rule, and the case a naive filter silently gets wrong
- a chain of two consecutive dropped concepts still bridges to the surviving ancestor
- bridged prerequisites are deduped when two hidden paths reach the same ancestor
- a graph where every concept has questions is returned unchanged
- a graph where *no* concept has questions (the draft shape) returns empty — the proof that
  `ReviewGraphPage` must not call this, rather than a bug to work around inside it

Component:

- `states` omitted leaves the existing output unchanged (the guard for
  `GraphView`/`ReviewGraphPage`). Held structurally rather than by a test: `unreached`'s
  swatch *is* the old `white`/`#b8bede`, and a selected node routes through `current`,
  which *is* the old `#eef0fd`/`#4b5bd7`, so the no-`states` rendering is unchanged by
  construction.

Backend (added to the existing suites, not new files):

- `tests/test_memory_store.py::TestTestableConceptCounts` — question-less and
  diagnostic-only concepts are not counted; a `diagnostic-tools` slug still is; the session
  list agrees with the document list; a chapter with no testable concept is still listed
- `tests/test_postgres_store.py::test_concept_counts_exclude_question_less_concepts` — the
  same rules against the real `~ ':diagnostic[0-9]+$'` operator. The only place the SQL
  predicate runs, since `InMemoryStore` uses Python's `re`; without it a broken pattern
  would pass every free test
