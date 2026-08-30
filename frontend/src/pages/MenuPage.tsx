import { useEffect, useState } from 'react'
import { listStudySessions, uploadTextbook } from '../api/client'
import { SessionList } from '../components/SessionList'
import type { StudySessionSummary } from '../types'

interface Props {
  onUploaded: (docId: string) => void
  onResume: (session: StudySessionSummary) => void
}

/**
 * The app's entry screen: resumable sessions first, then the upload form.
 *
 * Was `UploadPage`. Returning users see their unfinished work immediately; a first-time
 * user sees an empty list render nothing at all, so the page is exactly the upload form
 * it always was.
 */
export function MenuPage({ onUploaded, onResume }: Props) {
  const [text, setText] = useState('')
  const [title, setTitle] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sessions, setSessions] = useState<StudySessionSummary[]>([])
  const [sessionsError, setSessionsError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listStudySessions()
      .then((loaded) => {
        if (!cancelled) setSessions(loaded)
      })
      .catch((err) => {
        // Surfaced above the form rather than replacing the page: a broken list must
        // never block uploading a new chapter.
        if (!cancelled) setSessionsError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  const submit = async () => {
    setSubmitting(true)
    setError(null)
    try {
      const { doc_id } = await uploadTextbook(text, title.trim() || undefined)
      onUploaded(doc_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      {sessionsError && <p className="error">Couldn’t load your sessions: {sessionsError}</p>}
      <SessionList sessions={sessions} onResume={onResume} />

      <div className="card">
        <h2>Upload a chapter</h2>
        <p>
          Paste chapter text below. The backend will extract concepts, build a dependency
          graph, and pre-generate questions.
        </p>
        <input
          type="text"
          placeholder="Chapter title (optional)"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <textarea
          rows={12}
          placeholder="Paste chapter text here…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <p>
          <button onClick={submit} disabled={submitting || !text.trim()}>
            {submitting ? 'Processing…' : 'Build dependency graph'}
          </button>
        </p>
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  )
}
