# Delete study session — design

**Status:** implemented (§5's confirmation UI was revised after initial implementation — see the note there)
**Scope:** adds the ability to delete a study session, end to end. Touches `backend/app/store/memory_store.py`, `backend/app/store/postgres_store.py`, `backend/app/routers/study_session.py`, `frontend/src/api/client.ts`, `frontend/src/components/SessionList.tsx`, `frontend/src/pages/MenuPage.tsx`, `frontend/src/index.css`, plus new/extended tests in `backend/tests/`. No Alembic migration.

## 1. Context

There is no delete functionality anywhere in this app today for any entity reachable from the client. `Store.delete_document` exists, but it's an internal rollback used only by `routers/ingestion.py` when a chapter upload fails mid-pipeline — no HTTP endpoint exposes it, and nothing in the frontend calls it. There is no `delete_study_session` on the `Store` ABC at all.

This design adds a user-facing way to delete a study session from the "Continue a session" list on the menu screen: a `DELETE /api/study-session/{id}` endpoint, the store-layer method behind it in both backends, and the frontend UI to trigger it.

Decisions already settled before this doc: deleting a session cascades to its history entries (nothing is soft-deleted or orphaned); the trigger lives only in the session list on the menu screen (not inside an open session); and deletion is allowed at any session status (active, diagnosing, or completed). The confirmation step was originally planned as a native `window.confirm()` (chosen for zero new code, since no modal/dialog pattern existed in the app yet) — shipped that way first, then replaced with a custom inline confirmation styled to match the app once the MVP was validated. See §5 for the as-built version.

## 2. Backend — store layer

Add to the `Store` ABC (`backend/app/store/memory_store.py`), grouped with the other study-session methods, idempotent on an unknown id — the same contract `delete_document` already documents:

```python
@abstractmethod
def delete_study_session(self, study_session_id: str) -> None:
    """Remove a session and its history. Idempotent — deleting an unknown id is not an error."""
    ...
```

**`InMemoryStore`:**

```python
def delete_study_session(self, study_session_id: str) -> None:
    self._study_sessions.pop(study_session_id, None)
```

Nothing else references a session by id in `InMemoryStore` (questions are keyed by concept id, not session id), so this is the whole implementation — no hand-rolled cascade needed the way `delete_document` needs one.

**`PostgresStore`:**

```python
def delete_study_session(self, study_session_id: str) -> None:
    """History entries reach study_sessions through ON DELETE CASCADE
    (app/db/models.py), so the database removes them. Deleting an unknown id is a no-op.
    """
    with session_scope() as session:
        session.execute(delete(StudySessionRow).where(StudySessionRow.id == study_session_id))
```

`HistoryEntryRow.study_session_id` already declares `ondelete="CASCADE"` (`app/db/models.py`, confirmed also present in the initial Alembic revision, `d5202eeffbcc_initial_schema.py`). **No new migration is needed** — this is purely additive to the existing schema.

## 3. Backend — router

New endpoint on `backend/app/routers/study_session.py`, following the file's existing lookup/404 pattern (`store.get_study_session(id)` → `HTTPException(404, f"No study session '{study_session_id}'")` if `None`):

```python
@router.delete("/{study_session_id}", status_code=204)
def delete_study_session(study_session_id: str) -> None:
    store = get_store()
    if store.get_study_session(study_session_id) is None:
        raise HTTPException(status_code=404, detail=f"No study session '{study_session_id}'")
    store.delete_study_session(study_session_id)
```

204 with no body on success; 404 if the id doesn't exist. This is the first DELETE endpoint in the app — no existing convention to reconcile with.

## 4. Frontend — API client

`frontend/src/api/client.ts`'s shared `request<T>` helper always calls `response.json()` on success, which would throw on a 204's empty body — every existing caller assumes a JSON response. `request` needs a small guard for this, since `deleteStudySession` is the first caller that doesn't get one back:

```typescript
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    const body = await response.text()
    throw new Error(`${response.status} ${response.statusText}: ${body}`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function deleteStudySession(studySessionId: string): Promise<void> {
  return request(`/api/study-session/${encodeURIComponent(studySessionId)}`, {
    method: 'DELETE',
  })
}
```

## 5. Frontend — UI

**`SessionList.tsx`:** each row is currently one `<button className="session-row" onClick={() => onResume(session)}>` wrapping the title/badge/progress content. A delete button can't nest inside it (invalid HTML — button-in-button), so the row is restructured: the outer element becomes a `<div className="session-row">` holding two siblings — a `<button className="session-resume">` with the existing content and click behavior, and a new small `<button className="session-delete">`.

Initial shipped version confirmed via `window.confirm()` before calling `onDelete`. **As-built (revised after MVP review):** `window.confirm()` is replaced by an inline confirmation that swaps a row's own content in place, tracked by one `confirmingId: string | null` state value in `SessionList` (at most one row confirms at a time — clicking another row's delete button just moves `confirmingId`, no explicit cancel-the-previous-one logic needed):

