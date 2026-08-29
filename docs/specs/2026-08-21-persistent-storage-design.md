# Persistent storage — design

**Status:** approved, not yet implemented
**Scope:** replaces `InMemoryStore` with a real, persistent backend. Touches `backend/app/store/`, adds `backend/app/db/`, adds `backend/alembic/`, touches `docker-compose.yml`, `.env.example`, `config.py`.

## 1. Context

Everything the app persists — documents, dependency graphs, questions, study sessions — currently lives in `InMemoryStore`, a set of plain Python dicts behind the `Store` ABC (`backend/app/store/memory_store.py`). It doesn't survive a process restart, and `CLAUDE.md` has called this out as deliberately unfinished since the project's start: "Swapping storage backends = new subclass + change `get_store()` — nothing else should need to change." This is that swap.

The initial framing for this work proposed a dedicated graph database for the dependency graph alongside Postgres for everything else. That's rejected below (§2) in favor of one Postgres database for all of it — the reasoning is worth keeping in the doc because it's the decision the rest of this design rests on.

## 2. Decision: one Postgres database, no separate graph DB

Every dependency graph in this app is scoped to one document, loaded whole (`get_graph(doc_id)` returns the entire graph — nothing today queries a partial one), and small: the golden test fixtures run 10-15 concepts, and a real textbook chapter is unlikely to be dramatically larger. The existing code already reflects this — `graph_builder.topological_order()` loads the whole graph into memory and runs `graphlib.TopologicalSorter` in Python; nothing issues a graph-shaped query against a store today.

A dedicated graph database (Neo4j, etc.) would add a second database technology, a second query language, and a second service to deploy and back up, for graphs too small to need it. Worse, it would split `Concept` and its `Question`s across two databases when they're already tightly coupled — the diagnostic-question registration bug fixed earlier in this project (a question written to the store's index but not mirrored onto the graph object) is exactly the class of bug that splitting storage technologies makes structurally worse, not better, since keeping two databases in sync needs either a distributed transaction or accepted drift.

**Decision: single Postgres instance, no graph database.** Concepts are rows; `depends_on` and `evidence` are JSONB columns rather than a normalized edge table, since nothing queries an edge independent of loading its whole document's graph — normalizing would add joins with no query it enables.

A middle option (Postgres + the Apache AGE extension, for Cypher-style queries without a second server) was considered and set aside for the same reason: no query in this app would use it.

## 3. Decision: collapse the questions duplication

Today, a `Concept`'s questions exist in two places kept in sync by hand: nested in `Concept.questions` on the graph object (populated by `question_generator.generate_questions()`, and separately maintained in `study_session.py`'s diagnostic-question mirroring), and independently in the store's per-concept question index (`save_questions`/`get_questions`, used by `routers/questions.py` and `_find_question`). This dual-write is exactly the shape of bug this project has already hit once.

**Decision: `questions` becomes the single source of truth.** One table, `concept_id` as a foreign key. `Concept.questions` is never stored — it's reconstructed by joining `questions` onto `concepts` every time a graph is read. There is no write path that touches both; there's only one write path, to `questions`, and one read path that assembles the nested shape the Pydantic model expects.

Two knock-on simplifications this produces, not just schema tidiness:

- `HistoryEntry.question` and `DiagnosisResult.targeted_question` (in `study_sessions`/`history_entries`, §4) become foreign keys into `questions` rather than embedded copies — a `Question` gets exactly one home anywhere in the schema.
- `study_session.py`'s diagnostic-question mirroring (`suspect.questions.append(targeted); store.save_graph(graph)`) becomes unnecessary. Once `get_graph()` always reconstructs `Concept.questions` from the current contents of `questions`, a plain `store.save_questions(suspect.id, [...])` is sufficient — the concept sees the new question on its very next load, in either backend. `InMemoryStore.get_graph()` needs the equivalent change (rebuild each concept's `questions` from `self._questions` at read time, rather than returning whatever was physically embedded at the last `save_graph` call) so both `Store` implementations honor the same contract. This removes the exact bug class it was written to patch, permanently, in both stores — not just the new one.

## 4. Schema

