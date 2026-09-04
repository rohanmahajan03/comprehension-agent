# comprehension-agent

Diagnosing EXACTLY what you don't understand from your reading — an adaptive tutor that ingests textbook chapters, builds a concept dependency graph, and runs a question/answer loop that traces wrong answers back to the prerequisite concept actually at fault.

**Current state:** all four LLM seams are wired up for real. Concept extraction (`graph_builder.py`), question generation (`question_generator.py`), answer grading (`evaluator.py`), and gap diagnosis (`diagnoser.py`) all call Claude — the last one runs a bounded agentic tool-calling loop rather than a single structured call (see below). Storage defaults to an in-memory store; set `DATABASE_URL` in `.env` to persist everything in Postgres instead. The frontend supports more than one document/session at a time: a menu screen lists every unfinished session so you can resume or delete one before uploading a new chapter.

## How it works

### Pipeline 1 — Pre-questioning (runs once per uploaded chapter)

Upload textbook chapter → build dependency graph (extract concepts and prerequisite links) → generate a question set per concept node.

Implemented as: `POST /api/textbook` → `services/graph_builder.py` → `services/question_generator.py`, all synchronous for now. Both are real: `graph_builder.py` calls Claude (`claude-haiku-4-5`) to extract concepts and prerequisite edges from the chapter text, grounding every edge in a verbatim quote and dropping any edge that would introduce a cycle. `question_generator.py` calls Claude (`claude-sonnet-4-6`) once per concept to generate a set of evidence-grounded questions from a fixed taxonomy (conceptual correctness, conceptual distinction, enumeration completeness, open-ended example, applied reasoning), skipping any type that doesn't genuinely fit the concept. Both need a valid `LLM_API_KEY` in `.env` (see Prerequisites).

### Pipeline 2 — Question/answer diagnostic loop (runs per study session)

Ask a question targeting a concept → evaluate the answer.

- **Correct** → advance to the next concept (in prerequisite order) and loop back to asking.
- **Incorrect** → check the concept's dependencies → diagnose the suspected gap → ask a targeted question probing that prerequisite → loop back to evaluation, potentially recursing into deeper dependencies until the root gap is found.

Implemented as: `POST /api/study-session/{id}/answer` → `services/evaluator.py`, and on a wrong answer `services/diagnoser.py`. Both are real. `evaluator.py` calls Claude (`claude-haiku-4-5`) to check the student's answer against the question's rubric and return a structured `{correct, explanation}`. `diagnoser.py` runs a bounded agentic tool-calling loop over Claude (`claude-sonnet-4-6`, up to 5 turns) rather than a single call: it can walk prerequisites to arbitrary depth, check whether an existing question already probes the suspected gap, or generate a new targeted one — and a code-enforced certainty gate means it can't end the loop on anything less than high confidence (design doc: `docs/specs/2026-08-10-diagnoser-agentic-pipeline-design.md`). Both need a valid `LLM_API_KEY` in `.env` (see Prerequisites).

### Resuming and deleting sessions

