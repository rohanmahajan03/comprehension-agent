"""The question-id convention, in one place.

Question ids are `{concept_id}:{suffix}`: `q1`, `q2`, … for the set `question_generator`
writes at ingestion, and `diagnostic1`, `diagnostic2`, … for one the diagnoser mints
mid-session (numbered because a concept can be diagnosed more than once in a session with
a different gap each time — see `diagnoser._next_diagnostic_id`).

Both the minting and the reading side live here because there are now two readers. The
convention used to have exactly one owner, and `study_session._diagnostic_question_ids()`
deliberately derives diagnostics from the session's own diagnosis records rather than
parsing the suffix, precisely to keep it that way. That works only while the question is
"was this served as a probe *in this session*". Counting a chapter's **testable** concepts
is a different question — "was this question written by pipeline 1" — and it has no
session to consult, so it has to read the id.

This sits in the models layer, not in `app.services`, because the stores need it and a
Store importing from the services layer would invert the layering every other module
follows (the same constraint that keeps `completed_concepts` in the router).
"""

import re
from collections.abc import Iterable

#: The suffix stem. Kept as a constant so the word "diagnostic" is written once, including
#: inside the SQL pattern below.
DIAGNOSTIC_STEM = "diagnostic"

#: Matches the trailing `:diagnostic{n}` segment and nothing else.
#:
#: Anchored at the end and requiring the digits deliberately: a bare `":diagnostic" in id`
#: test would misread a concept whose own slug happens to start with the word — the id
#: `doc:diagnostic-tools:q1` is a pipeline-1 question on a concept called "diagnostic
#: tools", not a probe. `[0-9]` rather than `\d` so the identical pattern is valid in both
#: Python's `re` and Postgres' regex operator.
DIAGNOSTIC_ID_PATTERN = rf":{DIAGNOSTIC_STEM}[0-9]+$"

_DIAGNOSTIC_ID_RE = re.compile(DIAGNOSTIC_ID_PATTERN)


def diagnostic_id_prefix(concept_id: str) -> str:
    """The `{concept_id}:diagnostic` stem every probe id on this concept starts with."""
    return f"{concept_id}:{DIAGNOSTIC_STEM}"


def diagnostic_question_id(concept_id: str, number: int) -> str:
    """The `number`-th diagnostic question id for this concept. 1-based."""
    return f"{diagnostic_id_prefix(concept_id)}{number}"


def is_diagnostic_question_id(question_id: str) -> bool:
    """Whether this id was minted by the diagnoser rather than written by pipeline 1."""
    return _DIAGNOSTIC_ID_RE.search(question_id) is not None


def has_pipeline_one_question(question_ids: Iterable[str]) -> bool:
    """Whether any of these ids is a question pipeline 1 wrote — i.e. whether the concept
    they belong to is *testable*, and so a node the student can be sent to on the main track.

    Diagnostic ids are excluded so the answer is stable for the life of the chapter. Both
    stores rebuild `Concept.questions` from the question index on every `get_graph()`, so a
    concept the diagnoser probed would otherwise become "testable" mid-session, appear in
    the graph, and bump the progress denominator — see
    docs/specs/2026-09-20-graph-progress-coloring-design.md §4.
    """
    return any(not is_diagnostic_question_id(qid) for qid in question_ids)