```tsx
interface Props {
  sessions: StudySessionSummary[]
  onResume: (session: StudySessionSummary) => void
  onDelete: (session: StudySessionSummary) => void
}

const [confirmingId, setConfirmingId] = useState<string | null>(null)
...
{sessions.map((session) => {
  const confirming = confirmingId === session.id
  return (
    <li key={session.id}>
      <div className={confirming ? 'session-row session-row-confirming' : 'session-row'}>
        {confirming ? (
          <>
            <div className="session-confirm-text">
              <strong>{session.title ?? session.text_snippet}</strong>
              <span>Delete this session? This can't be undone.</span>
            </div>
            <div className="session-confirm-actions">
              <button className="session-cancel" onClick={() => setConfirmingId(null)}>
                Cancel
              </button>
              <button
                className="session-delete-confirm"
                onClick={() => {
                  setConfirmingId(null)
                  onDelete(session)
                }}
              >
                Delete
              </button>
            </div>
          </>
        ) : (
          <>
            <button className="session-resume" onClick={() => onResume(session)}>
              <strong>{session.title ?? session.text_snippet}</strong>
              <span>...</span>
            </button>
            <button
              className="session-delete"
              aria-label="Delete session"
              onClick={() => setConfirmingId(session.id)}
            >
              Delete
            </button>
          </>
        )}
      </div>
    </li>
  )
})}
```

`index.css`: `.session-row` is a flex-row container (background/border/padding live on its children, not itself); `.session-resume` carries the old flex-column/text-align/reset styling (the code comment there about opting a `<button>` out of global button styling moves with it) and grows to fill the row (`flex: 1`); `.session-delete` is a small secondary-styled button aligned to the row's end. The confirming state adds `.session-row-confirming` (red-tinted background/border, reusing the existing `.error`/`.badge.incorrect` red family so it reads as consistent rather than bolted on), `.session-confirm-text`/`.session-confirm-actions` for the two-column layout, `.session-cancel` (muted outline button), and `.session-delete-confirm` (solid red — the actual destructive action, visually distinct from the small red-on-transparent trigger button). A `max-width: 480px` breakpoint stacks `.session-row-confirming` into a column — caught during visual iteration (see below): at phone width, the title and the two buttons competed for the same row and the title wrapped into an unreadable multi-line column.

Validated by iterating against an isolated stub-backed instance (a throwaway backend on a separate port, seeded with fixture sessions, torn down afterward) rather than the developer's real `docker compose` dev stack — that stack turned out to already be running with real multi-day-old session history during the first delete-feature smoke test, which is what surfaced the need for an isolated instance for any further UI iteration on this feature.

**`MenuPage.tsx`:** owns the delete handler alongside the existing `sessions`/`sessionsError` state, and passes it down:

```tsx
const handleDelete = async (session: StudySessionSummary) => {
  try {
    await deleteStudySession(session.id)
    setSessions((prev) => prev.filter((s) => s.id !== session.id))
  } catch (err) {
    setSessionsError(
      `Couldn't delete session: ${err instanceof Error ? err.message : String(err)}`
    )
  }
}
...
<SessionList sessions={sessions} onResume={onResume} onDelete={handleDelete} />
```

This is a pessimistic update — the session is removed from local state only after the DELETE succeeds, matching the app's existing no-toast, no-undo minimalism. On failure, the existing `sessionsError`/`.error` display (already rendered above the list) shows the failure; the list is left unchanged.

`GraphView.tsx`'s separate `listStudySessions()` fetch (used to offer "Resume session" for the current document) is left untouched — it re-fetches fresh on every mount, so it can't show a session deleted elsewhere as stale for more than the current page view. Out of scope here.

## 6. Testing

**`backend/tests/test_memory_store.py`** — new `TestDeleteStudySession` class alongside `TestDeleteDocument`, following its structure:
- deleting a session removes it (`get_study_session` returns `None` afterward)
- deleting one session doesn't affect another
- deleting an unknown id is a no-op (doesn't raise, doesn't touch existing sessions)

**`backend/tests/test_postgres_store.py`** — new test mirroring `test_delete_document_cascades_to_everything_derived_from_it`: create a session with at least one `HistoryEntry`, call `delete_study_session`, then assert both `get_study_session(...) is None` *and* a raw `select count(*) from history_entries where study_session_id = ...` is 0 — proving the FK cascade fired in the database, not just that the Python-level store forgot the object. Also assert a neighbouring session is untouched.

**`backend/tests/test_flow.py`** — HTTP-level: start a session, `client.delete(f"/api/study-session/{id}")` → 204, then `client.get(f"/api/study-session/{id}")` → 404. Separately, `client.delete` on an id that was never created → 404.

No test changes needed in `tests/conftest.py` — this feature touches no LLM-calling service, so none of the stub fixtures are relevant.

## 7. What's implemented vs. pending

Everything is implemented: `Store.delete_study_session` (ABC, `InMemoryStore`, `PostgresStore`, §2), the `DELETE /api/study-session/{id}` router endpoint (§3), the `request<T>` 204 guard and `deleteStudySession` (§4), `SessionList.tsx`/`MenuPage.tsx` wiring (§5, including the post-MVP inline-confirm revision), `index.css` (§5), and all tests in §6.

Nothing pending.
