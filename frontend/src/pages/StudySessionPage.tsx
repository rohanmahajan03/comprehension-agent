import { useEffect, useState } from 'react'
import { getGraph, getStudySession, startStudySession, submitAnswer } from '../api/client'
import { QuestionCard } from '../components/QuestionCard'
import type {
  AnswerResponse,
  DependencyGraph,
  Question,
  StudySession,
} from '../types'

interface Props {
  docId: string
  /** Resume this session instead of starting a new one. */
  sessionId?: string
  onExit: () => void
}

export function StudySessionPage({ docId, sessionId, onExit }: Props) {
  const [studySession, setStudySession] = useState<StudySession | null>(null)
  const [graph, setGraph] = useState<DependencyGraph | null>(null)
  const [question, setQuestion] = useState<Question | null>(null)
  const [lastResult, setLastResult] = useState<AnswerResponse | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // `cancelled` guards against setting state from a stale request if `docId`/`sessionId`
    // change (or the component unmounts) before this resolves.
    let cancelled = false
    // Resume when given a session id, otherwise start a fresh one. Without this branch
    // every visit to this page minted a new session, which is how duplicate sessions
    // accumulated on a single chapter.
    const loadSession = sessionId ? getStudySession(sessionId) : startStudySession(docId)
    // Session and graph are fetched concurrently — neither depends on the other's result.
    Promise.all([loadSession, getGraph(docId)])
      .then(([loadedStudySession, loadedGraph]) => {
        if (cancelled) return
        setStudySession(loadedStudySession)
        setGraph(loadedGraph)
        // Both endpoints report which question the session is on, so there's nothing to
        // work out here. That rule has one non-obvious branch (a diagnosing session is
        // parked on its diagnostic question, not its concept's first one) and lives
        // server-side, shared with the answer endpoint — see `_pending_question`.
        setQuestion(loadedStudySession.pending_question)
      })
      .catch((err) => setError(String(err)))
    return () => {
      cancelled = true
    }
  }, [docId, sessionId])

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
  if (!studySession) return <p>{sessionId ? 'Resuming study session…' : 'Starting study session…'}</p>

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
