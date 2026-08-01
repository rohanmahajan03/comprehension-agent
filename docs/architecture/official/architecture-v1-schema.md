No persisted DB tables — `InMemoryStore` holds Python objects in process memory, not rows.

## Connections

**Browser → ReactApp**
Loads the SPA; routes between Upload, Graph, and StudySession pages.

**ReactApp → ApiClient**
All pages call through the shared `api/client.ts` wrapper rather than issuing raw fetches.

**ApiClient → Routers**
Typed HTTP calls to `/api/*`. Request/response shapes come from the hand-mirrored types in `frontend/src/types/index.ts`.

**Routers → GraphBuilder**
`POST /api/textbook` triggers synchronous graph construction from the uploaded chapter (currently stubbed — ignores the text).

**GraphBuilder → QuestionGen**
For each concept in the built graph, generates its question set before returning.

**GraphBuilder / QuestionGen → Store**
Persists the concept graph and generated questions so later session requests can read them.

**Routers → Evaluator**
`POST /api/study-session/{id}/answer` hands the submitted answer to the evaluator to determine correct/incorrect.

**Evaluator → Diagnoser**
On an incorrect answer, the diagnoser finds the prerequisite concept most likely at fault and generates a targeted question.

**Evaluator → Store**
On a correct answer, advances `current_concept_id` in topological order and persists the updated study session.

**Diagnoser → Store**
Appends the generated diagnostic question to its concept's question set so a later answer to it resolves correctly.

**Store → Routers → ApiClient**
Read path for graph/questions/study-session state, returned as JSON to the frontend.

**GraphBuilder / QuestionGen / Evaluator / Diagnoser ⇢ LLM (dashed)**
Not implemented yet — each service is a stub with a `# TODO:` marking where real LLM calls will replace the current fixed/alternating logic.
