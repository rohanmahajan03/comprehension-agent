# Resuming a study session — design

**Status:** approved, not yet implemented
**Scope:** makes existing study sessions selectable from the app's entry screen so a user can continue one. Adds one Alembic revision, one endpoint, one store method; touches `backend/app/models/schemas.py`, `backend/app/store/`, `backend/app/routers/{ingestion,study_session}.py`, and most of `frontend/src/`.

## 1. Context

Study sessions are persisted (`study_sessions` + `history_entries`, per the 2026-08-21 storage design) but unreachable once you navigate away. `StudySessionPage` calls `startStudySession(docId)` in its mount effect unconditionally — there is no code path anywhere in the app that opens an existing session. `GET /api/study-session/{id}` exists on the backend and has no caller; `client.ts` doesn't even wrap it.

The practical consequence is visible in the current database: three sessions, two of them on the same document (`fe32c4a9965d`), both sitting on `command_line_interface`. They are duplicates created by visiting the session page twice. Every visit mints another one, and none of them can be returned to.

Two structural gaps block a session list, and both are load-bearing enough to shape the design:

- **Nothing identifies a session to a human.** `study_sessions` has no timestamps and `documents` has no title column. `TextbookUpload.title` is accepted at `ingestion.py:16` and then dropped — `save_document(doc_id, text)` never receives it. A list built today could only show `b31a063a40e9`.
- **`App.tsx` assumes linear navigation.** Its comment reads "only three steps, always visited in this order, and no page needs a shareable URL." Resuming enters at step three directly, which is exactly what that sentence rules out.

## 2. Decision: store a title and session timestamps

The alternative was deriving labels from existing data — a snippet of `documents.text` plus history length, with no migration. Rejected: two sessions on one document render nearly identically under that scheme (which is precisely the current data), and with no timestamp there is no meaningful sort order for a list whose entire purpose is "pick up where you left off."

**Decision: one Alembic revision adding three columns.**

```sql
ALTER TABLE documents       ADD COLUMN title      varchar NULL;
ALTER TABLE study_sessions  ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE study_sessions  ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
```

`documents.title` is nullable rather than defaulted: the three existing rows genuinely have no title, and inventing one would be worse than rendering a fallback. When it is `NULL`, the client renders the first 60 characters of the document's text, whitespace-collapsed and ellipsised — e.g. `"As we covered in the previous lecture, most shells are…"`. This is a client-side concern only; the API returns `title: null` and does not synthesize a label.

The two timestamps take `server_default=now()`, which backfills existing rows at migration time. `updated_at` is maintained in `PostgresStore.save_study_session`, which is already an `on_conflict_do_update` — this is one additional key in the existing `set_` dict, not a new write path.

`Store.save_document` gains an optional `title: str | None = None` parameter, and `routers/ingestion.py` starts forwarding the field it already parses. `InMemoryStore` grows a parallel `_titles` dict rather than changing the shape of `_documents`, so `get_document() -> str | None` keeps its current contract and no existing caller changes.

## 3. Decision: a dedicated summary model, not `StudySession`

A list row needs three things: the chapter's title, the session's progress, and its recency. `StudySession` carries none of them — the title lives on `documents`, the concept total on `concepts`, and `updated_at` did not exist before §2. What it does carry is `history`, a list in which every entry embeds a full `Question`, `Answer`, `EvaluationResult`, and possibly a `DiagnosisResult`.

Returning `list[StudySession]` would therefore ship the heaviest field in the model to render three lines of text, and still leave the client issuing one `getGraph(doc_id)` per document to compute a concept count the server could have joined.

**Decision: a new `StudySessionSummary`, assembled server-side.**

```python
class StudySessionSummary(BaseModel):
    id: str
    doc_id: str
    title: str | None          # None -> client falls back to a text snippet
    status: StudySessionStatus
    completed_concepts: int
    total_concepts: int
    updated_at: datetime
```

## 4. Decision: progress is computed in the router, not the store

Progress means "how far through the chapter," which is the position of `current_concept_id` in `topological_order(graph)` — the same ordering `submit_answer` uses to advance. It is not `len(history)`: a diagnosis appends history entries without advancing a concept, so the two diverge exactly when a student is struggling, which is when the number matters most.

Computing it requires loading the graph, which no SQL join can do. The natural place to put that is the store — but `topological_order` lives in `app/services/graph_builder.py`, and importing it from `app/store/` would make the storage layer depend on the services layer, inverting the direction every other module follows.

**Decision: the store returns what SQL can cheaply join; the router computes progress.** `routers/study_session.py` already imports `topological_order` (line 18) and already calls it twice (lines 42, 95), so this adds no dependency and follows the file's existing shape.

The store's method returns an internal `StudySessionSummaryRow` — every public field except `completed_concepts`, plus `current_concept_id`. The router loads the graph once per **distinct** `doc_id` into a dict, then maps rows to the public model. The cost is one HTTP request and `1 + D` store reads, where `D` is the count of distinct documents among unfinished sessions — two for the current data, not three. No LLM calls are involved, so the latency is a graph read and an in-memory topological sort.

Two internal/public model shapes rather than one partially-populated model, mirroring the `_extract_raw_graph` → `build_graph` internal-seam idiom already used in `graph_builder.py`.

Guards, both reachable today:

- `current_concept_id is None` → `completed_concepts = 0`. The `sess1` row is exactly this.
- `current_concept_id` absent from the ordered list → `0`, defensively.

