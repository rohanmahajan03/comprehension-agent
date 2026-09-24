import { describe, expect, it } from 'vitest'
import { isTestable, withoutUntestableConcepts } from './graphFilter'
import { isDiagnosticQuestionId } from './questionIds'
import type { Concept, DependencyGraph, Question } from '../types'

function question(conceptId: string, suffix: string): Question {
  return {
    id: `${conceptId}:${suffix}`,
    concept_id: conceptId,
    prompt: 'p',
    expected_answer_notes: 'n',
    required_points: [],
  }
}

/** `questions: 'q1'` makes a concept testable; `null` leaves it with none. */
function concept(
  id: string,
  dependsOn: string[] = [],
  suffix: string | null = 'q1',
): Concept {
  return {
    id,
    name: id,
    summary: 's',
    source_quotes: [],
    depends_on: dependsOn,
    evidence: Object.fromEntries(dependsOn.map((d) => [d, `because of ${d}`])),
    questions: suffix ? [question(id, suffix)] : [],
  }
}

const graphOf = (...concepts: Concept[]): DependencyGraph => ({ doc_id: 'd', concepts })

describe('isDiagnosticQuestionId', () => {
  it('recognises a minted probe id', () => {
    expect(isDiagnosticQuestionId('d:log-segment:diagnostic1')).toBe(true)
    expect(isDiagnosticQuestionId('d:log-segment:diagnostic12')).toBe(true)
  })

  it('does not mistake a pipeline-1 question for a probe', () => {
    expect(isDiagnosticQuestionId('d:log-segment:q1')).toBe(false)
  })

  it('does not fire on a concept whose own slug starts with the word', () => {
    // The case a substring test on ':diagnostic' gets wrong.
    expect(isDiagnosticQuestionId('d:diagnostic-tools:q1')).toBe(false)
    expect(isDiagnosticQuestionId('d:diagnostic-tools:diagnostic1')).toBe(true)
  })
})

describe('isTestable', () => {
  it('is false with no questions and true with a pipeline-1 one', () => {
    expect(isTestable(concept('d:thin', [], null))).toBe(false)
    expect(isTestable(concept('d:a'))).toBe(true)
  })

  it('is false for a concept holding only a probe the diagnoser minted', () => {
    // Both stores rebuild Concept.questions from the question index on every get_graph(),
    // so without this the node would reappear mid-session the moment it was probed.
    expect(isTestable(concept('d:probed', [], 'diagnostic1'))).toBe(false)
  })
})

describe('withoutUntestableConcepts', () => {
  it('returns the same object when every concept is testable', () => {
    const graph = graphOf(concept('d:a'), concept('d:b', ['d:a']))
    expect(withoutUntestableConcepts(graph)).toBe(graph)
  })

  it('drops a question-less concept', () => {
    const graph = graphOf(concept('d:a'), concept('d:thin', [], null))
    expect(withoutUntestableConcepts(graph).concepts.map((c) => c.id)).toEqual(['d:a'])
  })

  it('bridges an edge through a dropped concept', () => {
    // A -> B -> C with B hidden must leave C depending on A, not looking like a root.
    const graph = graphOf(
      concept('d:a'),
      concept('d:b', ['d:a'], null),
      concept('d:c', ['d:b']),
    )
    const out = withoutUntestableConcepts(graph)

    expect(out.concepts.map((c) => c.id)).toEqual(['d:a', 'd:c'])
    expect(out.concepts.find((c) => c.id === 'd:c')?.depends_on).toEqual(['d:a'])
  })

  it('bridges through two consecutive dropped concepts', () => {
    const graph = graphOf(
      concept('d:a'),
      concept('d:b', ['d:a'], null),
      concept('d:c', ['d:b'], null),
      concept('d:e', ['d:c']),
    )
    expect(
      withoutUntestableConcepts(graph).concepts.find((c) => c.id === 'd:e')?.depends_on,
    ).toEqual(['d:a'])
  })

  it('dedupes when two hidden paths reach the same ancestor', () => {
    const graph = graphOf(
      concept('d:a'),
      concept('d:h1', ['d:a'], null),
      concept('d:h2', ['d:a'], null),
      concept('d:c', ['d:h1', 'd:h2']),
    )
    expect(
      withoutUntestableConcepts(graph).concepts.find((c) => c.id === 'd:c')?.depends_on,
    ).toEqual(['d:a'])
  })

  it('keeps evidence for surviving edges and drops it for bridged ones', () => {
    // A bridged edge never had a justifying quote — there was no direct edge for one to
    // justify — so carrying a key nothing points at would be a lie about provenance.
    const graph = graphOf(
      concept('d:a'),
      concept('d:b', ['d:a'], null),
      concept('d:c', ['d:a', 'd:b']),
    )
    const c = withoutUntestableConcepts(graph).concepts.find((x) => x.id === 'd:c')

    expect(c?.depends_on).toEqual(['d:a'])
    expect(c?.evidence).toEqual({ 'd:a': 'because of d:a' })
  })

  it('returns an empty graph when nothing is testable', () => {
    // The draft shape. This is why ReviewGraphPage must not call this, rather than
    // something for the filter to special-case.
    const graph = graphOf(concept('d:a', [], null), concept('d:b', ['d:a'], null))
    expect(withoutUntestableConcepts(graph).concepts).toEqual([])
  })
})
