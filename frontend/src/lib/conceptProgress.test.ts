import { describe, expect, it } from 'vitest'
import { conceptAttempts, conceptStates, effectiveCorrect } from './conceptProgress'
import type {
  Concept,
  DependencyGraph,
  HistoryEntry,
  Question,
  StudySession,
} from '../types'

function question(conceptId: string, suffix: string): Question {
  return {
    id: `${conceptId}:${suffix}`,
    concept_id: conceptId,
    prompt: 'p',
    expected_answer_notes: 'n',
    required_points: [],
  }
}

function concept(id: string): Concept {
  return {
    id,
    name: id,
    summary: 's',
    source_quotes: [],
    depends_on: [],
    evidence: {},
    questions: [question(id, 'q1')],
  }
}

function entry(
  conceptId: string,
  suffix: string,
  correct: boolean,
  overridden = false,
): HistoryEntry {
  return {
    question: question(conceptId, suffix),
    answer: { question_id: `${conceptId}:${suffix}`, text: 'a' },
    evaluation: { correct, explanation: 'e' },
    diagnosis: null,
    overridden,
  }
}

function session(history: HistoryEntry[], currentConceptId: string | null): StudySession {
  return {
    id: 's',
    doc_id: 'd',
    current_concept_id: currentConceptId,
    history,
    status: 'active',
    created_at: '2026-09-20T00:00:00Z',
    updated_at: '2026-09-20T00:00:00Z',
  }
}

const graph: DependencyGraph = {
  doc_id: 'd',
  concepts: ['d:a', 'd:b', 'd:c'].map(concept),
}

const states = (
  history: HistoryEntry[],
  current: string | null,
  pending: Question | null = null,
) => conceptStates(graph, session(history, current), pending)

describe('conceptStates', () => {
  it('marks a concept answered correctly on the main track as mastered', () => {
    expect(states([entry('d:a', 'q1', true)], 'd:b').get('d:a')).toBe('mastered')
  })

  it('marks an untouched concept as unreached', () => {
    expect(states([entry('d:a', 'q1', true)], 'd:b').get('d:c')).toBe('unreached')
  })

  it('marks a wrong answer as a gap', () => {
    expect(states([entry('d:a', 'q1', false)], 'd:b').get('d:a')).toBe('gap')
  })

  it('clears the gap once the probe on it is answered correctly', () => {
    // The refinement this feature exists for: `gap` must mean "not rectified", not "ever
    // struggled". A diagnostic question carries the suspect's own concept_id, so the
    // correct probe answer lands on d:a and supersedes the failure.
    const history = [
      entry('d:b', 'q1', false), // failed the dependent
      entry('d:a', 'diagnostic1', true), // rectified the prerequisite it was traced to
    ]
    expect(states(history, 'd:b').get('d:a')).toBe('mastered')
  })

  it('returns a mastered concept to gap when it is later failed', () => {
    const history = [entry('d:a', 'q1', true), entry('d:a', 'q2', false)]
    expect(states(history, 'd:b').get('d:a')).toBe('gap')
  })

  it('leaves a concept abandoned by the attempt cap as a gap', () => {
    // Three wrong answers, the cap trips, the loop reveals the answer and advances. The
    // student never got it right, so advancing past it is not evidence of anything — this
    // is where the graph and the topological progress counter deliberately disagree.
    const history = [
      entry('d:a', 'q1', false),
      entry('d:a', 'q1', false),
      entry('d:a', 'q1', false),
    ]
    expect(states(history, 'd:b').get('d:a')).toBe('gap')
  })

  it('marks the concept the pending question targets as a gap before it is answered', () => {
    // The diagnosis has been returned but its probe is unanswered, so there is no history
    // entry for d:a yet. Without this it would be the one node with no marking at all.
    const pending = question('d:a', 'diagnostic1')
    expect(states([entry('d:b', 'q1', false)], 'd:b', pending).get('d:a')).toBe('gap')
  })

  it('lets current win over both mastered and gap', () => {
    const mastered = states([entry('d:a', 'q1', true)], 'd:a')
    const failed = states([entry('d:a', 'q1', false)], 'd:a')
    expect(mastered.get('d:a')).toBe('current')
    expect(failed.get('d:a')).toBe('current')
  })

  it('treats an overridden answer as mastered despite the false grade beside it', () => {
    // The evaluator's verdict is never rewritten, so `overridden` is the only thing that
    // says the session advanced as though the answer were right. It arrives on the entry
    // from the server, so unlike the page state it replaced this survives a reload.
    const history = [entry('d:a', 'q1', false, true)]
    expect(states(history, 'd:b').get('d:a')).toBe('mastered')
  })

  it('lets a later genuine failure override an earlier overridden pass', () => {
    // Last outcome still wins; `overridden` changes what an outcome *is*, not the rule.
    const history = [entry('d:a', 'q1', false, true), entry('d:a', 'q2', false)]
    expect(states(history, 'd:b').get('d:a')).toBe('gap')
  })

  it('covers every concept in the graph', () => {
    expect([...states([], null).keys()]).toEqual(['d:a', 'd:b', 'd:c'])
  })
})

describe('effectiveCorrect', () => {
  it('is the evaluator verdict or the student\'s successful dispute', () => {
    expect(effectiveCorrect(entry('d:a', 'q1', true))).toBe(true)
    expect(effectiveCorrect(entry('d:a', 'q1', false))).toBe(false)
    expect(effectiveCorrect(entry('d:a', 'q1', false, true))).toBe(true)
  })
})

describe('conceptAttempts', () => {
  it('counts probes and main-track questions alike', () => {
    const history = [
      entry('d:a', 'q1', false),
      entry('d:a', 'diagnostic1', true),
      entry('d:b', 'q1', true),
    ]
    expect(conceptAttempts(session(history, 'd:b'), 'd:a')).toEqual({ asked: 2, correct: 1 })
  })

  it('counts an overridden answer as correct', () => {
    const history = [entry('d:a', 'q1', false, true)]
    expect(conceptAttempts(session(history, 'd:b'), 'd:a')).toEqual({ asked: 1, correct: 1 })
  })

  it('reports zeroes for an untouched concept', () => {
    expect(conceptAttempts(session([], null), 'd:c')).toEqual({ asked: 0, correct: 0 })
  })
})
