import { useState } from 'react'
import { GraphView } from './pages/GraphView'
import { MenuPage } from './pages/MenuPage'
import { StudySessionPage } from './pages/StudySessionPage'
import type { StudySessionSummary } from './types'

// Plain state instead of a router. The pages are no longer strictly linear — resuming a
// session jumps from the menu straight to 'session', skipping 'graph' — but with three
// pages and two entry points the whole navigation graph still fits in two state fields.
//
// What a router would buy: working browser-back, refresh-survival, and URLs as the
// discriminator instead of the `&& docId` guards below. Deliberately deferred (see
// docs/specs/2026-08-29-resume-study-session-design.md §9): refresh costs two clicks
// rather than data, since sessions are persisted server-side, and the frontend has no
// test runner to catch a regression from converting every page to route params. Revisit
// when a fourth page appears or auth makes URLs meaningful.
type Page = 'menu' | 'graph' | 'session'

export default function App() {
  const [page, setPage] = useState<Page>('menu')
  const [docId, setDocId] = useState<string | null>(null)
  // Set = resume that session; null = start a new one for `docId`.
  const [resumeSessionId, setResumeSessionId] = useState<string | null>(null)

  const resume = (session: StudySessionSummary) => {
    setDocId(session.doc_id)
    setResumeSessionId(session.id)
    setPage('session')
  }

  return (
    <div className="container">
      <h1>
        <button className="home-link" onClick={() => setPage('menu')}>
          Adaptive Concept Tutor
        </button>
      </h1>
      {page === 'menu' && (
        <MenuPage
          onUploaded={(id) => {
            setDocId(id)
            setResumeSessionId(null)
            setPage('graph')
          }}
          onResume={resume}
        />
      )}
      {page === 'graph' && docId && (
        <GraphView
          docId={docId}
          onStartStudySession={() => {
            // Clear any previously-resumed id, or StudySessionPage would reopen that
            // session instead of starting the fresh one this button asks for.
            setResumeSessionId(null)
            setPage('session')
          }}
          onResumeStudySession={resume}
        />
      )}
      {page === 'session' && docId && (
        <StudySessionPage
          docId={docId}
          sessionId={resumeSessionId ?? undefined}
          onExit={() => setPage('graph')}
        />
      )}
    </div>
  )
}
