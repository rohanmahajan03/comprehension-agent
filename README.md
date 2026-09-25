# comprehension-agent

Diagnosing EXACTLY what you don't understand from your reading — an adaptive tutor that ingests textbook chapters, builds a concept dependency graph, and runs a question/answer loop that traces wrong answers back to the prerequisite concept actually at fault.

**Current state:** every LLM seam is wired up for real. Concept extraction (`graph_builder.py`), question generation (`question_generator.py`), answer grading (`evaluator.py`), and gap diagnosis (`diagnoser.py`) all call Claude — the last one runs a bounded agentic tool-calling loop rather than a single structured call (see below) — and a fifth service, `evidence_finder.py`, finds verbatim chapter evidence while you review a graph. Storage defaults to an in-memory store; set `DATABASE_URL` in `.env` to persist everything in Postgres instead. The menu screen is home: it lists every unfinished session so you can resume or delete one before uploading a new chapter, and both the graph and tutoring screens have a "Back to Home" button that returns to it.

## How it works

### Pipeline 1 — Pre-questioning (runs once per uploaded chapter)

Upload textbook chapter → build dependency graph (extract concepts and prerequisite links) → generate a question set per concept node.

Implemented as: `POST /api/textbook` → `services/graph_builder.py` → `services/question_generator.py`, all synchronous for now. Both are real: `graph_builder.py` calls Claude (`claude-haiku-4-5`) to extract concepts and prerequisite edges from the chapter text, grounding every edge in a verbatim quote and dropping any edge that would introduce a cycle. `question_generator.py` calls Claude (`claude-sonnet-4-6`) once per concept to generate a set of evidence-grounded questions from a fixed taxonomy (conceptual correctness, conceptual distinction, enumeration completeness, open-ended example, applied reasoning), skipping any type that doesn't genuinely fit the concept. Each question carries a full model answer plus a short list of **required points** — the minimum a passing answer must express — which is what the evaluator actually grades against. Both need a valid `LLM_API_KEY` in `.env` (see Prerequisites).

### Reviewing the graph before questions are generated (optional)

Tick **review** on the upload form and the chapter stops after extraction as a `draft`: you can add, rename, or delete concepts and add or remove prerequisite links (cycles are rejected) before approving it, and only then does question generation run. A draft can't be studied. When you add a concept or a prerequisite, `evidence_finder.py` (`claude-haiku-4-5`) scans the chapter for passages that explain it and *proposes* them — you accept all, some, or none. Every quote is checked to be verbatim chapter text; a paraphrase is discarded rather than repaired, and if the chapter doesn't cover the concept the UI says so. Design doc: `docs/specs/2026-09-12-human-in-the-loop`.

### Pipeline 2 — Question/answer diagnostic loop (runs per study session)

Ask a question targeting a concept → evaluate the answer.

- **Correct** → advance to the next concept (in prerequisite order) and loop back to asking.
- **Incorrect** → check the concept's dependencies → diagnose the suspected gap → ask a targeted question probing that prerequisite → loop back to evaluation, potentially recursing into deeper dependencies until the root gap is found.
- **Correct on a prerequisite probe** → return to the concept that originally failed and ask it again, so a concept is only passed once it has actually been answered correctly. (If the diagnoser named the failed concept itself as the gap, a correct probe answer counts as that demonstration and the session advances.)
- **Stuck** → after 3 failed attempts on one concept, or a diagnostic chain 2 probes deep, the model answer is revealed and the session moves on.

Implemented as: `POST /api/study-session/{id}/answer` → `services/evaluator.py`, and on a wrong answer `services/diagnoser.py`. Both are real. `evaluator.py` calls Claude (`claude-haiku-4-5`, `temperature=0`) to check the student's answer against the question's required points — using the model answer only to interpret them — and return a structured `{correct, explanation}`; it never credits the student with an idea they didn't express. `diagnoser.py` runs a bounded agentic tool-calling loop over Claude (`claude-sonnet-4-6`, up to 5 turns) rather than a single call: it can walk prerequisites to arbitrary depth, check whether an existing question already probes the suspected gap, or generate a new targeted one — and a code-enforced certainty gate means it can't end the loop on anything less than high confidence (design doc: `docs/specs/2026-08-10-diagnoser-agentic-pipeline-design.md`). Both need a valid `LLM_API_KEY` in `.env` (see Prerequisites).

### Disputing a grade

