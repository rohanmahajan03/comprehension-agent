import { useEffect, useState } from 'react'
import { getGraph, getQuestions, listStudySessions } from '../api/client'
import { DependencyGraphViz } from '../components/DependencyGraphViz'
import { relativeTime } from '../components/SessionList'
import type { Concept, DependencyGraph, Question, StudySessionSummary } from '../types'

interface Props {
  docId: string
  onStartStudySession: () => void
  onResumeStudySession: (session: StudySessionSummary) => void
}

export function GraphView({ docId, onStartStudySession, onResumeStudySession }: Props) {
  const [graph, setGraph] = useState<DependencyGraph | null>(null)
  const [selected, setSelected] = useState<Concept | null>(null)
  const [questions, setQuestions] = useState<Question[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [resumable, setResumable] = useState<StudySessionSummary | null>(null)

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

  return (
    <div>
      <div className="card">
        <h2>Dependency graph</h2>
        <p>
          Arrows point from prerequisite to dependent concept. Click a concept to preview
          its generated questions, or start a tutoring session.
        </p>
        <DependencyGraphViz graph={graph} selectedId={selected?.id} onSelect={setSelected} />
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
                  .map((id) => graph.concepts.find((c) => c.id === id)?.name ?? id)
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
