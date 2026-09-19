import { useEffect, useRef, useState } from 'react'
import {
  getGraph,
  getStudySession,
  overrideAnswer,
  startStudySession,
  submitAnswer,
} from '../api/client'
import { QuestionCard } from '../components/QuestionCard'
import type {
  AnswerResponse,
  DependencyGraph,
  Question,
  StudySession,
  StudySessionDetail,
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
  // Both transient, like the evidence notice in ReviewGraphPage: an override is a
  // one-shot action on the result currently on screen, with nothing to restore on reload.
  const [overriding, setOverriding] = useState(false)
  const [overrideNote, setOverrideNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  // Caches the in-flight `startStudySession` call per docId so React StrictMode's dev-mode
  // double-invoke of the mount effect below reuses the one POST instead of firing a second.
  // Without this, every fresh start minted two sessions server-side — the second is the one
  // this page ends up tracking, while the first lingers forever as an untouched duplicate at
  // 0 progress in the "continue a session" list (that's the bug behind the ghost 0-of-N row).
  const startedSessionRef = useRef<{ docId: string; promise: Promise<StudySessionDetail> } | null>(
    null,
  )

  useEffect(() => {
    // `cancelled` guards against setting state from a stale request if `docId`/`sessionId`
    // change (or the component unmounts) before this resolves.
    let cancelled = false
    // Resume when given a session id, otherwise start a fresh one (reusing a cached
    // in-flight start for the same docId — see `startedSessionRef` above). Without the
    // sessionId branch, every visit to this page minted a new session, which is how
    // duplicate sessions accumulated on a single chapter.
    let loadSession: Promise<StudySessionDetail>
    if (sessionId) {
      loadSession = getStudySession(sessionId)
    } else if (startedSessionRef.current?.docId === docId) {
      loadSession = startedSessionRef.current.promise
    } else {
      loadSession = startStudySession(docId)
      startedSessionRef.current = { docId, promise: loadSession }
    }
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
      // A fresh result is a fresh grade to agree or disagree with, so the panel never
      // carries a half-typed note from the previous question into this one.
      setOverriding(false)
      setOverrideNote('')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  const handleOverride = async () => {
    // The answer just graded is the last history entry — derived from `lastResult` rather
    // than tracked in a second state, so the id and the result it belongs to cannot drift.
    // It is also the only entry the server will accept (it 409s on any older one).
    const history = lastResult?.study_session.history ?? []
    const answered = history[history.length - 1]
    if (!studySession || !answered) return
    setSubmitting(true)
    setError(null)
    try {
      const detail = await overrideAnswer(studySession.id, {
        question_id: answered.question.id,
        note: overrideNote.trim() || null,
      })
      // Clearing `lastResult` retires the card the button lives in: the grade has been
      // disputed and the session has moved, so leaving the old verdict on screen would
      // invite a second click at a question that is no longer current.
      setLastResult(null)
      setOverriding(false)
      setOverrideNote('')
      setStudySession(detail)
      setQuestion(detail.pending_question)
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
          {/* Only set when a cap tripped, so its presence *is* the message that the loop
              gave up on that question — the heading says so before the answer lands. */}
          {lastResult.revealed_answer && (
            <>
              <h4>Moving on — the answer we were looking for</h4>
              <p>{lastResult.revealed_answer}</p>
            </>
          )}
          {lastResult.diagnosis && (
            <>
              <h4>
                Diagnosis: checking “{conceptName(lastResult.diagnosis.suspected_gap_concept_id)}”
              </h4>
              <p>{lastResult.diagnosis.reasoning}</p>
            </>
          )}
          {/* The grader is a model and gets this wrong often enough to need a channel, so
              every incorrect result offers one. Opens in place rather than in a dialog,
              matching the delete confirmation in SessionList. */}
          {!lastResult.evaluation.correct &&
            (overriding ? (
              <div className="override-panel">
                <label htmlFor="override-note">
                  Why do you think your answer was right? (optional)
                </label>
                <textarea
                  id="override-note"
                  rows={3}
                  value={overrideNote}
                  onChange={(e) => setOverrideNote(e.target.value)}
                  placeholder="e.g. the rubric wanted an example, but the question asked for a definition"
                />
                <div className="override-actions">
                  <button
                    className="session-cancel"
                    onClick={() => setOverriding(false)}
                    disabled={submitting}
                  >
                    Cancel
                  </button>
                  <button onClick={handleOverride} disabled={submitting}>
                    {submitting ? 'Recording…' : 'Record and move on'}
                  </button>
                </div>
              </div>
            ) : (
              <button className="override-open" onClick={() => setOverriding(true)}>
                I think this was correct
              </button>
            ))}
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