Every incorrect result has an **Override Incorrect Answer** button. It records the disagreement (question, rubric, your answer and the evaluator's explanation, copied so the record survives deleting the session or chapter) and moves the session on exactly as a correct answer would. The evaluator's own verdict is kept unchanged beside the override; an overridden attempt doesn't count toward the attempt limit or show as a gap on the graph. Only the most recent answer can be overridden. Implemented as `POST /api/study-session/{id}/override` (design doc: `docs/specs/2026-09-18-manual-answer-override-design.md`). Overrides are only durable with `DATABASE_URL` set.

### Progress on the graph

The tutoring screen draws the chapter's dependency graph, coloured by what the session has shown: **current**, **mastered**, **gap** (unrectified — a concept you later answer correctly turns green), and **unreached**, with a legend. A concept's colour comes from its most recent answer, so this can differ from the session list's "N of M complete" count, which also counts concepts the session gave up on. Concepts with no generated questions aren't drawn (their edges are bridged through to the nearest drawn ancestor). The detail panel shows a concept's state, prerequisites and attempts, but not its questions, and hides the summary of the concept currently being asked about — both would give the answer away. The graph screen uses the same colours for a chapter with a resumable session. Design doc: `docs/specs/2026-09-20-graph-progress-coloring-design.md`.

### Resuming and deleting sessions

The menu screen lists every unfinished session (any that hasn't reached `completed`), most recently updated first, so you can pick up a study session across page reloads or upload another chapter without losing progress on the current one. Each row also has a delete option, with an inline confirmation before it actually removes the session and its history.

Implemented as: `GET /api/study-session` for the list, `DELETE /api/study-session/{id}` to remove one. A session drops off the list automatically once completed; delete is a separate, explicit action that works at any status.

### ID conventions (load-bearing)

Concept ids are `{doc_id}:{slug}`; question ids are `{concept_id}:{suffix}` (`q1`, `q2`, `diagnostic1`, `diagnostic2`, …, numbered since one concept can be diagnosed more than once in a session). The study-session router resolves an answered question by stripping the id back to its concept (`question_id.rsplit(":", 1)[0]`) and looking it up in that concept's question set — diagnostic questions get appended to the store under their concept when generated so this resolution keeps working for them too.

## Prerequisites

- Docker + Docker Compose (that's all for the containerized quickstart)
- For native development: Python ≥ 3.11 and Node ≥ 20
- An Anthropic API key in `.env` as `LLM_API_KEY` — every real LLM call needs it: uploading a chapter (`graph_builder.py` + `question_generator.py`), submitting an answer (`evaluator.py`), diagnosing a wrong one (`diagnoser.py`), and scanning for evidence during graph review (`evidence_finder.py`).
- Postgres is optional. Leave `DATABASE_URL` unset in `.env` and the app uses an in-memory store — nothing to run, nothing persists across restarts. Set it to persist everything instead; see `CLAUDE.md` for the local Postgres setup (`docker compose up -d postgres`, migrations run automatically on backend startup).

## Quickstart (Docker)

```bash
cp .env.example .env
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000 (docs at http://localhost:8000/docs)
- Health check: http://localhost:8000/api/health

`docker compose up` automatically merges `docker-compose.override.yml`, which gives you **dev mode**: hot reload for both services via bind mounts (vite dev server for the frontend, `uvicorn --reload` for the backend).

For a **production-like** run (multi-stage builds, nginx serving the frontend bundle, no mounts):

```bash
docker compose -f docker-compose.yml up --build
```

## Running natively (no Docker)

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # or: uv sync --extra dev
uvicorn app.main:app --reload    # serves on :8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev                      # serves on :5173, proxies /api to :8000
```

## Running backend tests

```bash
cd backend
.venv/bin/pytest                 # or just `pytest` with the venv activated
```

Free and deterministic — all five LLM services are stubbed for these via autouse fixtures in `tests/conftest.py` (the graph_builder stub returns a fixed 5-concept calculus graph; the question_generator stub returns two templated questions per concept; the diagnoser stub picks the concept's first prerequisite, falling back to the concept itself when it has none; the evidence_finder stub only finds sentences that name the concept).

`backend/tests/test_postgres_store.py` is also free (no LLM calls) but needs a real Postgres instance, so it auto-skips unless `TEST_DATABASE_URL` is set — see `CLAUDE.md` for the exact setup (it truncates its tables before every test, so it's pointed at a dedicated `_test`-suffixed database, never the working one).

There are also five live regression suites (using [DeepEval](https://github.com/confident-ai/deepeval)) that exercise the real LLM calls end-to-end and make real, **billed** Anthropic API calls, so none of them run as part of the default `pytest` — each auto-skips without an `LLM_API_KEY`:

- `backend/tests/eval_geval/` — grades `evaluator.evaluate()` against 10 questions / 42 answer variants (~$0.35–0.45, ~5-6 minutes per full run)
- `backend/tests/graph_geval/` — grades `graph_builder.build_graph()`'s extracted concepts/edges against a golden set (`tests/graph_golden_set.md`), using a judge LLM call for concept alignment
- `backend/tests/question_geval/` — grades `question_generator.generate_questions()`'s output against a golden set: source citation, whether questions are answerable from the evidence, whether each model answer is gradeable and correct, and whether questions stay on their target concept rather than a neighbour
- `backend/tests/diagnoser_geval/` — grades `diagnoser.py`'s agentic loop against 9 hand-authored diagnosis cases: suspect accuracy by hop depth, zero-tolerance invariants (no answer leaks into the targeted question), and two judged checks on question relevance and reasoning quality
- `backend/tests/evidence_geval/` — grades `evidence_finder.py` against hand-labelled chapter spans: whether each quote is verbatim and actually about the concept, and that it finds nothing for concepts the chapter doesn't cover (the cheapest suite — Haiku only)

To run any of them:

```bash
cd backend
set -a && source ../.env && set +a
.venv/bin/pytest tests/eval_geval -v            # or tests/graph_geval, tests/question_geval, tests/diagnoser_geval, tests/evidence_geval
```

## Running frontend tests

```bash
cd frontend
npm test                         # vitest, no DOM — pure functions in src/lib/**/*.test.ts
```

These cover the graph colouring rules (`conceptProgress.ts`) and the untestable-concept filter (`graphFilter.ts`). CI runs them before `npm run build`.

## API surface

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/textbook` | Upload chapter text; builds graph + questions, returns `doc_id` (with `review`, stops at a draft graph) |
| `GET` | `/api/textbook` | List chapters available to study (drafts excluded) |
| `GET` | `/api/textbook/{doc_id}/status` | Whether a chapter is a `draft` or `finalized` |
| `POST` | `/api/textbook/{doc_id}/finalize` | Approve a reviewed draft: generate its questions and open it to study |
| `GET` | `/api/graph/{doc_id}` | The chapter's concept dependency graph |
| `POST` | `/api/graph/{doc_id}/concepts` | Draft only: add a concept |
| `PATCH` | `/api/graph/{doc_id}/concepts/{concept_id}` | Draft only: edit a concept (including accepting evidence quotes) |
| `DELETE` | `/api/graph/{doc_id}/concepts/{concept_id}` | Draft only: delete a concept |
| `POST` | `/api/graph/{doc_id}/concepts/{concept_id}/evidence` | Draft only: propose verbatim chapter evidence for a concept |
| `POST` | `/api/graph/{doc_id}/concepts/{concept_id}/prereqs` | Draft only: add a prerequisite (rejects cycles) |
| `DELETE` | `/api/graph/{doc_id}/concepts/{concept_id}/prereqs/{prereq_id}` | Draft only: remove a prerequisite |
| `GET` | `/api/questions/{concept_id}` | Generated question set for a concept |
| `POST` | `/api/study-session/start` | Start a tutoring study session for a `doc_id` |
| `GET` | `/api/study-session` | List unfinished sessions, most recently updated first |
| `GET` | `/api/study-session/{study_session_id}` | Fetch study session state |
| `POST` | `/api/study-session/{study_session_id}/answer` | Submit an answer; returns evaluation, optional diagnosis, next question |
| `POST` | `/api/study-session/{study_session_id}/override` | Dispute the most recent incorrect grade and advance as if correct |
| `DELETE` | `/api/study-session/{study_session_id}` | Delete a session and its history |
| `GET` | `/api/health` | Liveness check |

## Where the real logic goes

All five LLM seams are done. Four call Claude with a JSON-schema-constrained response:

- `backend/app/services/evaluator.py` — grades the student's answer against the question's required points (`claude-haiku-4-5`)
- `backend/app/services/graph_builder.py` — extracts concepts + evidence-grounded prerequisite edges from chapter text (`claude-haiku-4-5`)
- `backend/app/services/question_generator.py` — generates an evidence-grounded question set per concept from a fixed type taxonomy, each with a model answer and required points (`claude-sonnet-4-6`)
- `backend/app/services/evidence_finder.py` — during graph review, proposes verbatim chapter passages for a concept or prerequisite link, discarding anything that isn't an exact quote (`claude-haiku-4-5`)

The fifth is shaped differently:

- `backend/app/services/diagnoser.py` — not a single structured call but a bounded agentic tool-calling loop over Claude (`claude-sonnet-4-6`) that walks prerequisites, checks for a reusable question, and generates a new targeted one, gated by a code-enforced certainty check (design doc: `docs/specs/2026-08-10-diagnoser-agentic-pipeline-design.md`)

Storage lives behind the `Store` abstract class (`backend/app/store/memory_store.py`): `InMemoryStore` by default, or `PostgresStore` (`backend/app/store/postgres_store.py`) when `DATABASE_URL` is set — `get_store()` picks between them, so nothing else in the app needs to know which backend is active (design doc: `docs/specs/2026-08-21-persistent-storage-design.md`).
