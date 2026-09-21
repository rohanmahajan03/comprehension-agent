// Mirrors backend/app/models/question_ids.py — keep the two in sync.

/**
 * Matches the trailing `:diagnostic{n}` segment the diagnoser mints, and nothing else.
 *
 * Anchored, with the digits required, for the same reason the Python side is: a bare
 * `id.includes(':diagnostic')` would misread `doc:diagnostic-tools:q1` — a pipeline-1
 * question on a concept called "diagnostic tools" — as a probe.
 */
const DIAGNOSTIC_ID_PATTERN = /:diagnostic[0-9]+$/

/** Whether this question was minted mid-session by the diagnoser rather than written by
 * pipeline 1 at ingestion. */
export function isDiagnosticQuestionId(questionId: string): boolean {
  return DIAGNOSTIC_ID_PATTERN.test(questionId)
}
