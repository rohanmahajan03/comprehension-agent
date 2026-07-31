import { useState } from 'react'
import { GraphView } from './pages/GraphView'
import { StudySessionPage } from './pages/StudySessionPage'
import { UploadPage } from './pages/UploadPage'

// Plain state instead of a router: only three steps, always visited in this
// order, and no page needs a shareable URL — a router would add ceremony
// without buying anything yet.
type Page = 'upload' | 'graph' | 'session'

export default function App() {
  const [page, setPage] = useState<Page>('upload')
  const [docId, setDocId] = useState<string | null>(null)

  return (
    <div className="container">
      <h1>Adaptive Concept Tutor</h1>
      {page === 'upload' && (
        <UploadPage
          onUploaded={(id) => {
            setDocId(id)
            setPage('graph')
          }}
        />
      )}
      {page === 'graph' && docId && (
        <GraphView docId={docId} onStartStudySession={() => setPage('session')} />
      )}
      {page === 'session' && docId && (
        <StudySessionPage docId={docId} onExit={() => setPage('graph')} />
      )}
    </div>
  )
}
