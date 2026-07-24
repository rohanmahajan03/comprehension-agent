import { useState } from 'react'
import { uploadTextbook } from '../api/client'

interface Props {
  onUploaded: (docId: string) => void
}

export function UploadPage({ onUploaded }: Props) {
  const [text, setText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    setSubmitting(true)
    setError(null)
    try {
      const { doc_id } = await uploadTextbook(text)
      onUploaded(doc_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="card">
      <h2>Upload a chapter</h2>
      <p>
        Paste chapter text below. The backend will extract concepts, build a dependency
        graph, and pre-generate questions (currently stubbed with sample data).
      </p>
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
  )
}
