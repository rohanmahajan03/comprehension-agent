"""The "Done studying for now" journal: summary contents, the GitHub write, the endpoint.

Free — `publish()`'s HTTP helper is replaced with a fake, so nothing reaches GitHub.
"""

import io
import urllib.error
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.models import (
    Answer,
    Concept,
    DependencyGraph,
    DiagnosisResult,
    EvaluationResult,
    HistoryEntry,
    Question,
    StudySession,
    StudySessionStatus,
)
from app.services import study_journal

client = TestClient(app)


def _graph() -> DependencyGraph:
    return DependencyGraph(
        doc_id="doc",
        concepts=[
            Concept(id="doc:limits", name="Limits", summary="s"),
            Concept(id="doc:derivative", name="Derivative", summary="s", depends_on=["doc:limits"]),
            Concept(id="doc:chain", name="Chain Rule", summary="s", depends_on=["doc:derivative"]),
        ],
    )


def _entry(
    concept_id: str,
    correct: bool,
    *,
    suffix: str = "q1",
    overridden: bool = False,
    diagnosis_to: str | None = None,
) -> HistoryEntry:
    question = Question(
        id=f"{concept_id}:{suffix}",
        concept_id=concept_id,
        prompt=f"Explain {concept_id}",
        expected_answer_notes="notes",
    )
    diagnosis = None
    if diagnosis_to is not None:
        diagnosis = DiagnosisResult(
            suspected_gap_concept_id=diagnosis_to,
            reasoning="r",
            targeted_question=Question(
                id=f"{diagnosis_to}:diagnostic1",
                concept_id=diagnosis_to,
                prompt="probe",
                expected_answer_notes="n",
            ),
        )
    return HistoryEntry(
        question=question,
        answer=Answer(question_id=question.id, text="my answer"),
        evaluation=EvaluationResult(
            correct=correct, explanation=f"verdict on {concept_id}"
        ),
        diagnosis=diagnosis,
        overridden=overridden,
    )


def _session(history: list[HistoryEntry]) -> StudySession:
    return StudySession(
        id="abc123",
        doc_id="doc",
        current_concept_id="doc:chain",
        history=history,
        created_at=datetime(2026, 10, 20, 9, 30, tzinfo=UTC),
    )


class TestSummarize:
    def test_sorts_concepts_into_strong_recovered_and_still_shaky(self):
        session = _session(
            [
                _entry("doc:limits", True),
                _entry("doc:derivative", False, diagnosis_to="doc:limits"),
                _entry("doc:limits", True, suffix="diagnostic1"),
                _entry("doc:derivative", True),
                _entry("doc:chain", False),
            ]
        )
        md = study_journal.summarize(session, _graph(), "Calculus Ch. 2")

        assert md.startswith("# Calculus Ch. 2\n")
        strong = md.split("## Where I'm strong")[1].split("## Where I struggled")[0]
        assert "**Limits** — correct, 2 for 2" in strong
        assert "Derivative" not in strong
        assert "**Derivative** — missed once, then got it right" in md
        still_open = md.split("### Still open")[1].split("###")[0]
        assert "**Chain Rule** — missed 1 of 1" in still_open
        assert "verdict on doc:chain" in still_open
        assert "A miss on **Derivative** was traced back to **Limits**" in md
        assert "**Up next:** Chain Rule" in md

    def test_topics_table_follows_prerequisite_order(self):
        session = _session([_entry("doc:chain", True), _entry("doc:limits", True)])
        md = study_journal.summarize(session, _graph(), None)
        assert md.index("| Limits |") < md.index("| Chain Rule |")
        assert md.startswith("# Untitled chapter\n")

    def test_last_outcome_wins_so_a_later_miss_reopens_a_concept(self):
        session = _session([_entry("doc:limits", True), _entry("doc:limits", False)])
        md = study_journal.summarize(session, _graph(), "t")
        assert "**Limits** — missed 1 of 2" in md.split("### Still open")[1]

    def test_an_overridden_miss_counts_as_correct(self):
        session = _session([_entry("doc:limits", False, overridden=True)])
        md = study_journal.summarize(session, _graph(), "t")
        assert "1 correct, 1 of them by override" in md
        assert "**Limits** — correct, first try" in md

    def test_self_diagnosis_is_not_reported_as_a_traced_gap(self):
        session = _session([_entry("doc:limits", False, diagnosis_to="doc:limits")])
        assert "Root gaps" not in study_journal.summarize(session, _graph(), "t")

    def test_completed_session_says_so_instead_of_naming_up_next(self):
        session = _session([_entry("doc:limits", True)])
        session.status = StudySessionStatus.COMPLETED
        md = study_journal.summarize(session, _graph(), "t")
        assert "chapter complete" in md and "Up next" not in md


