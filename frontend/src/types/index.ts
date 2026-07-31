// Mirrors backend/app/models/schemas.py — keep the two in sync.

export interface Concept {
  id: string
  name: string
  summary: string
  depends_on: string[]
}

export interface DependencyGraph {
  doc_id: string
  concepts: Concept[]
}

export interface Question {
  id: string
  concept_id: string
  prompt: string
  expected_answer_notes: string
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
}

// Response of POST /api/study-session/{id}/answer
export interface AnswerResponse {
  evaluation: EvaluationResult
  diagnosis: DiagnosisResult | null
  next_question: Question | null
  study_session: StudySession
}
