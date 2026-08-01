# comprehension-agent

Diagnosing EXACTLY what you don't understand from your reading — an adaptive tutor that ingests textbook chapters, builds a concept dependency graph, and runs a question/answer loop that traces wrong answers back to the prerequisite concept actually at fault.

**Current state:** full infrastructure skeleton. All LLM/tutoring logic is stubbed with mock implementations (marked with `# TODO:` in `backend/app/services/`) that return plausible sample data, so the app runs end-to-end out of the box.

## How it works

### Pipeline 1 — Pre-questioning (runs once per uploaded chapter)

Upload textbook chapter → build dependency graph (extract concepts and prerequisite links) → generate a question set per concept node.

Implemented as: `POST /api/textbook` → `services/graph_builder.py` → `services/question_generator.py`, all synchronous for now.

### Pipeline 2 — Question/answer diagnostic loop (runs per study session)

Ask a question targeting a concept → evaluate the answer.

- **Correct** → advance to the next concept (in prerequisite order) and loop back to asking.
- **Incorrect** → check the concept's dependencies → diagnose the suspected gap → ask a targeted question probing that prerequisite → loop back to evaluation, potentially recursing into deeper dependencies until the root gap is found.

Implemented as: `POST /api/study-session/{id}/answer` → `services/evaluator.py`, and on a wrong answer `services/diagnoser.py`.

### ID conventions (load-bearing)

Concept ids are `{doc_id}:{slug}`; question ids are `{concept_id}:{suffix}` (`q1`, `q2`, `diagnostic`). The study-session router resolves an answered question by stripping the id back to its concept (`question_id.rsplit(":", 1)[0]`) and looking it up in that concept's question set — diagnostic questions get appended to the store under their concept when generated so this resolution keeps working for them too.

## Prerequisites

- Docker + Docker Compose (that's all for the containerized quickstart)
- For native development: Python ≥ 3.11 and Node ≥ 20

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

Every stub is a single function with a `# TODO:` describing what replaces it:

- `backend/app/services/graph_builder.py` — concept extraction + dependency inference from chapter text
- `backend/app/services/question_generator.py` — per-concept question generation
- `backend/app/services/evaluator.py` — answer grading (currently alternates correct/incorrect so the UI exercises both branches)
- `backend/app/services/diagnoser.py` — prerequisite-walking gap diagnosis + targeted question generation

Storage is in-memory (`backend/app/store/memory_store.py`) behind the `Store` abstract class — swapping in Postgres later means adding a subclass and changing `get_store()`.
