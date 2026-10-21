"""The study journal: "Done studying for now" commits a session summary to GitHub.

Two halves, kept separate so the summary is testable without a network:

- `summarize()` is pure — session + graph in, markdown out. No LLM call: everything it
  says is read straight off the session's history, so it costs nothing and can't invent a
  strength the student never showed.
- `publish()` writes that markdown to `settings.journal_repo` through GitHub's contents
  API, which makes exactly one commit per call. Stdlib `urllib` rather than a new
  dependency, since it is two requests.

One file per study session, overwritten on every press, so a session studied across three
sittings is one file with three commits rather than three files that each repeat
everything before them.
"""

import base64
import json
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime

import certifi

from app.config import get_settings
from app.models import DependencyGraph, HistoryEntry, StudySession, StudySessionStatus
from app.services.graph_builder import topological_order

_API = "https://api.github.com"
# certifi's CA bundle rather than the system store: python.org's macOS builds ship without
# one, so a native backend fails every request with CERTIFICATE_VERIFY_FAILED.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


class JournalNotConfigured(Exception):
    """No GitHub token is set, so there is nowhere to commit to."""


class JournalPublishError(Exception):
    """GitHub refused the write, or could not be reached."""


@dataclass
class PublishResult:
    path: str
    file_url: str
    commit_url: str


@dataclass
class _ConceptRecord:
    concept_id: str
    name: str
    entries: list[HistoryEntry]

    @property
    def asked(self) -> int:
        return len(self.entries)

    @property
    def correct(self) -> int:
        return sum(1 for e in self.entries if e.effective_correct)

    @property
    def missed(self) -> int:
        return self.asked - self.correct

    @property
    def last_correct(self) -> bool:
        # Last outcome wins — the same rule the graph colouring uses
        # (frontend/src/lib/conceptProgress.ts), so the journal and the graph never
        # disagree about whether a concept is still a gap.
        return self.entries[-1].effective_correct

    @property
    def standing(self) -> str:
        if not self.last_correct:
            return "Still shaky"
        return "Strong" if self.missed == 0 else "Recovered"


def journal_path(study_session: StudySession, title: str | None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "untitled chapter").lower()).strip("-")
    slug = slug[:50].rstrip("-") or "chapter"
    return f"sessions/{study_session.created_at:%Y-%m-%d}-{slug}-{study_session.id}.md"


def _records(study_session: StudySession, graph: DependencyGraph) -> list[_ConceptRecord]:
    """One record per concept the session asked about, in prerequisite order.

    A diagnostic probe counts toward its suspect — `diagnoser` sets the targeted
    question's `concept_id` to the suspect's id — so a gap the diagnoser traced shows up
    under the concept that actually holds it.
    """
    names = {c.id: c.name for c in graph.concepts}
    by_concept: dict[str, list[HistoryEntry]] = {}
    for entry in study_session.history:
        by_concept.setdefault(entry.question.concept_id, []).append(entry)

    order = [c.id for c in topological_order(graph)]
    # A concept missing from the order (removed since) still gets listed, at the end.
    ordered_ids = [cid for cid in order if cid in by_concept]
    ordered_ids += [cid for cid in by_concept if cid not in order]
    return [
        _ConceptRecord(cid, names.get(cid, cid.rsplit(":", 1)[-1]), by_concept[cid])
        for cid in ordered_ids
    ]


