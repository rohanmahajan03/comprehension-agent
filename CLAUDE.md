# CLAUDE.md

Adaptive concept tutor: ingests textbook chapters, builds a concept dependency graph, and runs a Q&A loop that traces wrong answers back to the prerequisite concept at fault. `evaluator.py` (pipeline 2, step 2) now makes real LLM calls; `graph_builder.py`, `question_generator.py`, and `diagnoser.py` are still stubbed.

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

# Backend tests (free — evaluator is stubbed via tests/conftest.py, geval suite auto-skips)
cd backend && .venv/bin/pytest

# G-Eval regression suite for evaluator.py (real, billed Anthropic API calls — see Testing below)
cd backend && set -a && source ../.env && set +a && .venv/bin/pytest tests/geval -v

# Frontend natively
cd frontend && npm install && npm run dev   # proxies /api to :8000
npm run build                                # tsc -b && vite build
```

## Architecture

Two pipelines in `backend/app/services/`:

1. **Pre-questioning** (per uploaded chapter): `POST /api/textbook` → `graph_builder.build_graph()` → `question_generator.generate_questions()` per concept, all synchronous, results saved to the store. Still stubbed (`# TODO:` describes the real LLM logic).
2. **Diagnostic loop** (per study session): `POST /api/study-session/{id}/answer` → `evaluator.evaluate()`. Correct → advance `current_concept_id` in topological order. Incorrect → `diagnoser.diagnose()` returns a targeted question probing a prerequisite; study session status becomes `diagnosing`. `evaluator.evaluate()` is real (`diagnoser.py` is still stubbed).

`evaluator.py` calls `claude-haiku-4-5` via the Anthropic SDK with a JSON-schema-constrained response (`_OUTPUT_SCHEMA`) grading the student's answer against `question.expected_answer_notes`. It's the template to follow when de-stubbing the other three services. Known issue: the `temperature=0` call parameter is currently commented out, which means grading is **not deterministic** — the same question/answer pair can flip between `correct: true/false` across calls. Re-enabling it is recommended; the `tests/geval` suite (see Testing below) is what surfaced this.

Key seams:

- **Storage**: `backend/app/store/memory_store.py` — abstract `Store` class + `InMemoryStore` + `get_store()` factory (lru_cache singleton). Swapping in Postgres = new subclass + change `get_store()`.
- **Models**: `backend/app/models/schemas.py` is the source of truth; `frontend/src/types/index.ts` mirrors it **by hand — keep them in sync** (includes `AnswerResponse`, the answer-endpoint envelope). The study-session domain model is named `StudySession`/`StudySessionStatus` (not `Session`) specifically so it won't collide with a future DB session object (e.g. SQLAlchemy's `Session`) once Postgres is wired in.
- **ID conventions (load-bearing)**: concept ids are `{doc_id}:{slug}`, question ids are `{concept_id}:{suffix}` (`q1`, `q2`, `diagnostic`). The study-session router (`routers/study_session.py`) resolves an answered question by `question_id.rsplit(":", 1)[0]` → concept's question set. Diagnostic questions are appended to the store's question set for their concept when generated, so answers to them resolve too.
- Concept ordering uses `graphlib.TopologicalSorter` (`graph_builder.topological_order`).

## Stub behavior (intentional, don't "fix")

- `graph_builder.py` ignores the uploaded text and always returns the same 5-concept calculus graph.
- `question_generator.py` ignores the source chapter text and returns two templated questions per concept ("explain X" / "give an example of X").
- `diagnoser.py` always picks the concept's **first** `depends_on` entry (or the concept itself if none). Targeted-question prompts must not embed `suspect.summary` (it leaks the answer); the summary belongs in `expected_answer_notes`.

`evaluator.py` is no longer part of this list — it makes real LLM calls (see Architecture above). `tests/conftest.py` still stubs it (alternating correct/incorrect via a global counter) for the rest of the test suite, so `test_flow.py` and friends stay free and deterministic.

## Testing

- **Stub-backed tests** (`backend/tests/test_flow.py`, `test_health.py`): free, fast, no API key needed. `tests/conftest.py` monkeypatches `evaluator.evaluate` with an alternating-correct/incorrect stub (autouse fixture) so these never hit the real API.
- **`backend/tests/geval/`** — a G-Eval regression suite (via [DeepEval](https://github.com/confident-ai/deepeval)) that runs the *real* `evaluator.evaluate()` against the 10 questions/42 answer variants in `tests/geval_test_suite.md`, then scores the evaluator's explanation against the golden answer using a `GEval` metric judged by a separate model (`claude-opus-4-5`, deliberately different/stronger than the `claude-haiku-4-5` evaluator under test, to avoid a model grading its own homework).
  - Organized one file per chapter (`test_ch1.py`…`test_ch8.py`), one test function per question/answer-variant pair.
  - `criteria.py` holds each question's G-Eval `criteria` (copied from the markdown) and `evaluation_steps`, hand-derived and **hardcoded** — GEval would otherwise regenerate steps via an LLM call on every run, making the rubric non-deterministic across runs. If a question's criterion changes, regenerate its steps by hand and update `criteria.py`; don't let evaluation_steps go unset.
  - `tests/geval/conftest.py` overrides the parent `stub_evaluator` fixture as a no-op (real calls needed) and skips the whole directory if `LLM_API_KEY` is unset, so CI (which has no key) stays green.
  - **Makes real, billed Anthropic API calls** — roughly $0.35–0.45 and 5-6 minutes for a full run (Opus judge calls dominate cost). Don't run this suite reflexively; it's for validating changes to `evaluator.py`'s prompt/model.
  - As of the last full run: 39/42 passing. The 3 known failures are real evaluator leniency gaps (not suite bugs) — see git history around the `evaluator implementation done` / `g-eval test suite` commits for details.

## Docker gotchas

- `docker-compose.override.yml` (auto-merged) is dev mode: vite dev server (Dockerfile `dev` target), `uvicorn --reload`, bind mounts. It uses `ports: !override` to replace (not append to) the base port mapping, and a **distinct image tag** (`comprehension-agent-frontend-dev`) so dev/prod builds don't clobber each other — if the frontend serves nothing on :5173, a stale image from the other mode is the likely cause; rebuild with `--build`.
- Prod frontend: nginx serves `dist/` and proxies `/api` → `backend:8000` (`frontend/nginx.conf`). Dev: vite proxies `/api` using `BACKEND_URL` env var (`vite.config.ts`).
- Backend `env_file: .env` means compose fails without `.env` — copy from `.env.example`.

## Not built yet (deliberate)

No persistent DB, no auth. Concept extraction, question generation, and gap diagnosis (`graph_builder.py`, `question_generator.py`, `diagnoser.py`) are still stubbed — only answer grading (`evaluator.py`) makes real LLM calls so far. CI (`.github/workflows/ci.yml`) only runs backend pytest (stub-backed tests; `tests/geval` auto-skips without `LLM_API_KEY`) + frontend build — it does not run the live G-Eval suite.
