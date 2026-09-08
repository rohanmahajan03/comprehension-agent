import { relativeTime } from './SessionList'
import type { DocumentSummary } from '../types'

interface Props {
  documents: DocumentSummary[]
  onOpen: (document: DocumentSummary) => void
}

// Every chapter with a graph, so a new session can start from one already in the DB
// without re-uploading. Deliberately independent of SessionList: a chapter with an
// unfinished session may appear in both lists, which is fine — GraphView resolves the
// correct Resume/Start-fresh state either way once opened.
export function DocumentList({ documents, onOpen }: Props) {
  if (documents.length === 0) return null

  return (
    <div className="card">
      <h2>Your chapters</h2>
      <ul className="session-list">
        {documents.map((doc) => (
          <li key={doc.id}>
            <div className="session-row">
              <button className="session-resume" onClick={() => onOpen(doc)}>
                <strong>{doc.title ?? doc.text_snippet}</strong>
                <span>
                  {doc.total_concepts} concept{doc.total_concepts === 1 ? '' : 's'} ·{' '}
                  {relativeTime(doc.created_at)}
                </span>
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
