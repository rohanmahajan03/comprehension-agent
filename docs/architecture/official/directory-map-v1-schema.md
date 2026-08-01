No DB tables — this diagram maps source directories to architectural roles.

## Connections

**Root → Routers / Pages**
Backend and frontend directories are the build contexts for their respective Docker targets.

**Root → Tests**
CI (`.github/workflows/ci.yml`) runs the pytest suite in `backend/tests/`.

**Root → Docs**
This `docs/architecture` tree is the versioned record of the diagrams themselves.

**Routers → Services**
Routers stay thin — they call into `app/services` for all business logic, currently stubbed.

**Routers → Store**
Routers read and write persisted state directly through the storage abstraction.

**Routers → Models**
Request/response bodies are typed with the Pydantic schemas in `app/models`.

**Services → Models**
Service functions return typed model instances rather than raw dicts.

**Store → Models**
The store persists and returns model instances, keeping storage decoupled from HTTP concerns.

**Tests → Routers**
The pytest suite exercises endpoints via FastAPI's `TestClient`, not by calling services directly.

**Pages → Api**
Frontend pages fetch data exclusively through the `api/` client wrapper.

**Pages → Components**
Pages compose reusable UI pieces from `components/`.

**Api / Components → Types**
Both are typed against `types/index.ts`.

**Models ⇢ Types (dashed)**
`types/index.ts` is a hand-kept mirror of `models/schemas.py` — there's no codegen, so the two must be updated together whenever schemas change.
