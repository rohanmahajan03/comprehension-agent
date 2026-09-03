import { useState } from 'react'
import type { StudySessionSummary } from '../types'

interface Props {
  sessions: StudySessionSummary[]
  onResume: (session: StudySessionSummary) => void
  onDelete: (session: StudySessionSummary) => void
}

/** Human-readable gap since `iso`, coarsened to the largest useful unit. */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000))
  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.round(hours / 24)
  return days === 1 ? 'yesterday' : `${days} days ago`
}

export function SessionList({ sessions, onResume, onDelete }: Props) {
  // At most one row confirms a delete at a time — picking a new row's delete button
  // implicitly cancels whichever row was previously confirming.
  const [confirmingId, setConfirmingId] = useState<string | null>(null)

  // Nothing to continue: render nothing at all, so a first-time user sees only the
  // upload form rather than an empty-state card explaining a feature they haven't used.
  if (sessions.length === 0) return null

  return (
    <div className="card">
      <h2>Continue a session</h2>
      <ul className="session-list">
        {sessions.map((session) => {
          const confirming = confirmingId === session.id
          return (
            <li key={session.id}>
              <div className={confirming ? 'session-row session-row-confirming' : 'session-row'}>
                {confirming ? (
                  <>
                    <div className="session-confirm-text">
                      <strong>{session.title ?? session.text_snippet}</strong>
                      <span>Delete this session? This can’t be undone.</span>
                    </div>
                    <div className="session-confirm-actions">
                      <button className="session-cancel" onClick={() => setConfirmingId(null)}>
                        Cancel
                      </button>
                      <button
                        className="session-delete-confirm"
                        onClick={() => {
                          setConfirmingId(null)
                          onDelete(session)
                        }}
                      >
                        Delete
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <button className="session-resume" onClick={() => onResume(session)}>
                      {/* Untitled chapters fall back to a server-computed text snippet, so two
                          of them stay distinguishable in the list. */}
                      <strong>{session.title ?? session.text_snippet}</strong>
                      <span>
                        {/* Matches StudySessionPage's badge treatment: only "diagnosing" gets
                            its own look; everything else reads as on-track. */}
                        <span
                          className={`badge ${session.status === 'diagnosing' ? 'diagnosing' : 'correct'}`}
                        >
                          {session.status}
                        </span>{' '}
                        · {session.completed_concepts} of {session.total_concepts} concepts ·{' '}
                        {relativeTime(session.updated_at)}
                      </span>
                    </button>
                    <button
                      className="session-delete"
                      aria-label="Delete session"
                      onClick={() => setConfirmingId(session.id)}
                    >
                      Delete
                    </button>
                  </>
                )}
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