## 5. API surface

```
GET /api/study-session  ->  StudySessionSummary[]
```

Added to the existing router (`prefix="/api/study-session"`) as `@router.get("")`. Filtered to `status IN ('active', 'diagnosing')` and sorted `updated_at DESC`.

**Only unfinished sessions appear.** A completed session cannot be continued, so it leaves the list on its own the moment it completes. This is what keeps the list self-cleaning and is why no delete endpoint is part of this design — the alternative (show everything, add a delete affordance) buys a history view nobody asked for and a destructive endpoint to secure.

`GET /api/study-session/{id}` needs no changes; resume reads through it.

## 6. Store seam

One new abstract method on `Store`, implemented in both backends:

```python
def list_unfinished_sessions(self) -> list[StudySessionSummaryRow]: ...
```

- `PostgresStore`: one query joining `study_sessions → documents` for the title, with a single correlated count of `concepts` by `doc_id` for `total_concepts`. `history_entries` is deliberately **not** counted — progress is the topological position of `current_concept_id` (§4), not an answer tally, so nothing consumes it.
- `InMemoryStore`: filter `_study_sessions` by status, assembling title from `_titles` and the concept count from `_graphs`.

## 7. Frontend

| File | Change |
|---|---|
| `types/index.ts` | Add `StudySessionSummary`; add `created_at`/`updated_at` to `StudySession`. Hand-mirrored, per the existing convention. |
| `api/client.ts` | Add `listStudySessions()` and `getStudySession(id)`. |
| `App.tsx` | State gains `resumeSessionId: string \| null`. Rewrite the "always visited in this order" comment, which this change makes false. |
| `pages/MenuPage.tsx` | Rename of `UploadPage`. Fetches the list on mount; renders `SessionList` above the unchanged upload form. |
| `components/SessionList.tsx` | New. Renders rows, calls `onResume(summary)`. |
| `pages/StudySessionPage.tsx` | Props become `{docId, sessionId?, onExit}`; the mount effect branches on `sessionId`. |
| `pages/GraphView.tsx` | Filters `listStudySessions()` by `doc_id` to choose between "Resume / Start fresh" and "Start session". |

**Entry screen layout:** unfinished sessions first, upload form beneath. An empty list renders nothing at all, so a first-time user sees exactly today's page.

**`GraphView` offers both actions explicitly.** When an unfinished session exists for the chapter, it shows "Resume session" and "Start fresh" side by side; otherwise a single "Start session". Silently resuming was rejected because it removes any way to restudy a chapter from scratch, and always creating new was rejected because it is the behavior that produced the duplicate sessions in the first place.

## 8. Resume must restore the pending question

The non-obvious requirement. `StudySessionPage` currently renders `getQuestions(current_concept_id)[0]`, which is correct only for a freshly started session.

For a session in `diagnosing`, that expression returns the concept's first pre-generated question — the definitional one the student already answered wrong — not the diagnostic question actually on screen when they left. Against the current `b31a063a40e9` row it would return `q1` while the pending question is `q2`.

**Rule:**

- `status === 'diagnosing'` → the pending question is `history[history.length - 1].diagnosis.targeted_question`
- otherwise → `getQuestions(current_concept_id)[0]`

Without this, resume silently drops the student on the wrong question, and the resulting answer is graded against the wrong rubric.

## 9. Rejected: adding a router

`react-router` would give real URLs (`/session/:id`), make the browser back button work, survive a refresh, and let the URL discriminate navigation states instead of the growing chain of `page === 'x' && docId &&` guards in `App.tsx`.

**Rejected for now**, on these grounds:

- Refresh is not data loss. Sessions are persisted server-side, so a refresh costs two clicks (menu → Resume), not work.
- Shareable URLs are worth close to nothing in a single-user local app with no auth.
- The state-tuple argument is directionally right but premature: at three pages and two entry points it costs exactly one additional guard.
- The frontend has no test runner at all — `package.json` defines only `dev`/`build`/`preview`, there are no test files, and CI runs `npm run build`. Converting all three pages from props to `useParams` would be a typecheck-only refactor with no behavioral safety net, landing in the same change as a new feature.

Revisit when a fourth page appears, or when auth makes URLs meaningful. The backend work in this design is identical either way, so adding a router later invalidates none of it.

## 10. Error handling

A failed list fetch renders an inline error **above** the upload form rather than replacing the page: a broken list must never block uploading a new chapter. Resuming a session that 404s — deleted, or completed since the list was loaded — surfaces the error and returns to the menu.

## 11. Testing

`tests/test_flow.py` (stub-backed, free, no API key):

- the list returns only unfinished sessions, sorted by recency
- resuming returns the same session id rather than minting a new one
- progress math, including the `current_concept_id is None` case
- the §8 rule: resuming a `diagnosing` session selects the targeted question, not `q1`

`tests/test_postgres_store.py` (real Postgres, no LLM calls): the join's title and count correctness, and that `updated_at` advances on save.

The migration is verified by running `alembic upgrade head` against the existing three-row database and confirming the backfill.

Frontend verification is `tsc -b` via `npm run build`, matching CI. There is no frontend test runner, and this design does not add one.

## 12. Out of scope

- Deleting sessions (§5 — the list is self-cleaning).
- Viewing a chapter's graph without starting or resuming a session. Reachable today only after upload or via "Back to graph"; the menu does not add a path to it.
- Any router change (§9).
- Backfilling titles for the three existing documents.
