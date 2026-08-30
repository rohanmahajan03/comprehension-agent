import type { StudySessionSummary } from '../types'

interface Props {
  sessions: StudySessionSummary[]
  onResume: (session: StudySessionSummary) => void
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

export function SessionList({ sessions, onResume }: Props) {
  // Nothing to continue: render nothing at all, so a first-time user sees only the
  // upload form rather than an empty-state card explaining a feature they haven't used.
  if (sessions.length === 0) return null

  return (
    <div className="card">
      <h2>Continue a session</h2>
      <ul className="session-list">
        {sessions.map((session) => (
          <li key={session.id}>
            <button className="session-row" onClick={() => onResume(session)}>
              {/* Untitled chapters fall back to a server-computed text snippet, so two
                  of them stay distinguishable in the list. */}
              <strong>{session.title ?? session.text_snippet}</strong>
              <span>
                {/* Matches StudySessionPage's badge treatment: only "diagnosing" gets its
                    own look; everything else reads as on-track. */}
                <span
                  className={`badge ${session.status === 'diagnosing' ? 'diagnosing' : 'correct'}`}
                >
                  {session.status}
                </span>{' '}
                · {session.completed_concepts} of {session.total_concepts} concepts ·{' '}
                {relativeTime(session.updated_at)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
