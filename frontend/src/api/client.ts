import type {
  Answer,
  AnswerResponse,
  DependencyGraph,
  Question,
  StudySessionDetail,
  StudySessionSummary,
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

export function uploadTextbook(text: string, title?: string): Promise<{ doc_id: string }> {
  return request('/api/textbook', {
    method: 'POST',
    body: JSON.stringify({ text, title }),
  })
}

export function getGraph(docId: string): Promise<DependencyGraph> {
  return request(`/api/graph/${encodeURIComponent(docId)}`)
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
