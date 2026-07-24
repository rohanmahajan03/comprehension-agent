import { useState } from 'react'
import { GraphView } from './pages/GraphView'
import { SessionPage } from './pages/SessionPage'
import { UploadPage } from './pages/UploadPage'

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
        <GraphView docId={docId} onStartSession={() => setPage('session')} />
      )}
      {page === 'session' && docId && (
        <SessionPage docId={docId} onExit={() => setPage('graph')} />
      )}
    </div>
  )
}