The menu screen lists every unfinished session (any that hasn't reached `completed`), most recently updated first, so you can pick up a study session across page reloads or upload another chapter without losing progress on the current one. Each row also has a delete option, with an inline confirmation before it actually removes the session and its history.

Implemented as: `GET /api/study-session` for the list, `DELETE /api/study-session/{id}` to remove one. A session drops off the list automatically once completed; delete is a separate, explicit action that works at any status.

### ID conventions (load-bearing)

Concept ids are `{doc_id}:{slug}`; question ids are `{concept_id}:{suffix}` (`q1`, `q2`, `diagnostic1`, `diagnostic2`, …, numbered since one concept can be diagnosed more than once in a session). The study-session router resolves an answered question by stripping the id back to its concept (`question_id.rsplit(":", 1)[0]`) and looking it up in that concept's question set — diagnostic questions get appended to the store under their concept when generated so this resolution keeps working for them too.

## Prerequisites

- Docker + Docker Compose (that's all for the containerized quickstart)
- For native development: Python ≥ 3.11 and Node ≥ 20
- An Anthropic API key in `.env` as `LLM_API_KEY` — every real LLM call needs it: uploading a chapter (`graph_builder.py` + `question_generator.py`), submitting an answer (`evaluator.py`), and diagnosing a wrong one (`diagnoser.py`).
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

Free and deterministic — `evaluator.py`, `graph_builder.py`, `question_generator.py`, and `diagnoser.py` are all stubbed for these via autouse fixtures in `tests/conftest.py` (the graph_builder stub returns a fixed 5-concept calculus graph; the question_generator stub returns two templated questions per concept; the diagnoser stub picks the concept's first prerequisite — the old pre-agentic behavior).

`backend/tests/test_postgres_store.py` is also free (no LLM calls) but needs a real Postgres instance, so it auto-skips unless `DATABASE_URL`/`TEST_DATABASE_URL` is set — see `CLAUDE.md` for the exact setup (it truncates its tables before every test, so it's pointed at a dedicated `_test`-suffixed database, never the working one).

There are also four live G-Eval-style regression suites (using [DeepEval](https://github.com/confident-ai/deepeval)) that exercise the real LLM calls end-to-end and make real, **billed** Anthropic API calls, so none of them run as part of the default `pytest` — each auto-skips without an `LLM_API_KEY`:

- `backend/tests/geval/` — grades `evaluator.evaluate()` against 10 questions / 42 answer variants (~$0.35–0.45, ~5-6 minutes per full run)
- `backend/tests/graph_geval/` — grades `graph_builder.build_graph()`'s extracted concepts/edges against a golden set (`tests/graph_golden_set.md`), using a judge LLM call for concept alignment
- `backend/tests/question_geval/` — grades `question_generator.generate_questions()`'s output against a golden set
- `backend/tests/diagnoser_geval/` — grades `diagnoser.py`'s agentic loop against 9 hand-authored diagnosis cases: suspect accuracy by hop depth, zero-tolerance invariants (no answer leaks into the targeted question), and two judged checks on question relevance and reasoning quality

To run any of them:

```bash
cd backend
set -a && source ../.env && set +a
.venv/bin/pytest tests/geval -v            # or tests/graph_geval, tests/question_geval, tests/diagnoser_geval
```

## API surface

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/textbook` | Upload chapter text; builds graph + questions, returns `doc_id` |
| `GET` | `/api/graph/{doc_id}` | The chapter's concept dependency graph |
| `GET` | `/api/questions/{concept_id}` | Generated question set for a concept |
| `POST` | `/api/study-session/start` | Start a tutoring study session for a `doc_id` |
| `GET` | `/api/study-session` | List unfinished sessions, most recently updated first |
| `GET` | `/api/study-session/{study_session_id}` | Fetch study session state |
| `POST` | `/api/study-session/{study_session_id}/answer` | Submit an answer; returns evaluation, optional diagnosis, next question |
| `DELETE` | `/api/study-session/{study_session_id}` | Delete a session and its history |
| `GET` | `/api/health` | Liveness check |

## Where the real logic goes

All four LLM seams are done. Three call Claude with a JSON-schema-constrained response:

- `backend/app/services/evaluator.py` — grades the student's answer against the question's rubric (`claude-haiku-4-5`)
- `backend/app/services/graph_builder.py` — extracts concepts + evidence-grounded prerequisite edges from chapter text (`claude-haiku-4-5`)
- `backend/app/services/question_generator.py` — generates an evidence-grounded question set per concept from a fixed type taxonomy (`claude-sonnet-4-6`)

The fourth is shaped differently:

- `backend/app/services/diagnoser.py` — not a single structured call but a bounded agentic tool-calling loop over Claude (`claude-sonnet-4-6`) that walks prerequisites, checks for a reusable question, and generates a new targeted one, gated by a code-enforced certainty check (design doc: `docs/specs/2026-08-10-diagnoser-agentic-pipeline-design.md`)

Storage lives behind the `Store` abstract class (`backend/app/store/memory_store.py`): `InMemoryStore` by default, or `PostgresStore` (`backend/app/store/postgres_store.py`) when `DATABASE_URL` is set — `get_store()` picks between them, so nothing else in the app needs to know which backend is active (design doc: `docs/specs/2026-08-21-persistent-storage-design.md`).
