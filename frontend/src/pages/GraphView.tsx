import { useEffect, useState } from 'react'
import { getGraph, getQuestions } from '../api/client'
import { DependencyGraphViz } from '../components/DependencyGraphViz'
import type { Concept, DependencyGraph, Question } from '../types'

interface Props {
  docId: string
  onStartSession: () => void
}

export function GraphView({ docId, onStartSession }: Props) {
  const [graph, setGraph] = useState<DependencyGraph | null>(null)
  const [selected, setSelected] = useState<Concept | null>(null)
  const [questions, setQuestions] = useState<Question[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getGraph(docId).then(setGraph).catch((err) => setError(String(err)))
  }, [docId])

  useEffect(() => {
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
        <p>
          <button onClick={onStartSession}>Start tutoring session</button>
        </p>
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
