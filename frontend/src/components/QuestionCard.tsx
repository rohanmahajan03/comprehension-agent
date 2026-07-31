import { useState } from 'react'
import type { Question } from '../types'

interface Props {
  question: Question
  onSubmit: (text: string) => void | Promise<void>
  submitting?: boolean
}

export function QuestionCard({ question, onSubmit, submitting }: Props) {
  const [text, setText] = useState('')

  const submit = async () => {
    await onSubmit(text)
    // Belt-and-suspenders reset: the parent normally remounts this component
    // (via a changing `key`) once the next question arrives, but this keeps
    // the field clean even if it doesn't.
    setText('')
  }

  return (
    <div className="card">
      <p>
        <strong>{question.prompt}</strong>
      </p>
      <textarea
        rows={4}
        placeholder="Type your answer…"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <p>
        <button onClick={submit} disabled={submitting || !text.trim()}>
          {submitting ? 'Evaluating…' : 'Submit answer'}
        </button>
      </p>
    </div>
  )
}
