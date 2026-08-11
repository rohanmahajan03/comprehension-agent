# comprehension-agent

Diagnosing EXACTLY what you don't understand from your reading — an adaptive tutor that ingests textbook chapters, builds a concept dependency graph, and runs a question/answer loop that traces wrong answers back to the prerequisite concept actually at fault.

**Current state:** three of the four LLM seams are wired up for real. Concept extraction (`graph_builder.py`), question generation (`question_generator.py`), and answer grading (`evaluator.py`) all call Claude. Gap diagnosis (`diagnoser.py`) is still stubbed — it always picks the concept's first prerequisite instead of reasoning about which one the wrong answer actually implicates — and is the next piece of real logic to build.

## How it works

### Pipeline 1 — Pre-questioning (runs once per uploaded chapter)

Upload textbook chapter → build dependency graph (extract concepts and prerequisite links) → generate a question set per concept node.

Implemented as: `POST /api/textbook` → `services/graph_builder.py` → `services/question_generator.py`, all synchronous for now. Both are real: `graph_builder.py` calls Claude (`claude-haiku-4-5`) to extract concepts and prerequisite edges from the chapter text, grounding every edge in a verbatim quote and dropping any edge that would introduce a cycle. `question_generator.py` calls Claude (`claude-sonnet-4-6`) once per concept to generate a set of evidence-grounded questions from a fixed taxonomy (conceptual correctness, conceptual distinction, enumeration completeness, open-ended example, applied reasoning), skipping any type that doesn't genuinely fit the concept. Both need a valid `LLM_API_KEY` in `.env` (see Prerequisites).

### Pipeline 2 — Question/answer diagnostic loop (runs per study session)

Ask a question targeting a concept → evaluate the answer.

- **Correct** → advance to the next concept (in prerequisite order) and loop back to asking.
- **Incorrect** → check the concept's dependencies → diagnose the suspected gap → ask a targeted question probing that prerequisite → loop back to evaluation, potentially recursing into deeper dependencies until the root gap is found.

Implemented as: `POST /api/study-session/{id}/answer` → `services/evaluator.py`, and on a wrong answer `services/diagnoser.py`. Answer grading is real: `evaluator.py` calls Claude (`claude-haiku-4-5`) to check the student's answer against the question's rubric and return a structured `{correct, explanation}` — this needs a valid `LLM_API_KEY` in `.env` (see Prerequisites).

**Next up:** `diagnoser.py`'s prerequisite-walking is still stubbed — it always picks the concept's first `depends_on` entry (or the concept itself if it has none) rather than reasoning about which prerequisite the wrong answer actually implicates, and it doesn't recurse into deeper dependencies on repeated wrong answers. Replacing this stub with a real LLM call is the next piece of work.

### ID conventions (load-bearing)

Concept ids are `{doc_id}:{slug}`; question ids are `{concept_id}:{suffix}` (`q1`, `q2`, `diagnostic`). The study-session router resolves an answered question by stripping the id back to its concept (`question_id.rsplit(":", 1)[0]`) and looking it up in that concept's question set — diagnostic questions get appended to the store under their concept when generated so this resolution keeps working for them too.

## Prerequisites

- Docker + Docker Compose (that's all for the containerized quickstart)
- For native development: Python ≥ 3.11 and Node ≥ 20
- An Anthropic API key in `.env` as `LLM_API_KEY` — needed for both pipelines: uploading a chapter (`graph_builder.py` + `question_generator.py`) and submitting answers in a study session (`evaluator.py`) all make real Claude calls. Only gap diagnosis on a wrong answer (`diagnoser.py`) still works without one, since it's stubbed.

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

Free and deterministic — `evaluator.py`, `graph_builder.py`, and `question_generator.py` are all stubbed for these via autouse fixtures in `tests/conftest.py` (the graph_builder stub returns a fixed 5-concept calculus graph; the question_generator stub returns two templated questions per concept).

There are also three live G-Eval-style regression suites (using [DeepEval](https://github.com/confident-ai/deepeval)) that exercise the real LLM calls end-to-end and make real, **billed** Anthropic API calls, so none of them run as part of the default `pytest` — each auto-skips without an `LLM_API_KEY`:

- `backend/tests/geval/` — grades `evaluator.evaluate()` against 10 questions / 42 answer variants (~$0.35–0.45, ~5-6 minutes per full run)
- `backend/tests/graph_geval/` — grades `graph_builder.build_graph()`'s extracted concepts/edges against a golden set (`tests/graph_golden_set.md`), using a judge LLM call for concept alignment
- `backend/tests/question_geval/` — grades `question_generator.generate_questions()`'s output against a golden set

To run any of them:

```bash
cd backend
set -a && source ../.env && set +a
.venv/bin/pytest tests/geval -v            # or tests/graph_geval, tests/question_geval
```

## API surface

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/textbook` | Upload chapter text; builds graph + questions, returns `doc_id` |
| `GET` | `/api/graph/{doc_id}` | The chapter's concept dependency graph |
| `GET` | `/api/questions/{concept_id}` | Generated question set for a concept |
| `POST` | `/api/study-session/start` | Start a tutoring study session for a `doc_id` |
| `GET` | `/api/study-session/{study_session_id}` | Fetch study session state |
| `POST` | `/api/study-session/{study_session_id}/answer` | Submit an answer; returns evaluation, optional diagnosis, next question |
| `GET` | `/api/health` | Liveness check |

## Where the real logic goes

Three of the four LLM seams are done, each calling Claude with a JSON-schema-constrained response:

- `backend/app/services/evaluator.py` — grades the student's answer against the question's rubric (`claude-haiku-4-5`)
- `backend/app/services/graph_builder.py` — extracts concepts + evidence-grounded prerequisite edges from chapter text (`claude-haiku-4-5`)
- `backend/app/services/question_generator.py` — generates an evidence-grounded question set per concept from a fixed type taxonomy (`claude-sonnet-4-6`)

**Next up:** `backend/app/services/diagnoser.py` — prerequisite-walking gap diagnosis + targeted question generation — is still a stub, a single function with a `# TODO:` describing what replaces it: given a wrong answer, call an LLM with the answer plus prerequisite summaries to decide which prerequisite the misunderstanding most likely stems from (instead of always picking the first `depends_on` entry), and recurse into deeper dependencies on repeated wrong answers until the root gap is found. The other three services are the template to follow.

Storage is in-memory (`backend/app/store/memory_store.py`) behind the `Store` abstract class — swapping in Postgres later means adding a subclass and changing `get_store()`.
