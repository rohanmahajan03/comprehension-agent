import { useCallback, useEffect, useState } from 'react'
import {
  addConcept,
  addPrereq,
  deleteConcept,
  deletePrereq,
  editConcept,
  finalizeGraph,
  findEvidence,
  getGraph,
} from '../api/client'
import { DependencyGraphViz } from '../components/DependencyGraphViz'
import type { Concept, DependencyGraph, EvidenceProposal } from '../types'

interface Props {
  docId: string
  onFinalized: () => void
}

const SLUG_PATTERN = /^[a-z0-9_]+$/

/**
 * What a chapter re-scan for one concept is currently showing.
 *
 * Kept in component state rather than derived from the concept, because "we looked and the
 * chapter has nothing" and "nobody has looked yet" are different things a reviewer needs
 * told apart, and only one of them is recorded server-side (an empty `source_quotes` means
 * both). It is deliberately transient: it belongs to this review sitting, not to the
 * chapter.
 */
type EvidenceState =
  | { phase: 'scanning' }
  | { phase: 'error'; message: string }
  | { phase: 'done'; proposal: EvidenceProposal; keep: boolean[]; useSummary: boolean }

/**
 * The sentence out of a failed request, without the envelope around it.
 *
 * `request()` throws "<status> <statusText>: <raw body>", which every other page renders
 * as-is — reasonable where an error means something broke. Here the most common failure is
 * a rule working exactly as intended (a prerequisite that would close a cycle), so the
 * reviewer gets the explanation rather than `422 Unprocessable Content: {"detail":…}`.
 */
function failureMessage(err: unknown): string {
  const message = err instanceof Error ? err.message : String(err)
  const body = message.match(/\{.*\}$/)
  if (body) {
    try {
      const { detail } = JSON.parse(body[0])
      if (typeof detail === 'string') return detail
    } catch {
      // Not a JSON body after all — fall through and show what we have.
    }
  }
  return message
}

/**
 * The review screen for a draft chapter: the graph as extracted, with the affordances to
 * fix it, and the button that approves it.
 *
 * Only reachable when an upload comes back `draft`, which happens only when the uploader
 * ticked "review the concept graph first". Deliberately not a mode inside GraphView: that
 * page is a reader's view of a finished chapter, and its whole point — starting a tutoring
 * session — is exactly what a draft can't do yet.
 */