def _one_line(text: str, limit: int = 400) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def summarize(
    study_session: StudySession,
    graph: DependencyGraph,
    title: str | None,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(UTC)
    names = {c.id: c.name for c in graph.concepts}
    records = _records(study_session, graph)
    history = study_session.history
    correct = sum(1 for e in history if e.effective_correct)
    overridden = sum(1 for e in history if e.overridden)

    strong = [r for r in records if r.standing == "Strong"]
    recovered = [r for r in records if r.standing == "Recovered"]
    shaky = [r for r in records if r.standing == "Still shaky"]

    lines: list[str] = [
        f"# {title or 'Untitled chapter'}",
        "",
        f"_Study session `{study_session.id}` · started "
        f"{study_session.created_at:%Y-%m-%d %H:%M} UTC · saved {now:%Y-%m-%d %H:%M} UTC_",
        "",
        "## At a glance",
        "",
        f"- **Questions answered:** {len(history)} ({correct} correct"
        + (f", {overridden} of them by override" if overridden else "")
        + ")",
        f"- **Concepts studied:** {len(records)}",
        f"- **Strong:** {len(strong)} · **Recovered:** {len(recovered)} · "
        f"**Still shaky:** {len(shaky)}",
    ]
    if study_session.status is StudySessionStatus.COMPLETED:
        lines.append("- **Status:** chapter complete")
    elif study_session.current_concept_id:
        lines.append(
            f"- **Up next:** {names.get(study_session.current_concept_id, study_session.current_concept_id)}"
        )

    lines += ["", "## Topics studied", ""]
    if records:
        lines += ["| Concept | Asked | Correct | Where it stands |", "| --- | --- | --- | --- |"]
        lines += [f"| {r.name} | {r.asked} | {r.correct} | {r.standing} |" for r in records]
    else:
        lines.append("_No questions answered yet._")

    lines += ["", "## Where I'm strong", ""]
    if strong:
        for r in strong:
            first_try = "first try" if r.asked == 1 else f"{r.asked} for {r.asked}"
            lines.append(f"- **{r.name}** — correct, {first_try}")
    else:
        lines.append("_Nothing answered cleanly yet._")

    lines += ["", "## Where I struggled", ""]
    if not shaky and not recovered:
        lines.append("_No misses this session._")
    if shaky:
        lines += ["### Still open", ""]
        for r in shaky:
            # The most recent miss is the one that still stands; its explanation is the
            # evaluator saying what the answer lacked, which is the useful part to reread.
            last = r.entries[-1]
            lines.append(f"- **{r.name}** — missed {r.missed} of {r.asked}")
            lines.append(f"  - _Question:_ {_one_line(last.question.prompt)}")
            lines.append(f"  - _What was missing:_ {_one_line(last.evaluation.explanation)}")
        lines.append("")
    if recovered:
        lines += ["### Worked through", ""]
        for r in recovered:
            misses = "once" if r.missed == 1 else f"{r.missed} times"
            lines.append(f"- **{r.name}** — missed {misses}, then got it right")
        lines.append("")

    traced = [
        (e.question.concept_id, e.diagnosis.suspected_gap_concept_id)
        for e in history
        if e.diagnosis is not None
        and e.diagnosis.suspected_gap_concept_id != e.question.concept_id
    ]
    if traced:
        lines += ["### Root gaps the tutor traced", ""]
        seen: set[tuple[str, str]] = set()
        for answered, suspect in traced:
            if (answered, suspect) in seen:
                continue
            seen.add((answered, suspect))
            lines.append(
                f"- A miss on **{names.get(answered, answered)}** was traced back to "
                f"**{names.get(suspect, suspect)}**"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def commit_message(study_session: StudySession, title: str | None) -> str:
    history = study_session.history
    correct = sum(1 for e in history if e.effective_correct)
    return f"Study session: {title or 'Untitled chapter'} ({correct}/{len(history)} correct)"


def _request(method: str, url: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20, context=_SSL_CONTEXT) as response:
        return json.loads(response.read() or b"{}")


def publish(path: str, content: str, message: str) -> PublishResult:
    """Create or overwrite `path` in the journal repo as one commit."""
    settings = get_settings()
    if not settings.journal_github_token:
        raise JournalNotConfigured(
            "Set JOURNAL_GITHUB_TOKEN in .env to commit study summaries to GitHub"
        )
    url = f"{_API}/repos/{settings.journal_repo}/contents/{path}"
    token = settings.journal_github_token

    # Overwriting needs the current blob sha; a 404 just means this is the first save.
    sha: str | None = None
    try:
        sha = _request("GET", f"{url}?ref={settings.journal_branch}", token).get("sha")
    except urllib.error.HTTPError as err:
        if err.code != 404:
            raise JournalPublishError(_describe(err, settings.journal_repo)) from err
    except urllib.error.URLError as err:
        raise JournalPublishError(f"Could not reach GitHub: {err.reason}") from err

    body: dict = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "branch": settings.journal_branch,
    }
    if sha:
        body["sha"] = sha
    try:
        result = _request("PUT", url, token, body)
    except urllib.error.HTTPError as err:
        raise JournalPublishError(_describe(err, settings.journal_repo)) from err
    except urllib.error.URLError as err:
        raise JournalPublishError(f"Could not reach GitHub: {err.reason}") from err

    return PublishResult(
        path=path,
        file_url=result.get("content", {}).get("html_url", ""),
        commit_url=result.get("commit", {}).get("html_url", ""),
    )


def _describe(err: urllib.error.HTTPError, repo: str) -> str:
    try:
        detail = json.loads(err.read() or b"{}").get("message", "")
    except ValueError:
        detail = ""
    if err.code == 404:
        return (
            f"GitHub repo '{repo}' not found, or the token can't see it"
            + (f" ({detail})" if detail else "")
        )
    if err.code in (401, 403):
        return f"GitHub rejected the token for '{repo}' ({detail or err.code})"
    return f"GitHub returned {err.code}" + (f": {detail}" if detail else "")
