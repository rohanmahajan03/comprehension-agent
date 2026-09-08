import { useEffect, useState } from 'react'
import { deleteStudySession, listDocuments, listStudySessions, uploadTextbook } from '../api/client'
import { DocumentList } from '../components/DocumentList'
import { SessionList } from '../components/SessionList'
import type { DocumentSummary, StudySessionSummary } from '../types'

interface Props {
  // Called both right after a fresh upload and when opening a chapter already in the DB
  // (from the "Your chapters" list) — either way it just means "go to this doc's graph".
  onOpenDocument: (docId: string) => void
  onResume: (session: StudySessionSummary) => void
}

/**
 * The app's entry screen: resumable sessions first, then the upload form.
 *
 * Was `UploadPage`. Returning users see their unfinished work immediately; a first-time
 * user sees an empty list render nothing at all, so the page is exactly the upload form
 * it always was.
 */
export function MenuPage({ onOpenDocument, onResume }: Props) {
  const [text, setText] = useState('')
  const [title, setTitle] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sessions, setSessions] = useState<StudySessionSummary[]>([])
  const [sessionsError, setSessionsError] = useState<string | null>(null)
  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [documentsError, setDocumentsError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listStudySessions()
      .then((loaded) => {
        if (!cancelled) setSessions(loaded)
      })
      .catch((err) => {
        // Surfaced above the form rather than replacing the page: a broken list must
        // never block uploading a new chapter.
        if (!cancelled) {
          setSessionsError(
            `Couldn’t load your sessions: ${err instanceof Error ? err.message : String(err)}`
          )
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    listDocuments()
      .then((loaded) => {
        if (!cancelled) setDocuments(loaded)
      })
      .catch((err) => {
        if (!cancelled) {
          setDocumentsError(
            `Couldn’t load your chapters: ${err instanceof Error ? err.message : String(err)}`
          )
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const handleDelete = async (session: StudySessionSummary) => {
    try {
      await deleteStudySession(session.id)
      setSessions((prev) => prev.filter((s) => s.id !== session.id))
    } catch (err) {
      setSessionsError(
        `Couldn’t delete session: ${err instanceof Error ? err.message : String(err)}`
      )
    }
  }

  const submit = async () => {
    setSubmitting(true)
    setError(null)
    try {
      const { doc_id } = await uploadTextbook(text, title.trim() || undefined)
      onOpenDocument(doc_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      {sessionsError && <p className="error">{sessionsError}</p>}
      <SessionList sessions={sessions} onResume={onResume} onDelete={handleDelete} />

      {documentsError && <p className="error">{documentsError}</p>}
      <DocumentList documents={documents} onOpen={(doc) => onOpenDocument(doc.id)} />

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
