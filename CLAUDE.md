# CLAUDE.md

Adaptive concept tutor: ingests textbook chapters, builds a concept dependency graph, and runs a Q&A loop that traces wrong answers back to the prerequisite concept at fault. Currently an infrastructure skeleton — all tutoring/LLM logic is stubbed.

## Commands

```bash
# Full stack, dev mode (hot reload both services via bind mounts)
cp .env.example .env          # once
docker compose up             # frontend :5173, backend :8000

# Production-like (nginx serving built frontend, no mounts)
docker compose -f docker-compose.yml up --build

# Backend natively
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"       # uv works too: uv sync --extra dev
uvicorn app.main:app --reload

# Backend tests
cd backend && .venv/bin/pytest

# Frontend natively
cd frontend && npm install && npm run dev   # proxies /api to :8000
npm run build                                # tsc -b && vite build
```

## Architecture

Two pipelines, both stubbed in `backend/app/services/` (each stub has a `# TODO:` describing the real LLM logic that replaces it):

1. **Pre-questioning** (per uploaded chapter): `POST /api/textbook` → `graph_builder.build_graph()` → `question_generator.generate_questions()` per concept, all synchronous, results saved to the store.
2. **Diagnostic loop** (per study session): `POST /api/study-session/{id}/answer` → `evaluator.evaluate()`. Correct → advance `current_concept_id` in topological order. Incorrect → `diagnoser.diagnose()` returns a targeted question probing a prerequisite; study session status becomes `diagnosing`.

Key seams:

- **Storage**: `backend/app/store/memory_store.py` — abstract `Store` class + `InMemoryStore` + `get_store()` factory (lru_cache singleton). Swapping in Postgres = new subclass + change `get_store()`.
- **Models**: `backend/app/models/schemas.py` is the source of truth; `frontend/src/types/index.ts` mirrors it **by hand — keep them in sync** (includes `AnswerResponse`, the answer-endpoint envelope). The study-session domain model is named `StudySession`/`StudySessionStatus` (not `Session`) specifically so it won't collide with a future DB session object (e.g. SQLAlchemy's `Session`) once Postgres is wired in.
- **ID conventions (load-bearing)**: concept ids are `{doc_id}:{slug}`, question ids are `{concept_id}:{suffix}` (`q1`, `q2`, `diagnostic`). The study-session router (`routers/study_session.py`) resolves an answered question by `question_id.rsplit(":", 1)[0]` → concept's question set. Diagnostic questions are appended to the store's question set for their concept when generated, so answers to them resolve too.
- Concept ordering uses `graphlib.TopologicalSorter` (`graph_builder.topological_order`).

## Stub behavior (intentional, don't "fix")

- `evaluator.py` alternates correct/incorrect via a **global** module-level counter — not per-study-session, ignores answer text. Exists so the UI exercises both branches.
- `graph_builder.py` ignores the uploaded text and always returns the same 5-concept calculus graph.
- `diagnoser.py` always picks the concept's **first** `depends_on` entry (or the concept itself if none). Targeted-question prompts must not embed `suspect.summary` (it leaks the answer); the summary belongs in `expected_answer_notes`.

## Docker gotchas

- `docker-compose.override.yml` (auto-merged) is dev mode: vite dev server (Dockerfile `dev` target), `uvicorn --reload`, bind mounts. It uses `ports: !override` to replace (not append to) the base port mapping, and a **distinct image tag** (`comprehension-agent-frontend-dev`) so dev/prod builds don't clobber each other — if the frontend serves nothing on :5173, a stale image from the other mode is the likely cause; rebuild with `--build`.
- Prod frontend: nginx serves `dist/` and proxies `/api` → `backend:8000` (`frontend/nginx.conf`). Dev: vite proxies `/api` using `BACKEND_URL` env var (`vite.config.ts`).
- Backend `env_file: .env` means compose fails without `.env` — copy from `.env.example`.

## Not built yet (deliberate)

No real LLM calls, no persistent DB, no auth. CI (`.github/workflows/ci.yml`) only runs backend pytest + frontend build.
