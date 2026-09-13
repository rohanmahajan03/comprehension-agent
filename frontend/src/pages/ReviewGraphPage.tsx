import { useCallback, useEffect, useState } from 'react'
import {
  addConcept,
  addPrereq,
  deleteConcept,
  deletePrereq,
  editConcept,
  finalizeGraph,
  getGraph,
} from '../api/client'
import { DependencyGraphViz } from '../components/DependencyGraphViz'
import type { Concept, DependencyGraph } from '../types'

interface Props {
  docId: string
  onFinalized: () => void
}

const SLUG_PATTERN = /^[a-z0-9_]+$/

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

  const refresh = useCallback(() => getGraph(docId).then(setGraph), [docId])

  useEffect(() => {
    refresh().catch((err) => setError(failureMessage(err)))
  }, [refresh])

  // Every edit re-reads the whole graph instead of patching state locally. Deleting a
  // concept also strips it from every dependent's prerequisites server-side, so local
  // patching would mean reimplementing that cascade in the client — the kind of duplicated
  // rule that drifts. One extra request per edit, on a page where edits are deliberate.
  const run = async (action: () => Promise<unknown>) => {
    setError(null)
    try {
      await action()
      await refresh()
    } catch (err) {
      setError(failureMessage(err))
    }
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
                        The summary is the evidence every question about this concept gets
                        written from.
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
                await addConcept(docId, {
                  slug: newSlug,
                  name: newName.trim(),
                  summary: newSummary.trim(),
                })
                setNewSlug('')
                setNewName('')
                setNewSummary('')
              })
            }
          >
            Add concept
          </button>
          <br />
          <small>Slug: lowercase letters, digits and underscores.</small>
        </p>
      </div>
    </div>
  )
}
