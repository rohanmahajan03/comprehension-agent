import { useEffect, useState } from 'react'
import { getGraph, getQuestions, startSession, submitAnswer } from '../api/client'
import { QuestionCard } from '../components/QuestionCard'
import type {
  AnswerResponse,
  DependencyGraph,
  Question,
  Session,
} from '../types'

interface Props {
  docId: string
  onExit: () => void
}

export function SessionPage({ docId, onExit }: Props) {
  const [session, setSession] = useState<Session | null>(null)
  const [graph, setGraph] = useState<DependencyGraph | null>(null)
  const [question, setQuestion] = useState<Question | null>(null)
  const [lastResult, setLastResult] = useState<AnswerResponse | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([startSession(docId), getGraph(docId)])
      .then(async ([newSession, loadedGraph]) => {
        if (cancelled) return
        setSession(newSession)
        setGraph(loadedGraph)
        if (newSession.current_concept_id) {
          const questions = await getQuestions(newSession.current_concept_id)
          if (!cancelled) setQuestion(questions[0] ?? null)
        }
      })
      .catch((err) => setError(String(err)))
    return () => {
      cancelled = true
    }
  }, [docId])

  const conceptName = (id: string | null | undefined) =>
    graph?.concepts.find((c) => c.id === id)?.name ?? id ?? 'unknown'

  const handleAnswer = async (text: string) => {
    if (!session || !question) return
    setSubmitting(true)
    setError(null)
    try {
      const result = await submitAnswer(session.id, { question_id: question.id, text })
      setLastResult(result)
      setSession(result.session)
      setQuestion(result.next_question)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (error && !session) return <p className="error">{error}</p>
  if (!session) return <p>Starting session…</p>

  return (
    <div>
      <div className="card">
        <h2>Tutoring session</h2>
        <p>
          Status:{' '}
          <span className={`badge ${session.status === 'diagnosing' ? 'diagnosing' : 'correct'}`}>
            {session.status}
          </span>{' '}
          · Current concept: <strong>{conceptName(session.current_concept_id)}</strong>
        </p>
        <button onClick={onExit}>Back to graph</button>
      </div>

      {lastResult && (
        <div className="card">
          <p>
            <span className={`badge ${lastResult.evaluation.correct ? 'correct' : 'incorrect'}`}>
              {lastResult.evaluation.correct ? 'Correct' : 'Incorrect'}
            </span>
          </p>
          <p>{lastResult.evaluation.explanation}</p>
          {lastResult.diagnosis && (
            <>
              <h4>
                Diagnosis: checking “{conceptName(lastResult.diagnosis.suspected_gap_concept_id)}”
              </h4>
              <p>{lastResult.diagnosis.reasoning}</p>
            </>
          )}
        </div>
      )}

      {session.status === 'completed' ? (
        <div className="card">
          <h3>Session complete 🎉</h3>
          <p>You worked through every concept in this chapter.</p>
        </div>
      ) : question ? (
        <QuestionCard
          key={question.id}
          question={question}
          onSubmit={handleAnswer}
          submitting={submitting}
        />
      ) : (
        <p>No question available.</p>
      )}

      {error && session && <p className="error">{error}</p>}
    </div>
  )
}