```sql
documents
  id                  text PRIMARY KEY   -- the doc_id
  text                text NOT NULL

concepts
  id                  text PRIMARY KEY   -- "{doc_id}:{slug}"
  doc_id              text NOT NULL REFERENCES documents(id) ON DELETE CASCADE
  name                text NOT NULL
  summary             text NOT NULL
  depends_on          jsonb NOT NULL DEFAULT '[]'   -- list[str] of concept ids
  evidence            jsonb NOT NULL DEFAULT '{}'   -- dict[str, str]: prereq_id -> quote

questions
  id                  text PRIMARY KEY   -- "{concept_id}:{suffix}"
  concept_id          text NOT NULL REFERENCES concepts(id) ON DELETE CASCADE
  prompt              text NOT NULL
  expected_answer_notes text NOT NULL

study_sessions
  id                  text PRIMARY KEY
  doc_id              text NOT NULL REFERENCES documents(id) ON DELETE CASCADE
  current_concept_id  text
  status              text NOT NULL   -- StudySessionStatus: active | diagnosing | completed

history_entries
  id                  bigserial PRIMARY KEY
  study_session_id    text NOT NULL REFERENCES study_sessions(id) ON DELETE CASCADE
  seq                 int NOT NULL       -- ordering within a session; history is a list, Postgres row order is not guaranteed without this
  question_id                    text NOT NULL REFERENCES questions(id)
  answer_text                    text NOT NULL
  eval_correct                   boolean NOT NULL
  eval_explanation                text NOT NULL
  diagnosis_suspected_concept_id  text
  diagnosis_reasoning             text
  diagnosis_targeted_question_id  text REFERENCES questions(id)

  UNIQUE (study_session_id, seq)
```

Notes on choices not already covered in §2/§3:

- `documents.id`, `concepts.id`, `questions.id`, `study_sessions.id` are `text`, matching the existing id conventions (`{doc_id}:{slug}`, `{concept_id}:{suffix}`, a `uuid4().hex[:12]` for sessions) rather than introducing surrogate integer keys the rest of the app doesn't use.
- `history_entries.id` is the one surrogate key in the schema, and deliberately so: `HistoryEntry` (the Pydantic model) has no `id` field at all — it's an unordered-by-nature list item identified only by its position, which `seq` captures. The `bigserial` PK exists purely so the row can be a foreign-key target and is never surfaced through the `Store` interface or the API.
- `history_entries` is the one genuinely normalized table beyond `questions`/`concepts` — it's the natural shape for `StudySession.history: list[HistoryEntry]`, and `diagnosis_*` columns are nullable as a group since `HistoryEntry.diagnosis` is `None` on every correct answer.
- Cascade deletes follow the existing containment hierarchy (delete a document → its concepts, their questions, and any study sessions against it all go with it) since nothing in the app deletes a document today, but an orphaned row is a worse failure mode than an accidental cascade here.

## 5. Store implementation

`PostgresStore(Store)` in `backend/app/store/postgres_store.py`, alongside the untouched `memory_store.py`. Same method signatures as today — `save_document`, `get_document`, `save_graph`, `get_graph`, `save_questions`, `get_questions`, `save_study_session`, `get_study_session` — so no router changes anywhere in `backend/app/routers/`.

- **SQLAlchemy (sync, 2.0-style) + Alembic**, chosen over raw `psycopg` + hand-written SQL migrations: it's the idiomatic default for a FastAPI app, and Alembic's autogenerate + revision history beats hand-ordered `.sql` files. The tradeoff, accepted deliberately: ORM models live in `backend/app/db/models.py`, entirely separate from the Pydantic schemas in `app/models/schemas.py` — a third representation of each shape (Pydantic ↔ ORM ↔ table) in a codebase that had stayed at two until now. `PostgresStore` is exactly the boundary that converts between them; no SQLAlchemy type leaks past the `Store` interface. Sync engine, not async — matches the codebase's existing plain `def` route handlers (FastAPI already runs those in a threadpool).
- **Session-per-call, no request-scoped session.** `backend/app/db/engine.py` holds a module-level `Engine` + `sessionmaker`, built once from `settings.database_url`. Each `Store` method opens its own short-lived `Session` via a context manager, does one transaction, commits, closes. This keeps `get_store()` a drop-in-compatible singleton exactly as it is today — no FastAPI dependency injection threading a session through every route.
- **`get_store()` picks the backend from config.** `PostgresStore` when `settings.database_url` is set, else `InMemoryStore`. `Settings` gains `database_url: str = ""`, matching the existing `llm_api_key: str = ""` pattern in `config.py`.
- **Consequence: the existing free test suite needs zero changes.** CI and local `pytest` never set `DATABASE_URL`, so `test_flow.py`, `test_health.py`, and every stub-backed test keep exercising `InMemoryStore` exactly as they do today.

### `get_graph` / `save_graph` under the new contract

```
get_graph(doc_id):
    SELECT concepts.*, questions.*
    FROM concepts LEFT JOIN questions ON questions.concept_id = concepts.id
    WHERE concepts.doc_id = :doc_id
  → group rows in Python into Concept(questions=[...]) per concept_id
  → DependencyGraph(doc_id, concepts=[...])

save_graph(graph):
    upsert each concept row (id, doc_id, name, summary, depends_on, evidence)
    — never touches `questions`; see §3.
```

