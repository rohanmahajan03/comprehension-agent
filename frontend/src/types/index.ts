// Mirrors backend/app/models/schemas.py — keep the two in sync.

export interface Question {
  id: string
  concept_id: string
  prompt: string
  expected_answer_notes: string
}

export interface Concept {
  id: string
  name: string
  summary: string
  depends_on: string[]
  // Maps each id in depends_on to the source-text quote justifying that prerequisite
  evidence: Record<string, string>
  questions: Question[]
}

export interface DependencyGraph {
  doc_id: string
  concepts: Concept[]
}

export interface Answer {
  question_id: string
  text: string
}

export interface EvaluationResult {
  correct: boolean
  explanation: string
}

export interface DiagnosisResult {
  suspected_gap_concept_id: string
  reasoning: string
  targeted_question: Question
}

export type StudySessionStatus = 'active' | 'diagnosing' | 'completed'

export interface HistoryEntry {
  question: Question
  answer: Answer
  evaluation: EvaluationResult
  diagnosis: DiagnosisResult | null
}

export interface StudySession {
  id: string
  doc_id: string
  current_concept_id: string | null
  history: HistoryEntry[]
  status: StudySessionStatus
  created_at: string
  updated_at: string
}

// Returned by the endpoints that open a session: POST /api/study-session/start and
// GET /api/study-session/{id}. A superset of StudySession.
export interface StudySessionDetail extends StudySession {
  // The question this session is waiting on, derived server-side. Non-obvious branch: a
  // `diagnosing` session reports its diagnostic question, not its concept's first one.
  // Clients render this directly rather than reconstructing it — the same helper feeds
  // AnswerResponse.next_question, so answering and resuming can't disagree.
  pending_question: Question | null
}

// One row of the "continue a session" list — GET /api/study-session.
// Deliberately not a StudySession: a row needs the chapter title, concept counts, and
// recency (none of which live on StudySession) and never renders `history` (the heaviest
// field on it).
export interface StudySessionSummary {
  id: string
  doc_id: string
  // null when the chapter was uploaded without one; render text_snippet instead.
  title: string | null
  // Always present. A short server-computed label from the document's text.
  text_snippet: string
  status: StudySessionStatus
  completed_concepts: number
  total_concepts: number
  updated_at: string
}

// Response of POST /api/study-session/{id}/answer
export interface AnswerResponse {
  evaluation: EvaluationResult
  diagnosis: DiagnosisResult | null
  next_question: Question | null
  study_session: StudySession
}
