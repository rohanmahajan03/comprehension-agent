import { useEffect, useState } from 'react'
import { getGraph, getQuestions, getStudySession, listStudySessions } from '../api/client'
import {
  DependencyGraphViz,
  STATE_COLORS,
  STATE_LABELS,
} from '../components/DependencyGraphViz'
import { LEGEND_ORDER, conceptStates } from '../lib/conceptProgress'
import { withoutUntestableConcepts } from '../lib/graphFilter'
import { relativeTime } from '../components/SessionList'
import type {
  Concept,
  DependencyGraph,
  Question,
  StudySessionDetail,
  StudySessionSummary,
} from '../types'

interface Props {
  docId: string
  onStartStudySession: () => void
  onResumeStudySession: (session: StudySessionSummary) => void
  onExit: () => void
}

export function GraphView({ docId, onStartStudySession, onResumeStudySession, onExit }: Props) {
  const [graph, setGraph] = useState<DependencyGraph | null>(null)
  const [selected, setSelected] = useState<Concept | null>(null)
  const [questions, setQuestions] = useState<Question[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [resumable, setResumable] = useState<StudySessionSummary | null>(null)
  // The resumable session's full history, purely so this graph can carry the same
  // colouring the study screen does — the summary row has counts but no history.
  const [resumableDetail, setResumableDetail] = useState<StudySessionDetail | null>(null)

  useEffect(() => {
    getGraph(docId).then(setGraph).catch((err) => setError(String(err)))
  }, [docId])

  useEffect(() => {
    let cancelled = false
    // Reuses the menu's endpoint rather than adding a per-document one: the list is
    // already filtered to unfinished sessions, so the newest entry for this chapter is
    // exactly what "Resume" should open.
    listStudySessions()
      .then((sessions) => {
        if (!cancelled) setResumable(sessions.find((s) => s.doc_id === docId) ?? null)
      })
      // A failure here only costs the Resume button; starting a session still works, so
      // it deliberately doesn't set the page-level error.
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [docId])

  useEffect(() => {
    let cancelled = false
    setResumableDetail(null)
    if (!resumable) return
    // Same reasoning as the listStudySessions call above: a failure here costs only the
    // colouring, so it stays off the page-level error path.
    getStudySession(resumable.id)
      .then((detail) => {
        if (!cancelled) setResumableDetail(detail)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [resumable])

  useEffect(() => {
    // Clear before fetching so switching concepts shows "Loading…" instead of
    // briefly flashing the previously-selected concept's questions.
    setQuestions(null)
    if (!selected) return
    getQuestions(selected.id)
      .then(setQuestions)
      .catch((err) => setError(String(err)))
  }, [selected])

  if (error) return <p className="error">{error}</p>
  if (!graph) return <p>Loading graph…</p>

  // Same filter the study session applies. This page invites you to "click a concept to
  // preview its generated questions", and a concept question_generator produced nothing
  // for is an empty list presented as a result. Selection and the "Depends on" line read
  // from the filtered graph too, so nothing here names a concept that isn't on screen.
  const visibleGraph = withoutUntestableConcepts(graph)

  // The same colouring the study screen shows, so the graph is one thing across both
  // pages rather than a coloured version and a clickable version. Undefined when there is
  // no session to colour from, which renders exactly as it always has. Overrides need no
  // special handling here: `HistoryEntry.overridden` comes down with the session, so a
  // disputed grade reads as mastered on this screen exactly as it does on the other.
  const states = resumableDetail
    ? conceptStates(visibleGraph, resumableDetail, resumableDetail.pending_question)
    : undefined

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2>Dependency graph</h2>
          <button onClick={onExit}>Back to Home</button>
        </div>
        <p>
          Arrows point from prerequisite to dependent concept. Click a concept to preview
          its generated questions, or start a tutoring session.
        </p>
        <DependencyGraphViz
          graph={visibleGraph}
          states={states}
          selectedId={selected?.id}
          onSelect={setSelected}
        />
        {states && (
          <ul className="graph-legend">
            {LEGEND_ORDER.map((state) => (
              <li key={state}>
                <span
                  className="graph-legend-swatch"
                  style={{
                    background: STATE_COLORS[state].fill,
                    borderColor: STATE_COLORS[state].stroke,
                  }}
                />
                {STATE_LABELS[state]}
              </li>
            ))}
          </ul>
        )}
        {/* Both actions are offered explicitly when there's something to resume. Silently
            resuming would remove any way to restudy a chapter from scratch; always
            starting fresh is what produced duplicate sessions in the first place. */}
        {resumable ? (
          <p>
            <button onClick={() => onResumeStudySession(resumable)}>Resume session</button>{' '}
            <button onClick={onStartStudySession}>Start fresh</button>
            <br />
            <small>
              unfinished · {resumable.completed_concepts} of {resumable.total_concepts} concepts ·{' '}
              {relativeTime(resumable.updated_at)}
            </small>
          </p>
        ) : (
          <p>
            <button onClick={onStartStudySession}>Start tutoring session</button>
          </p>
        )}
      </div>
      {selected && (
        <div className="card">
          <h3>{selected.name}</h3>
          <p>{selected.summary}</p>
          {selected.depends_on.length > 0 && (
            <p>
              <em>
                Depends on:{' '}
                {selected.depends_on
                  .map((id) => visibleGraph.concepts.find((c) => c.id === id)?.name ?? id)
                  .join(', ')}
              </em>
            </p>
          )}
          <h4>Generated questions</h4>
          {questions === null ? (
            <p>Loading questions…</p>
          ) : (
            <ul>
              {questions.map((q) => (
                <li key={q.id}>{q.prompt}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
