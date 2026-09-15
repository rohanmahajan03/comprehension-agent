import type {
  Answer,
  AnswerResponse,
  Concept,
  DependencyGraph,
  DocumentSummary,
  EvidenceProposal,
  Question,
  StudySessionDetail,
  StudySessionSummary,
  UploadTextbookResponse,
} from '../types'

// Same-origin by default; vite's dev server proxies /api to the backend.
const BASE_URL = ''

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

// `review` stops the pipeline after graph extraction so the concept graph can be edited;
// the chapter comes back 'draft' and has no questions until finalizeGraph() runs.
export function uploadTextbook(
  text: string,
  title?: string,
  review = false
): Promise<UploadTextbookResponse> {
  return request('/api/textbook', {
    method: 'POST',
    body: JSON.stringify({ text, title, review }),
  })
}

export function getGraph(docId: string): Promise<DependencyGraph> {
  return request(`/api/graph/${encodeURIComponent(docId)}`)
}

// Chapters that already have a graph, most recently created first — lets a new session
// start from one without re-uploading and re-paying for extraction.
export function listDocuments(): Promise<DocumentSummary[]> {
  return request('/api/textbook')
}

export function getQuestions(conceptId: string): Promise<Question[]> {
  return request(`/api/questions/${encodeURIComponent(conceptId)}`)
}

export function startStudySession(docId: string): Promise<StudySessionDetail> {
  return request('/api/study-session/start', {
    method: 'POST',
    body: JSON.stringify({ doc_id: docId }),
  })
}

// Unfinished sessions only, most recently updated first. Completed ones are filtered out
// server-side — they can't be continued, so the list empties itself as work finishes.
export function listStudySessions(): Promise<StudySessionSummary[]> {
  return request('/api/study-session')
}

export function getStudySession(studySessionId: string): Promise<StudySessionDetail> {
  return request(`/api/study-session/${encodeURIComponent(studySessionId)}`)
}

export function submitAnswer(studySessionId: string, answer: Answer): Promise<AnswerResponse> {
  return request(`/api/study-session/${encodeURIComponent(studySessionId)}/answer`, {
    method: 'POST',
    body: JSON.stringify(answer),
  })
}

export function deleteStudySession(studySessionId: string): Promise<void> {
  return request(`/api/study-session/${encodeURIComponent(studySessionId)}`, {
    method: 'DELETE',
  })
}

// --- Graph review (draft chapters only — these 409 against a chapter uploaded without
// `review`, and against one whose review has already been approved) ---

function conceptPath(docId: string, conceptId: string): string {
  return `/api/graph/${encodeURIComponent(docId)}/concepts/${encodeURIComponent(conceptId)}`
}

export function addConcept(
  docId: string,
  concept: { slug: string; name: string; summary: string }
): Promise<Concept> {
  return request(`/api/graph/${encodeURIComponent(docId)}/concepts`, {
    method: 'POST',
    body: JSON.stringify(concept),
  })
}

/**
 * Omitted fields are left alone; `source_quotes` replaces the whole list, which is how
 * accepting only part of an evidence proposal is expressed. Every quote sent must appear
 * verbatim in the chapter or the request is rejected with 422 — the field's contract is
 * that it holds source text, so it's checked at the write rather than trusted.
 */
export function editConcept(
  docId: string,
  conceptId: string,
  changes: { name?: string; summary?: string; source_quotes?: string[] }
): Promise<Concept> {
  return request(conceptPath(docId, conceptId), {
    method: 'PATCH',
    body: JSON.stringify(changes),
  })
}

/**
 * Re-scan the chapter for passages explaining one concept (one LLM call, so it is slow
 * relative to every other call on this page).
 *
 * Proposes only — nothing is written until the reviewer accepts it via editConcept. A
 * `found: false` result is a real answer, not a failure: the chapter may assume the concept
 * rather than teach it, which is a legitimate reason to have added it by hand.
 */
export function findEvidence(docId: string, conceptId: string): Promise<EvidenceProposal> {
  return request(`${conceptPath(docId, conceptId)}/evidence`, { method: 'POST' })
}

export function deleteConcept(docId: string, conceptId: string): Promise<void> {
  return request(conceptPath(docId, conceptId), { method: 'DELETE' })
}

/** Make `conceptId` depend on `prereqId`. Rejected with 422 if it would form a cycle. */
export function addPrereq(docId: string, conceptId: string, prereqId: string): Promise<void> {
  return request(`${conceptPath(docId, conceptId)}/prereqs`, {
    method: 'POST',
    body: JSON.stringify({ prereq_id: prereqId }),
  })
}

export function deletePrereq(docId: string, conceptId: string, prereqId: string): Promise<void> {
  return request(`${conceptPath(docId, conceptId)}/prereqs/${encodeURIComponent(prereqId)}`, {
    method: 'DELETE',
  })
}

// Approves the reviewed graph: generates a question set per concept (one LLM call each,
// so this is the slow one) and opens the chapter to study sessions.
export function finalizeGraph(docId: string): Promise<UploadTextbookResponse> {
  return request(`/api/textbook/${encodeURIComponent(docId)}/finalize`, { method: 'POST' })
}
