import type {
  Answer,
  AnswerResponse,
  DependencyGraph,
  Question,
  StudySession,
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

export function startStudySession(docId: string): Promise<StudySession> {
  return request('/api/study-session/start', {
    method: 'POST',
    body: JSON.stringify({ doc_id: docId }),
  })
}

export function submitAnswer(studySessionId: string, answer: Answer): Promise<AnswerResponse> {
  return request(`/api/study-session/${encodeURIComponent(studySessionId)}/answer`, {
    method: 'POST',
    body: JSON.stringify(answer),
  })
}
