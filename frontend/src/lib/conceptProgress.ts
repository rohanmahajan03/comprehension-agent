import type { DependencyGraph, HistoryEntry, Question, StudySession } from '../types'

/**
 * Whether an attempt counts as right.
 *
 * `evaluation.correct` is the evaluator's verdict and is never rewritten — the disputed
 * grade is the evidence a later reviewer needs (2026-09-18-manual-answer-override-design
 * §4). `overridden` is the student's successful dispute, resolved server-side from
 * `answer_overrides` on every load. An overridden answer advanced the session exactly as
 * a correct one would have, so everything downstream treats it as correct.
 *
 * Mirrors `HistoryEntry.effective_correct` in backend/app/models/schemas.py. Defined once
 * here so no caller re-spells the `||`.
 */
export function effectiveCorrect(entry: HistoryEntry): boolean {
  return entry.evaluation.correct || entry.overridden
}

/** What the student has shown about one concept, as the graph paints it. */
export type ConceptState = 'mastered' | 'current' | 'gap' | 'unreached'

/** Reading order for the legend: where you are, then the two outcomes, then the rest.
 *  Shared so the study screen and the graph screen cannot present it differently. */
export const LEGEND_ORDER: ConceptState[] = ['current', 'mastered', 'gap', 'unreached']

/**
 * Colour state per concept id, derived entirely from the session the page already holds.
 *
 * **Last outcome wins.** A concept's state is decided by the most recent history entry
 * that asked about it, with diagnostic and main-track answers counting identically. That
 * is what makes `gap` mean "not rectified" rather than "ever struggled": a concept
 * diagnosed as the root gap and then answered correctly on its probe is mastered from that
 * moment, and one mastered earlier but failed later goes back to being a gap. Diagnostic
 * answers attribute to the right concept for free — `diagnoser` sets a targeted question's
 * `concept_id` to the suspect's id.
 *
 * Nothing here is stored or accumulated; history is re-read on every render, so no state
 * can go stale and a reload reproduces the same colours.
 *
 * See docs/specs/2026-09-20-graph-progress-coloring-design.md §2.
 */
export function conceptStates(
  graph: DependencyGraph,
  session: StudySession,
  pendingQuestion: Question | null,
): Map<string, ConceptState> {
  // One pass over history rather than a scan per concept; later entries overwrite earlier
  // ones, which *is* the last-outcome-wins rule.
  const lastOutcome = new Map<string, boolean>()
  for (const entry of session.history) {
    lastOutcome.set(entry.question.concept_id, effectiveCorrect(entry))
  }

  const states = new Map<string, ConceptState>()
  for (const concept of graph.concepts) {
    states.set(concept.id, stateOf(concept.id))
  }
  return states

  function stateOf(id: string): ConceptState {
    // "Where am I" outranks "how did it go" — the page names the current concept in prose
    // directly above the graph, so the two should agree.
    if (id === session.current_concept_id) return 'current'

    const outcome = lastOutcome.get(id)
    if (outcome !== undefined) return outcome ? 'mastered' : 'gap'

    // Implicated but not yet answered: the probe is on screen right now. Keyed off the
    // pending question rather than the newest diagnosis record because a diagnosis can be
    // produced and then never served — `_MAX_DIAGNOSTIC_CHAIN` forces a return — and only
    // a concept actually being asked about should be painted.
    if (pendingQuestion?.concept_id === id) return 'gap'

    return 'unreached'
  }
}

/** How this session has gone on one concept, for the detail panel beside the graph. */
export interface ConceptAttempts {
  asked: number
  correct: number
}

/**
 * Attempt tally for one concept, counting probes and main-track questions alike — the
 * same population `conceptStates` reads, so the panel and the colour can never disagree.
 */
export function conceptAttempts(
  session: StudySession,
  conceptId: string,
): ConceptAttempts {
  const entries = session.history.filter((h) => h.question.concept_id === conceptId)
  return {
    asked: entries.length,
    correct: entries.filter(effectiveCorrect).length,
  }
}
