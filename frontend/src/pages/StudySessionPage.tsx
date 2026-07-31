import { useEffect, useState } from 'react'
import { getGraph, getQuestions, startStudySession, submitAnswer } from '../api/client'
import { QuestionCard } from '../components/QuestionCard'
import type {
  AnswerResponse,
  DependencyGraph,
  Question,
  StudySession,
} from '../types'

interface Props {
  docId: string
  onExit: () => void
}

export function StudySessionPage({ docId, onExit }: Props) {
  const [studySession, setStudySession] = useState<StudySession | null>(null)
  const [graph, setGraph] = useState<DependencyGraph | null>(null)
  const [question, setQuestion] = useState<Question | null>(null)
  const [lastResult, setLastResult] = useState<AnswerResponse | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // `cancelled` guards against setting state from a stale request if `docId`
    // changes (or the component unmounts) before this resolves.
    let cancelled = false
    // Start the session and fetch the graph concurrently — neither depends on
    // the other's result, so there's no reason to wait for one before starting
    // the other.
    Promise.all([startStudySession(docId), getGraph(docId)])
      .then(async ([newStudySession, loadedGraph]) => {
        if (cancelled) return
        setStudySession(newStudySession)
        setGraph(loadedGraph)
        if (newStudySession.current_concept_id) {
          const questions = await getQuestions(newStudySession.current_concept_id)
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
    if (!studySession || !question) return
    setSubmitting(true)
    setError(null)
    try {
      const result = await submitAnswer(studySession.id, { question_id: question.id, text })
      setLastResult(result)
      setStudySession(result.study_session)
      setQuestion(result.next_question)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (error && !studySession) return <p className="error">{error}</p>
  if (!studySession) return <p>Starting study session…</p>

  return (
    <div>
      <div className="card">
        <h2>Tutoring session</h2>
        <p>
          Status:{' '}
          {/* No dedicated "active" style — active reuses the "correct" (positive/green)
              badge since both mean "on track"; only "diagnosing" needs its own look. */}
          <span className={`badge ${studySession.status === 'diagnosing' ? 'diagnosing' : 'correct'}`}>
            {studySession.status}
          </span>{' '}
          · Current concept: <strong>{conceptName(studySession.current_concept_id)}</strong>
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

      {studySession.status === 'completed' ? (
        <div className="card">
          <h3>Study session complete 🎉</h3>
          <p>You worked through every concept in this chapter.</p>
        </div>
      ) : question ? (
        // `key={question.id}` forces a fresh QuestionCard (and thus a cleared
        // answer textarea) whenever the question changes, instead of manually
        // resetting its internal state.
        <QuestionCard
          key={question.id}
          question={question}
          onSubmit={handleAnswer}
          submitting={submitting}
        />
      ) : (
        <p>No question available.</p>
      )}

      {error && studySession && <p className="error">{error}</p>}
    </div>
  )
}