export function ReviewGraphPage({ docId, onFinalized }: Props) {
  const [graph, setGraph] = useState<DependencyGraph | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draftName, setDraftName] = useState('')
  const [draftSummary, setDraftSummary] = useState('')
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [newSlug, setNewSlug] = useState('')
  const [newName, setNewName] = useState('')
  const [newSummary, setNewSummary] = useState('')
  const [finalizing, setFinalizing] = useState(false)
  const [evidence, setEvidence] = useState<Record<string, EvidenceState>>({})

  const refresh = useCallback(() => getGraph(docId).then(setGraph), [docId])

  useEffect(() => {
    refresh().catch((err) => setError(failureMessage(err)))
  }, [refresh])

  // Every edit re-reads the whole graph instead of patching state locally. Deleting a
  // concept also strips it from every dependent's prerequisites server-side, so local
  // patching would mean reimplementing that cascade in the client — the kind of duplicated
  // rule that drifts. One extra request per edit, on a page where edits are deliberate.
  // Reports whether the action went through, so a caller with its own UI to tear down (the
  // evidence panel) can keep it up when the write was rejected — a 422 on a quote that
  // isn't in the chapter has to leave the reviewer something to fix.
  const run = async (action: () => Promise<unknown>): Promise<boolean> => {
    setError(null)
    try {
      await action()
      await refresh()
      return true
    } catch (err) {
      setError(failureMessage(err))
      return false
    }
  }

  const setEvidenceState = (conceptId: string, state: EvidenceState | null) =>
    setEvidence((prev) => {
      const next = { ...prev }
      if (state) next[conceptId] = state
      else delete next[conceptId]
      return next
    })

  /**
   * Ask the chapter what it says about one concept.
   *
   * Runs outside `run()` on purpose: it writes nothing, so there is nothing to refresh, and
   * a failure here is about one row rather than about the page. It also has to be able to
   * fail visibly-but-harmlessly — the concept is already saved by the time this runs, which
   * is exactly why the scan is a separate request from the add.
   */
  const scanForEvidence = async (conceptId: string) => {
    setEvidenceState(conceptId, { phase: 'scanning' })
    try {
      const proposal = await findEvidence(docId, conceptId)
      setEvidenceState(conceptId, {
        phase: 'done',
        proposal,
        // Everything ticked: the reviewer's job here is to reject what doesn't belong, not
        // to re-approve passage by passage what the chapter plainly says.
        keep: proposal.quotes.map(() => true),
        // The summary is the one thing they already wrote themselves, so replacing it is
        // opt-in rather than opt-out.
        useSummary: false,
      })
    } catch (err) {
      setEvidenceState(conceptId, { phase: 'error', message: failureMessage(err) })
    }
  }

  const acceptEvidence = async (conceptId: string, state: EvidenceState) => {
    if (state.phase !== 'done') return
    const quotes = state.proposal.quotes.filter((_, i) => state.keep[i])
    const saved = await run(() =>
      editConcept(docId, conceptId, {
        source_quotes: quotes,
        ...(state.useSummary && state.proposal.summary
          ? { summary: state.proposal.summary }
          : {}),
      })
    )
    if (saved) setEvidenceState(conceptId, null)
  }

  const startEditing = (concept: Concept) => {
    setEditingId(concept.id)
    setDraftName(concept.name)
    setDraftSummary(concept.summary)
  }

  const finalize = async () => {
    setFinalizing(true)
    setError(null)
    try {
      await finalizeGraph(docId)
      onFinalized()
    } catch (err) {
      setError(failureMessage(err))
    } finally {
      setFinalizing(false)
    }
  }

  if (!graph) return error ? <p className="error">{error}</p> : <p>Loading graph…</p>

  const nameOf = (id: string) => graph.concepts.find((c) => c.id === id)?.name ?? id

  const renderEvidence = (concept: Concept) => {
    const state = evidence[concept.id]
    if (!state) return null

    if (state.phase === 'scanning') {
      return <p className="evidence-panel evidence-quiet">Searching the chapter…</p>
    }

    if (state.phase === 'error') {
      return (
        <div className="evidence-panel evidence-empty">
          <span>Couldn’t search the chapter: {state.message}</span>
          <div className="evidence-actions">
            <button className="session-cancel" onClick={() => setEvidenceState(concept.id, null)}>
              Dismiss
            </button>
            <button onClick={() => scanForEvidence(concept.id)}>Try again</button>
          </div>
        </div>
      )
    }

    const { proposal } = state
    if (!proposal.found) {
      return (
        <div className="evidence-panel evidence-empty">
          <strong>Could not find evidence for this concept in the chapter.</strong>
          <span>
            Questions for it will be written from your summary alone, which supports a
            definition question and not much more. If the chapter does cover this idea, try
            rewording the name or summary to match the words it uses. If it assumes the idea
            rather than teaching it, leaving this as-is is the right answer.
          </span>
          {proposal.dropped > 0 && (
            <small>
              {proposal.dropped} passage{proposal.dropped === 1 ? '' : 's'} came back that
              {proposal.dropped === 1 ? " wasn't" : " weren't"} actually in the chapter, and
              {proposal.dropped === 1 ? ' was' : ' were'} discarded rather than stored as a
              source quote.
            </small>
          )}
          <div className="evidence-actions">
            <button className="session-cancel" onClick={() => setEvidenceState(concept.id, null)}>
              Dismiss
            </button>
            <button onClick={() => scanForEvidence(concept.id)}>Search again</button>
          </div>
        </div>
      )
    }

    const keptCount = state.keep.filter(Boolean).length
    return (
      <div className="evidence-panel evidence-found">
        <strong>
          Found {proposal.quotes.length} passage{proposal.quotes.length === 1 ? '' : 's'} in
          the chapter. Keep the ones that are really about this concept.
        </strong>
        <ul className="evidence-quotes">
          {proposal.quotes.map((quote, i) => (
            <li key={quote}>
              <label>
                <input
                  type="checkbox"
                  checked={state.keep[i]}
                  onChange={(e) =>
                    setEvidenceState(concept.id, {
                      ...state,
                      keep: state.keep.map((k, j) => (j === i ? e.target.checked : k)),
                    })
                  }
                />
                <q>{quote}</q>
              </label>
            </li>
          ))}
        </ul>
        {proposal.summary && (
          <label className="evidence-summary">
            <input
              type="checkbox"
              checked={state.useSummary}
              onChange={(e) =>
                setEvidenceState(concept.id, { ...state, useSummary: e.target.checked })
              }
            />
            <span>
              Also replace the summary with: <em>{proposal.summary}</em>
            </span>
          </label>
        )}
        {proposal.dropped > 0 && (
          <small>
            {proposal.dropped} further passage{proposal.dropped === 1 ? '' : 's'} came back
            that {proposal.dropped === 1 ? "wasn't" : "weren't"} actually in the chapter, and
            {proposal.dropped === 1 ? ' was' : ' were'} discarded.
          </small>
        )}
        <div className="evidence-actions">
          <button className="session-cancel" onClick={() => setEvidenceState(concept.id, null)}>
            Discard
          </button>
          <button onClick={() => acceptEvidence(concept.id, state)}>
            {keptCount === 0
              ? 'Keep none'
              : `Save ${keptCount} passage${keptCount === 1 ? '' : 's'}`}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="card">
        <h2>
          Review the graph <span className="badge diagnosing">draft</span>
        </h2>
        <p>
          These concepts were pulled out of the chapter automatically. Fix anything wrong
          before approving: questions are written once per concept from exactly what this
          graph says, and the chapter is locked afterwards.
        </p>
        <DependencyGraphViz graph={graph} selectedId={editingId} onSelect={startEditing} />
        <p>
          <button onClick={finalize} disabled={finalizing || graph.concepts.length === 0}>
            {finalizing ? 'Writing questions…' : 'Approve & write questions'}
          </button>
          {graph.concepts.length > 0 && (
            <>
              <br />
              <small>
                One question-writing call per concept ({graph.concepts.length}), so this
                takes a moment.
              </small>
            </>
          )}
        </p>
        {error && <p className="error">{error}</p>}
      </div>

      <div className="card">
        <h3>Concepts</h3>
        <ul className="session-list">
          {graph.concepts.map((concept) => {
            if (confirmingId === concept.id) {
              return (
                <li key={concept.id}>
                  <div className="session-row session-row-confirming">
                    <div className="session-confirm-text">
                      <strong>{concept.name}</strong>
                      <span>
                        Delete this concept? Anything that depends on it loses that
                        prerequisite.
                      </span>
                    </div>
                    <div className="session-confirm-actions">
                      <button className="session-cancel" onClick={() => setConfirmingId(null)}>
                        Cancel
                      </button>
                      <button
                        className="session-delete-confirm"
                        onClick={() => {
                          setConfirmingId(null)
                          run(() => deleteConcept(docId, concept.id))
                        }}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                </li>
              )
            }

            if (editingId === concept.id) {
              return (
                <li key={concept.id}>
                  <div className="concept-row concept-row-editing">
                    <div className="concept-main">
                      <input
                        type="text"
                        value={draftName}
                        placeholder="Concept name"
                        onChange={(e) => setDraftName(e.target.value)}
                      />
                      <textarea
                        rows={3}
                        value={draftSummary}
                        placeholder="Summary"
                        onChange={(e) => setDraftSummary(e.target.value)}
                      />
                      <small>
                        The summary is this concept's own evidence, alongside any chapter
                        passages kept for it — together they are what every question about
                        it gets written from.
                      </small>
                    </div>
                    <div className="concept-actions">
                      <button className="session-cancel" onClick={() => setEditingId(null)}>
                        Cancel
                      </button>
                      <button
                        disabled={!draftName.trim() || !draftSummary.trim()}
                        onClick={() => {
                          setEditingId(null)
                          run(() =>
                            editConcept(docId, concept.id, {
                              name: draftName.trim(),
                              summary: draftSummary.trim(),
                            })
                          )
                        }}
                      >
                        Save
                      </button>
                    </div>
                  </div>
                </li>
              )
            }

            const available = graph.concepts.filter(
              (c) => c.id !== concept.id && !concept.depends_on.includes(c.id)
            )
            return (
              <li key={concept.id}>
                <div className="concept-row">
                  <div className="concept-main">
                    <strong>{concept.name}</strong>
                    <span>{concept.summary}</span>
                    {concept.source_quotes.length > 0 && (
                      <details className="evidence-stored">
                        <summary>
                          {concept.source_quotes.length} chapter passage
                          {concept.source_quotes.length === 1 ? '' : 's'} kept as evidence
                        </summary>
                        <ul className="evidence-quotes">
                          {concept.source_quotes.map((quote) => (
                            <li key={quote}>
                              <q>{quote}</q>
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                    {renderEvidence(concept)}
                    <div className="concept-prereqs">
                      <span className="concept-prereqs-label">Depends on:</span>
                      {concept.depends_on.length === 0 && <em>nothing</em>}
                      {concept.depends_on.map((id) => (
                        <span className="prereq-chip" key={id}>
                          {nameOf(id)}
                          <button
                            className="prereq-remove"
                            aria-label={`Remove prerequisite ${nameOf(id)}`}
                            onClick={() => run(() => deletePrereq(docId, concept.id, id))}
                          >
                            ×
                          </button>
                        </span>
                      ))}
                      {available.length > 0 && (
                        // Resets to the placeholder on every render (value=""), so the
                        // same prerequisite can be picked again after an add fails.
                        <select
                          value=""
                          onChange={(e) => {
                            if (e.target.value) {
                              run(() => addPrereq(docId, concept.id, e.target.value))
                            }
                          }}
                        >
                          <option value="">+ add…</option>
                          {available.map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.name}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>
                  </div>
                  <div className="concept-actions">
                    {/* Re-runnable on demand, not just after an add: editing a concept's
                        name or summary changes what the scan is looking for. */}
                    <button
                      className="session-cancel"
                      disabled={evidence[concept.id]?.phase === 'scanning'}
                      onClick={() => scanForEvidence(concept.id)}
                    >
                      Find evidence
                    </button>
                    <button className="session-cancel" onClick={() => startEditing(concept)}>
                      Edit
                    </button>
                    <button
                      className="session-delete"
                      onClick={() => setConfirmingId(concept.id)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      </div>

      <div className="card">
        <h3>Add a concept</h3>
        <p>
          For an idea the chapter teaches that the extractor missed or folded into another
          concept.
        </p>
        <input
          type="text"
          placeholder="Slug, e.g. hash_index"
          value={newSlug}
          onChange={(e) => setNewSlug(e.target.value)}
        />
        <input
          type="text"
          placeholder="Name, e.g. Hash index"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
        <textarea
          rows={3}
          placeholder="Summary — what the chapter says this concept is"
          value={newSummary}
          onChange={(e) => setNewSummary(e.target.value)}
        />
        <p>
          <button
            disabled={
              !SLUG_PATTERN.test(newSlug) || !newName.trim() || !newSummary.trim()
            }
            onClick={() =>
              run(async () => {
                const created = await addConcept(docId, {
                  slug: newSlug,
                  name: newName.trim(),
                  summary: newSummary.trim(),
                })
                setNewSlug('')
                setNewName('')
                setNewSummary('')
                // Fired, not awaited: the concept is saved, so the slow part shouldn't
                // hold up the form clearing, and a scan that fails or finds nothing must
                // not read as a failed add. Automatic so there's no way to end up with a
                // thin concept by forgetting a second click.
                void scanForEvidence(created.id)
              })
            }
          >
            Add concept
          </button>
          <br />
          <small>
            Slug: lowercase letters, digits and underscores. The chapter is searched for
            supporting passages automatically once the concept is added.
          </small>
        </p>
      </div>
    </div>
  )
}
