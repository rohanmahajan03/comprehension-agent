# CLAUDE.md

Adaptive concept tutor: ingests textbook chapters, builds a concept dependency graph, and runs a Q&A loop that traces wrong answers back to the prerequisite concept at fault. `evaluator.py` (pipeline 2, step 2) and `graph_builder.py` (pipeline 1, step 2) now make real LLM calls; `question_generator.py` and `diagnoser.py` are still stubbed.

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

# Backend tests (free — evaluator and graph_builder are stubbed via tests/conftest.py, geval/graph_geval suites auto-skip)
cd backend && .venv/bin/pytest

# G-Eval regression suite for evaluator.py (real, billed Anthropic API calls — see Testing below)
cd backend && set -a && source ../.env && set +a && .venv/bin/pytest tests/geval -v

# Structural regression suite for graph_builder.py (real, billed Anthropic API calls — see Testing below)
cd backend && set -a && source ../.env && set +a && .venv/bin/pytest tests/graph_geval -v

# Frontend natively
cd frontend && npm install && npm run dev   # proxies /api to :8000
npm run build                                # tsc -b && vite build
```

## Architecture

Two pipelines in `backend/app/services/`:

1. **Pre-questioning** (per uploaded chapter): `POST /api/textbook` → `graph_builder.build_graph()` (real LLM call) → `question_generator.generate_questions()` per concept (still stubbed), all synchronous, results saved to the store.
2. **Diagnostic loop** (per study session): `POST /api/study-session/{id}/answer` → `evaluator.evaluate()`. Correct → advance `current_concept_id` in topological order. Incorrect → `diagnoser.diagnose()` returns a targeted question probing a prerequisite; study session status becomes `diagnosing`. `evaluator.evaluate()` is real (`diagnoser.py` is still stubbed).

`evaluator.py` calls `claude-haiku-4-5` via the Anthropic SDK with a JSON-schema-constrained response (`_OUTPUT_SCHEMA`) grading the student's answer against `question.expected_answer_notes`. It's the template `graph_builder.py` followed, and the one still to follow when de-stubbing `question_generator.py`/`diagnoser.py`. Known issue: the `temperature=0` call parameter is currently commented out, which means grading is **not deterministic** — the same question/answer pair can flip between `correct: true/false` across calls. Re-enabling it is recommended; the `tests/geval` suite (see Testing below) is what surfaced this.

`graph_builder.py` calls `claude-haiku-4-5` (with `temperature=0`, unlike `evaluator.py`) with a JSON-schema-constrained response asking for `{concepts: [{id, label, summary}], edges: [{from, to, evidence}]}` extracted from the chapter text. `_extract_raw_graph()` does the LLM call + parsing + dedup and returns that raw shape (still carrying each edge's `evidence` quote) — it's an internal seam, not stable public API, kept separate purely so `tests/graph_geval` can grade edge evidence, which the public `build_graph()` discards once it folds `edges` into each `Concept.depends_on` (`to` depends on `from`). `build_graph()` also skips any edge that would introduce a cycle when building `depends_on`, since `topological_order` (`graphlib.TopologicalSorter`) assumes a DAG and would otherwise raise unhandled.

Key seams:

- **Storage**: `backend/app/store/memory_store.py` — abstract `Store` class + `InMemoryStore` + `get_store()` factory (lru_cache singleton). Swapping in Postgres = new subclass + change `get_store()`.
- **Models**: `backend/app/models/schemas.py` is the source of truth; `frontend/src/types/index.ts` mirrors it **by hand — keep them in sync** (includes `AnswerResponse`, the answer-endpoint envelope). The study-session domain model is named `StudySession`/`StudySessionStatus` (not `Session`) specifically so it won't collide with a future DB session object (e.g. SQLAlchemy's `Session`) once Postgres is wired in.
- **ID conventions (load-bearing)**: concept ids are `{doc_id}:{slug}`, question ids are `{concept_id}:{suffix}` (`q1`, `q2`, `diagnostic`). The study-session router (`routers/study_session.py`) resolves an answered question by `question_id.rsplit(":", 1)[0]` → concept's question set. Diagnostic questions are appended to the store's question set for their concept when generated, so answers to them resolve too.
- Concept ordering uses `graphlib.TopologicalSorter` (`graph_builder.topological_order`).

## Stub behavior (intentional, don't "fix")

- `question_generator.py` ignores the source chapter text and returns two templated questions per concept ("explain X" / "give an example of X").
- `diagnoser.py` always picks the concept's **first** `depends_on` entry (or the concept itself if none). Targeted-question prompts must not embed `suspect.summary` (it leaks the answer); the summary belongs in `expected_answer_notes`.

`evaluator.py` and `graph_builder.py` are no longer part of this list — both make real LLM calls (see Architecture above). `tests/conftest.py` still stubs them (`stub_evaluator` alternates correct/incorrect via a global counter; `stub_graph_builder` returns the old fixed 5-concept calculus graph) for the rest of the test suite, so `test_flow.py` and friends stay free and deterministic.

## Testing

- **Stub-backed tests** (`backend/tests/test_flow.py`, `test_health.py`): free, fast, no API key needed. `tests/conftest.py` monkeypatches `evaluator.evaluate` and `graph_builder.build_graph` with deterministic stubs (autouse fixtures) so these never hit the real API.
- **`backend/tests/geval/`** — a G-Eval regression suite (via [DeepEval](https://github.com/confident-ai/deepeval)) that runs the *real* `evaluator.evaluate()` against the 10 questions/42 answer variants in `tests/geval_test_suite.md`, then scores the evaluator's explanation against the golden answer using a `GEval` metric judged by a separate model (`claude-opus-4-5`, deliberately different/stronger than the `claude-haiku-4-5` evaluator under test, to avoid a model grading its own homework).
  - Organized one file per chapter (`test_ch1.py`…`test_ch8.py`), one test function per question/answer-variant pair.
  - `criteria.py` holds each question's G-Eval `criteria` (copied from the markdown) and `evaluation_steps`, hand-derived and **hardcoded** — GEval would otherwise regenerate steps via an LLM call on every run, making the rubric non-deterministic across runs. If a question's criterion changes, regenerate its steps by hand and update `criteria.py`; don't let evaluation_steps go unset.
  - `tests/geval/conftest.py` overrides the parent `stub_evaluator` fixture as a no-op (real calls needed) and skips the whole directory if `LLM_API_KEY` is unset, so CI (which has no key) stays green.
  - **Makes real, billed Anthropic API calls** — roughly $0.35–0.45 and 5-6 minutes for a full run (Opus judge calls dominate cost). Don't run this suite reflexively; it's for validating changes to `evaluator.py`'s prompt/model.
  - As of the last full run: 39/42 passing. The 3 known failures are real evaluator leniency gaps (not suite bugs) — see git history around the `evaluator implementation done` / `g-eval test suite` commits for details.
- **`backend/tests/graph_geval/`** — a structural regression suite for `graph_builder.py`, built from the 4 DDIA excerpts in `tests/graph_golden_set.md` (hand-curated expected concepts/edges/"forbidden" ideas per case). Different shape than `tests/geval/` since the output under test is a graph, not free text:
  - Runs the real `graph_builder._extract_raw_graph()` on each case's source text, then aligns the extracted concepts to the golden concepts by meaning via a judge LLM call (`claude-sonnet-4-5` — cheaper than Opus since this is structural matching, not open-ended judgment; still stronger than the `claude-haiku-4-5` extractor under test). Edge quoted-evidence is checked deterministically (no LLM call): every edge's `evidence` must be a verbatim (whitespace-normalized) substring of the source text.
  - `golden.py` hardcodes each case's expected concepts/edges/forbidden-ideas; source text itself is *not* duplicated there — it's parsed straight out of `graph_golden_set.md`'s fenced code blocks so it can never drift from what the evidence check validates against.
  - One file per case (`test_case1.py`…`test_case4.py`), 4 tests each: concept recall ≥ 0.8, zero forbidden-idea leaks, edge recall ≥ 0.6, all edge evidence verbatim. `support.score_case()` is `lru_cache`d per case so those 4 assertions share one extraction call + one alignment call rather than re-running the real API per assertion.
  - `tests/graph_geval/conftest.py` overrides the parent `stub_graph_builder` fixture as a no-op and skips the whole directory if `LLM_API_KEY` is unset, same pattern as `tests/geval/`.
  - As of the first full run: 8/16 passing. Spot-checked each failure against the raw model output — none are harness bugs, all are genuine gaps in current `graph_builder.py` output: (1) edge recall is the weakest area — the model frequently extracts the right concepts but under-connects them (e.g. Case 4's `oltp → olap → data_warehouse` backbone edges are missing even though all three concepts matched); (2) some individually quiz-worthy sub-concepts (Case 2's `dirty_read`/`dirty_write`/`read_skew`/`race_condition`) are getting folded away — likely a side effect of the "be strict about what counts as a concept" prompt tightening earlier in this suite's development; (3) two forbidden-idea leaks (Case 2's "Weak Isolation Levels" and Case 3's generic "Index" each got their own node despite the source text treating them as folded-in/anti-pattern); (4) two edges with paraphrased-not-verbatim evidence quotes. Not yet triaged into "prompt needs tuning" vs. "golden expectations too strict" — see conversation/PR history for the analysis.

## Docker gotchas

- `docker-compose.override.yml` (auto-merged) is dev mode: vite dev server (Dockerfile `dev` target), `uvicorn --reload`, bind mounts. It uses `ports: !override` to replace (not append to) the base port mapping, and a **distinct image tag** (`comprehension-agent-frontend-dev`) so dev/prod builds don't clobber each other — if the frontend serves nothing on :5173, a stale image from the other mode is the likely cause; rebuild with `--build`.
- Prod frontend: nginx serves `dist/` and proxies `/api` → `backend:8000` (`frontend/nginx.conf`). Dev: vite proxies `/api` using `BACKEND_URL` env var (`vite.config.ts`).
- Backend `env_file: .env` means compose fails without `.env` — copy from `.env.example`.

## Not built yet (deliberate)

No persistent DB, no auth. Question generation and gap diagnosis (`question_generator.py`, `diagnoser.py`) are still stubbed — answer grading (`evaluator.py`) and concept-graph extraction (`graph_builder.py`) make real LLM calls so far. CI (`.github/workflows/ci.yml`) only runs backend pytest (stub-backed tests; `tests/geval` and `tests/graph_geval` auto-skip without `LLM_API_KEY`) + frontend build — it does not run either live regression suite.