`save_questions(concept_id, questions)` upserts rows in `questions` keyed by `id`, deleting any row for that `concept_id` no longer present in the given list (so a call with a shorter list actually shrinks the set — matching `InMemoryStore.save_questions`'s current replace-the-whole-list semantics).

## 6. Migrations & Docker

One initial Alembic revision creates all five tables from §4. `backend/alembic/env.py` reads `settings.database_url` the same way `db/engine.py` does, so there's one source of truth for the connection string.

**Already done, ahead of the rest of this design** (ticket for this exact request): `docker-compose.yml` has a `postgres` service —

```yaml
postgres:
  image: postgres:16-alpine
  environment:
    - POSTGRES_USER=comprehension_agent
    - POSTGRES_PASSWORD=devpassword
    - POSTGRES_DB=comprehension_agent
  ports:
    - "5433:5432"   # not 5432 — avoids colliding with a locally-installed Postgres
  volumes:
    - postgres_data:/var/lib/postgresql/data
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U comprehension_agent -d comprehension_agent"]
```

verified running and reachable on `localhost:5433` from both inside and outside the container. `backend` does **not** yet `depends_on` it — that wiring was deliberately deferred (see the note in that response) since `backend` doesn't consume `DATABASE_URL` yet and making it wait on a service it doesn't use would just be dead weight in the compose graph. This design is what makes that dependency real, at which point `backend` should gain `depends_on: postgres: condition: service_healthy`.

**Migrations on container startup.** `alembic upgrade head` runs automatically as part of `backend`'s startup (a startup step in `main.py`, or the Dockerfile entrypoint) rather than requiring a manual step — this is a solo/dev-focused project where `docker compose up` "just working" is worth more than the explicitness a manual migration step would buy in a team/production setting.

**`.env.example`** gains a documented `DATABASE_URL=` line, matching the working value already handed over: `postgresql://comprehension_agent:devpassword@localhost:5433/comprehension_agent`. `.env` itself is the user's to edit (not committed, not written by tooling).

## 7. Testing

New `backend/tests/test_postgres_store.py`, skipped when `DATABASE_URL` is unset — the same opt-in pattern already used by `tests/geval`, `tests/graph_geval`, `tests/question_geval`, and `tests/diagnoser_geval`, just gated on database availability instead of `LLM_API_KEY`. Covers:

- Round-trip save/get for every entity (`document`, `graph`, `questions`, `study_session`).
- **The regression this design exists to prevent**: save a graph, then call `save_questions()` for one of its concepts, then call `get_graph()` again and assert the new question appears in `Concept.questions` — without ever touching `save_graph()` a second time. This is the exact bug (§3) made structurally impossible; the test is what proves it.
- `get_study_session()` reconstructs `history` in `seq` order with `question`/`diagnosis.targeted_question` correctly resolved through the `questions` foreign keys.

No testcontainers — tests expect a real Postgres reachable at `DATABASE_URL`, same expectation the `geval` suites have of a real API key. Developers run this against `docker compose up postgres`.

## 8. What's implemented vs. still pending

**Done:** the `postgres` Docker service (§6), verified running and reachable at `postgresql://comprehension_agent:devpassword@localhost:5433/comprehension_agent`.

**Pending** (the implementation plan that follows this spec):
- `Settings.database_url` field in `config.py`.
- `backend/app/db/` — SQLAlchemy engine/session setup (`engine.py`) and ORM models (`models.py`).
- `backend/alembic/` — environment + the one initial revision (§4).
- `backend/app/store/postgres_store.py` implementing `Store` (§5).
- `get_store()` updated to select `PostgresStore` vs `InMemoryStore` based on `settings.database_url`.
- `InMemoryStore.get_graph()` updated to reconstruct `Concept.questions` from `self._questions` at read time (§3), so both backends share the same contract.
- `study_session.py`'s diagnostic-question mirroring simplified back to a single `store.save_questions(...)` call, per §3.
- `backend`'s `docker-compose.yml` entry gains `depends_on: postgres: condition: service_healthy`, and a startup step running `alembic upgrade head`.
- `.env.example` gains the `DATABASE_URL=` line.
- `pyproject.toml` gains `sqlalchemy`, `alembic`, and a Postgres driver (`psycopg[binary]`) as dependencies.
- `backend/tests/test_postgres_store.py` (§7).
- `CLAUDE.md` updated: storage section, new Commands entries for running the migration and the new test suite, and the "Not built yet" list loses persistent storage as an entry.
