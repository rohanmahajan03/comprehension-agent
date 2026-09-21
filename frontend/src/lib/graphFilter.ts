import { isDiagnosticQuestionId } from './questionIds'
import type { Concept, DependencyGraph } from '../types'

/**
 * Whether the student can actually be sent to this concept on the main track.
 *
 * `question_generator` is told to skip a question type rather than force one, so a thin
 * concept can come back with no questions at all — a legitimate output, and one the loop
 * already handles by walking past it (`_advance`). Diagnostic questions don't count: both
 * stores rebuild `Concept.questions` from the question index on every `get_graph()`, so a
 * concept the diagnoser probed would otherwise turn testable mid-session and reappear.
 */
export function isTestable(concept: Concept): boolean {
  return concept.questions.some((q) => !isDiagnosticQuestionId(q.id))
}

/**
 * The graph as the student should see it: untestable concepts removed, and the
 * prerequisite edges through them rewired so nothing about the structure is lost.
 *
 * Bridging is the whole difficulty. Omitting a concept does not merely hide it — edge
 * rendering resolves each prerequisite with `positions.get(depId)` and draws nothing when
 * it is missing, so dropping `B` from `A → B → C` would erase both edges and leave `C`
 * looking like a root. Each surviving concept's prerequisites are therefore resolved
 * through hidden ones to the nearest surviving ancestors.
 *
 * Deliberately a transform the caller applies rather than a flag on DependencyGraphViz:
 * `ReviewGraphPage` renders a DRAFT graph, where *no* concept has questions yet (question
 * generation is what finalize does), so a filter it could forget to switch off would blank
 * the one page whose job is editing the graph. See
 * docs/specs/2026-09-20-graph-progress-coloring-design.md §4.
 */
export function withoutUntestableConcepts(graph: DependencyGraph): DependencyGraph {
  const surviving = new Set(graph.concepts.filter(isTestable).map((c) => c.id))
  // Nothing to do — return the original object so callers can rely on referential
  // equality in the common case.
  if (surviving.size === graph.concepts.length) return graph

  const byId = new Map(graph.concepts.map((c) => [c.id, c]))

  // The nearest surviving ancestors reachable from `id`. `seen` guards against a cycle
  // the same way DependencyGraphViz's own `depthOf` does; real graphs are DAGs, since
  // build_graph drops any edge that would introduce one.
  const resolve = (id: string, seen: Set<string>): string[] => {
    if (surviving.has(id)) return [id]
    if (seen.has(id)) return []
    seen.add(id)
    const hidden = byId.get(id)
    if (!hidden) return []
    return hidden.depends_on.flatMap((dep) => resolve(dep, seen))
  }

  return {
    doc_id: graph.doc_id,
    concepts: graph.concepts
      .filter((c) => surviving.has(c.id))
      .map((concept) => {
        const depends_on = [
          ...new Set(concept.depends_on.flatMap((dep) => resolve(dep, new Set<string>()))),
        ]
        // A bridged edge has no justifying quote by construction — there was never a
        // direct edge for one to justify — so `evidence` keeps only the entries whose
        // edge survived intact rather than carrying keys nothing points at any more.
        const evidence = Object.fromEntries(
          Object.entries(concept.evidence).filter(([prereqId]) => depends_on.includes(prereqId)),
        )
        return { ...concept, depends_on, evidence }
      }),
  }
}
