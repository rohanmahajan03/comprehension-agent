// Mirrors backend/app/models/schemas.py — keep the two in sync.

export interface Question {
  id: string
  concept_id: string
  prompt: string
  expected_answer_notes: string
  // The minimum an answer must express to be marked correct. Empty for questions written
  // before the field existed and for diagnostic questions.
  required_points: string[]
}

export interface Concept {
  id: string
  name: string
  summary: string
  // Verbatim chapter passages about this concept itself, beyond its summary. The
  // counterpart to `evidence`, which only ever justifies an edge. Empty on every concept
  // the extractor produced; filled during review from POST .../evidence proposals.
  source_quotes: string[]
  depends_on: string[]
  // Maps each id in depends_on to the source-text quote justifying that prerequisite
  evidence: Record<string, string>
  questions: Question[]
}

// Response of POST /api/graph/{doc_id}/concepts/{concept_id}/evidence — what a targeted
// re-scan of the chapter turned up for one concept. A proposal: nothing is stored until
// the reviewer accepts it with a PATCH. `found: false` is an ordinary outcome, not an
// error — the chapter may assume a concept rather than teach it.
export interface EvidenceProposal {
  found: boolean
  // A chapter-grounded summary offered as a replacement; empty when found is false.
  summary: string
  // Verbatim chapter passages, each already checked against the source text.
  quotes: string[]
  // How many returned quotes were discarded as not verbatim. Lets the UI tell "the chapter
  // doesn't cover this" apart from "the model paraphrased everything it returned".
  dropped: number
}

export interface DependencyGraph {
  doc_id: string
  concepts: Concept[]
}

// Where a chapter sits in pipeline 1. 'draft' means the upload asked to review the graph:
// it's extracted but not yet approved, so it has no questions and no study session can
// start against it.
export type DocumentStatus = 'draft' | 'finalized'

// Response of POST /api/textbook and POST /api/textbook/{id}/finalize. `status` is what the
// client routes on after an upload — 'draft' means the review screen. Taken from the
// response rather than from the request's own `review` flag, so the server stays the one
// authority on which pipeline actually ran.
export interface UploadTextbookResponse {
  doc_id: string
  status: DocumentStatus
}

// One row of the "your chapters" list — GET /api/textbook. Unlike StudySessionSummary,
// no split between an internal and public shape: total_concepts is a plain count.
// Drafts never appear here (the server filters them), so there's no status field to check.
export interface DocumentSummary {
  id: string
  // null when the chapter was uploaded without one; render text_snippet instead.
  title: string | null
  // Always present. A short server-computed label from the document's text.
  text_snippet: string
  total_concepts: number
  created_at: string
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
  /** The evaluator's own verdict, never rewritten — what it said is the disputed artifact
   *  when a student overrides it. */
  evaluation: EvaluationResult
  diagnosis: DiagnosisResult | null
  /** Whether the student successfully disputed that verdict. Derived server-side from
   *  `answer_overrides` on every load, so it survives reload and is visible to every
   *  reader. The effective outcome is `evaluation.correct || overridden` — see
   *  `lib/conceptProgress.ts`, which is the one place that combines them. */
  overridden: boolean
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
  // The abandoned question's model answer, set only when an attempt/diagnostic cap tripped
  // and the loop moved on without the student getting it right. Response-only — nothing
  // stores it, so reloading the session loses the banner (the history entry recording the
  // failed attempt is what persists).
  revealed_answer: string | null
}

// Body of POST /api/study-session/{id}/override. The student's claim that the evaluator
// misgraded their last answer; the response is a StudySessionDetail carrying the advanced
// session. `note` is optional — requiring prose behind the button would suppress the
// disagreements the feature exists to collect.
export interface AnswerOverrideRequest {
  question_id: string
  note: string | null
}