def test_journal_path_is_stable_per_session():
    session = _session([])
    assert (
        study_journal.journal_path(session, "Storage & Retrieval: Ch. 3!")
        == "sessions/2026-10-20-storage-retrieval-ch-3-abc123.md"
    )
    assert study_journal.journal_path(session, None).endswith("-untitled-chapter-abc123.md")


class TestPublish:
    @pytest.fixture(autouse=True)
    def _token(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(get_settings(), "journal_github_token", "tok")
        monkeypatch.setattr(get_settings(), "journal_repo", "me/journal")

    def _fake(self, monkeypatch, existing_sha: str | None):
        calls: list[tuple[str, str, dict | None]] = []

        def fake_request(method, url, token, body=None):
            calls.append((method, url, body))
            if method == "GET":
                if existing_sha is None:
                    raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b"{}"))
                return {"sha": existing_sha}
            return {
                "content": {"html_url": "https://github.com/me/journal/blob/main/x.md"},
                "commit": {"html_url": "https://github.com/me/journal/commit/1"},
            }

        monkeypatch.setattr(study_journal, "_request", fake_request)
        return calls

    def test_first_save_creates_the_file_without_a_sha(self, monkeypatch):
        calls = self._fake(monkeypatch, existing_sha=None)
        result = study_journal.publish("sessions/x.md", "# hi\n", "msg")
        method, url, body = calls[-1]
        assert method == "PUT" and url.endswith("/repos/me/journal/contents/sessions/x.md")
        assert "sha" not in body and body["message"] == "msg" and body["branch"] == "main"
        assert result.commit_url == "https://github.com/me/journal/commit/1"

    def test_later_save_overwrites_with_the_current_sha(self, monkeypatch):
        calls = self._fake(monkeypatch, existing_sha="deadbeef")
        study_journal.publish("sessions/x.md", "# hi\n", "msg")
        assert calls[-1][2]["sha"] == "deadbeef"

    def test_missing_repo_is_a_publish_error(self, monkeypatch):
        def fake_request(method, url, token, body=None):
            raise urllib.error.HTTPError(
                url, 404, "Not Found", {}, io.BytesIO(b'{"message": "Not Found"}')
            )

        monkeypatch.setattr(study_journal, "_request", fake_request)
        with pytest.raises(study_journal.JournalPublishError, match="me/journal"):
            # GET's 404 is "no file yet"; it's the PUT's 404 that means no repo.
            study_journal.publish("sessions/x.md", "# hi\n", "msg")


def test_publish_without_a_token_is_not_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(get_settings(), "journal_github_token", "")
    with pytest.raises(study_journal.JournalNotConfigured):
        study_journal.publish("p.md", "c", "m")


class TestEndpoint:
    def _session_with_an_answer(self) -> str:
        doc_id = client.post("/api/textbook", json={"text": "A chapter.", "title": "Calc"}).json()[
            "doc_id"
        ]
        session = client.post("/api/study-session/start", json={"doc_id": doc_id}).json()
        client.post(
            f"/api/study-session/{session['id']}/answer",
            json={"question_id": session["pending_question"]["id"], "text": "x"},
        )
        return session["id"]

    def test_commits_the_summary_and_leaves_the_session_resumable(self, monkeypatch):
        published: dict = {}

        def fake_publish(path, content, message):
            published.update(path=path, content=content, message=message)
            return study_journal.PublishResult(path, "file-url", "commit-url")

        monkeypatch.setattr(study_journal, "publish", fake_publish)
        session_id = self._session_with_an_answer()
        before = client.get(f"/api/study-session/{session_id}").json()

        response = client.post(f"/api/study-session/{session_id}/journal")

        assert response.status_code == 200
        body = response.json()
        assert body["commit_url"] == "commit-url"
        assert body["markdown"] == published["content"]
        assert published["path"].endswith(f"-calc-{session_id}.md")
        assert published["content"].startswith("# Calc\n")
        assert published["message"].startswith("Study session: Calc (")
        assert client.get(f"/api/study-session/{session_id}").json() == before

    def test_unconfigured_journal_is_503(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "journal_github_token", "")
        response = client.post(f"/api/study-session/{self._session_with_an_answer()}/journal")
        assert response.status_code == 503
        assert "JOURNAL_GITHUB_TOKEN" in response.json()["detail"]

    def test_github_failure_is_502(self, monkeypatch):
        def failing(path, content, message):
            raise study_journal.JournalPublishError("GitHub returned 500")

        monkeypatch.setattr(study_journal, "publish", failing)
        response = client.post(f"/api/study-session/{self._session_with_an_answer()}/journal")
        assert response.status_code == 502

    def test_nothing_answered_yet_is_409(self):
        doc_id = client.post("/api/textbook", json={"text": "A chapter."}).json()["doc_id"]
        session = client.post("/api/study-session/start", json={"doc_id": doc_id}).json()
        assert client.post(f"/api/study-session/{session['id']}/journal").status_code == 409

    def test_unknown_session_is_404(self):
        assert client.post("/api/study-session/nope/journal").status_code == 404
