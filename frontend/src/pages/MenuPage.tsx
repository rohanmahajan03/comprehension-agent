import { useEffect, useState } from "react";
import {
  deleteStudySession,
  listDocuments,
  listStudySessions,
  uploadTextbook,
} from "../api/client";
import { DocumentList } from "../components/DocumentList";
import { SessionList } from "../components/SessionList";
import type {
  DocumentStatus,
  DocumentSummary,
  StudySessionSummary,
} from "../types";

interface Props {
  // Called both right after a fresh upload and when opening a chapter already in the DB
  // (from the "Your chapters" list). `status` is passed only by the upload path, since a
  // listed chapter is always finalized — a 'draft' one goes to review instead of the graph.
  onOpenDocument: (docId: string, status?: DocumentStatus) => void;
  onResume: (session: StudySessionSummary) => void;
}

/**
 * The app's entry screen: resumable sessions first, then the upload form.
 *
 * Was `UploadPage`. Returning users see their unfinished work immediately; a first-time
 * user sees an empty list render nothing at all, so the page is exactly the upload form
 * it always was.
 */
export function MenuPage({ onOpenDocument, onResume }: Props) {
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  // Off by default: the straight-through pipeline is what most uploads want, and review
  // is a deliberate choice to spend time on a chapter before its questions are written.
  const [review, setReview] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessions, setSessions] = useState<StudySessionSummary[]>([]);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [documentsError, setDocumentsError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listStudySessions()
      .then((loaded) => {
        if (!cancelled) setSessions(loaded);
      })
      .catch((err) => {
        // Surfaced above the form rather than replacing the page: a broken list must
        // never block uploading a new chapter.
        if (!cancelled) {
          setSessionsError(
            `Couldn’t load your sessions: ${err instanceof Error ? err.message : String(err)}`,
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    listDocuments()
      .then((loaded) => {
        if (!cancelled) setDocuments(loaded);
      })
      .catch((err) => {
        if (!cancelled) {
          setDocumentsError(
            `Couldn’t load your chapters: ${err instanceof Error ? err.message : String(err)}`,
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleDelete = async (session: StudySessionSummary) => {
    try {
      await deleteStudySession(session.id);
      setSessions((prev) => prev.filter((s) => s.id !== session.id));
    } catch (err) {
      setSessionsError(
        `Couldn’t delete session: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  };

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const { doc_id, status } = await uploadTextbook(
        text,
        title.trim() || undefined,
        review,
      );
      onOpenDocument(doc_id, status);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      {sessionsError && <p className="error">{sessionsError}</p>}
      <SessionList
        sessions={sessions}
        onResume={onResume}
        onDelete={handleDelete}
      />

      {documentsError && <p className="error">{documentsError}</p>}
      <DocumentList
        documents={documents}
        onOpen={(doc) => onOpenDocument(doc.id)}
      />

      <div className="card">
        <h2>Upload a chapter</h2>
        <p>
          Paste chapter text below. The backend will extract concepts and build
          a dependency graph,{" "}
          {review
            ? "then stop for your review."
            : "then pre-generate questions."}
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
        <label className="upload-option">
          <input
            type="checkbox"
            checked={review}
            onChange={(e) => setReview(e.target.checked)}
          />
          <span>
            <strong>BETA: Review the concept graph first</strong>
            <small>
              Stops after extraction so you can fix concepts and prerequisites.
              Questions are written from whatever you approve, so nothing is
              spent on a graph you're about to change.
            </small>
          </span>
        </label>
        <p>
          <button onClick={submit} disabled={submitting || !text.trim()}>
            {submitting
              ? "Processing…"
              : review
                ? "Extract concepts"
                : "Build dependency graph"}
          </button>
        </p>
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  );
}
