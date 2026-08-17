"""Cheap iteration harness for the diagnoser suite. Not a test — run it directly.

A full `tests/diagnoser_geval` run drives eight cases through a five-turn agentic loop plus
nested generation and two judges each. That is the wrong instrument for "did my prompt edit
help?" — it is slow, and its cost is dominated by the seven cases you did not change
anything for.

Two modes, each a fraction of a full run:

    # One case end-to-end, with the full trajectory printed
    python -m tests.diagnoser_geval.probe case lsm_tree_missing_memtable

    # Judge calibration: fixed inputs, known-good and known-bad, ~4 calls
    python -m tests.diagnoser_geval.probe judges

The `judges` mode exists because recalibrating a judge until the suite goes green is the
easiest way to build a test that measures nothing. Both judges here are run against
deliberately bad inputs they must reject; a judge that passes everything is a rubber stamp,
and on a green run that is indistinguishable from a healthy pass. Re-run this after every
judge-prompt edit.

Requires LLM_API_KEY:
    cd backend && set -a && source ../.env && set +a && python -m tests.diagnoser_geval.probe ...
"""

from __future__ import annotations

import sys

from .golden import CASES, build_graph
from .support import judge_question_relevance, judge_reasoning_quality, run_case


def probe_case(name: str) -> int:
    case = next((c for c in CASES if c.name == name), None)
    if case is None:
        print(f"no case named {name!r}. Available:")
        for c in CASES:
            print(f"  {c.name}")
        return 1

    graph = build_graph()
    by_id = {c.id: c for c in graph.concepts}
    result, trace = run_case(case, graph)
    suspect_slug = result.suspected_gap_concept_id.split(":", 1)[1]

    print(f"=== {case.name} ===")
    print(f"answered concept : {case.answered_concept}")
    print(f"acceptable       : {sorted(case.acceptable_suspects)}  (preferred: {case.preferred_suspect})")
    print(f"forbidden        : {sorted(case.forbidden_suspects)}")
    print()
    print("--- trajectory ---")
    for i, (tool, payload) in enumerate(trace.tool_calls, 1):
        detail = payload.get("concept_id") or payload.get("suspected_gap_concept_id") or ""
        focus = payload.get("focus")
        print(f"  {i}. {tool}({detail}){f'  focus={focus!r}' if focus else ''}")
    print(f"  turns={trace.turns_used}  forced_final={trace.forced_final}  "
          f"rejected={len(trace.rejected_submissions)}")
    print()

    verdict = (
        "FORBIDDEN" if suspect_slug in case.forbidden_suspects
        else "ok (preferred)" if suspect_slug == case.preferred_suspect
        else "ok" if suspect_slug in case.acceptable_suspects
        else "MISS"
    )
    print("--- diagnosis ---")
    print(f"  suspect  : {suspect_slug}   [{verdict}]")
    print(f"  reasoning: {result.reasoning}")
    print(f"  question : {result.targeted_question.prompt}")
    print(f"  notes    : {result.targeted_question.expected_answer_notes[:200]}")
    print(f"  source   : {'reused existing' if ':diagnostic' not in result.targeted_question.id else 'generated new'}")
    print()

    suspect = by_id.get(result.suspected_gap_concept_id)
    if suspect is not None:
        relevant, why_r = judge_question_relevance(result.targeted_question.prompt, suspect)
        grounded, why_g = judge_reasoning_quality(case.evaluation_explanation, suspect, result.reasoning, graph)
        print("--- judges ---")
        print(f"  question probes suspect: {relevant}  ({why_r})")
        print(f"  reasoning grounded     : {grounded}  ({why_g})")
    return 0


def probe_judges() -> int:
    """Confirm both judges reject inputs they should, not just accept good ones."""
    graph = build_graph()
    by_id = {c.id: c for c in graph.concepts}
    compaction = by_id["case3:compaction"]
    finding = (
        "The answer states the sorting requirement correctly. It omits the second "
        "requirement — that each key appears at most once within a merged segment."
    )

    relevance_cases = [
        (
            True,
            "on-target",
            "After a set of segments has been processed, what is true of any key that was "
            "updated several times across them, and why?",
        ),
        (False, "different concept", "What is a B-tree page, and how large is it?"),
        (False, "too broad to isolate", "What are some important ideas in database storage engines?"),
    ]
    reasoning_cases = [
        (
            True,
            "specific chain",
            "The answer named the sorting requirement but not the per-key uniqueness one. "
            "Uniqueness within a merged segment is exactly what compaction guarantees by "
            "discarding all but the most recent update for each key, so the omission points "
            "at compaction rather than at the SSTable format itself.",
        ),
        (False, "generic", "The student seems confused about the fundamentals here."),
        (
            False,
            "restates dependency only",
            "SSTable depends on compaction, so the gap is probably in compaction.",
        ),
    ]

    ok = 0
    print("--- question relevance judge ---")
    for expected, label, prompt in relevance_cases:
        got, why = judge_question_relevance(prompt, compaction)
        ok += got == expected
        print(f"  {'OK ' if got == expected else '!! '}{label:22} expected={expected} got={got}  ({why[:90]})")
    print()
    print("--- reasoning quality judge ---")
    for expected, label, reasoning in reasoning_cases:
        got, why = judge_reasoning_quality(finding, compaction, reasoning, graph)
        ok += got == expected
        print(f"  {'OK ' if got == expected else '!! '}{label:22} expected={expected} got={got}  ({why[:90]})")

    total = len(relevance_cases) + len(reasoning_cases)
    print()
    print(f"calibration: {ok}/{total} behaved as intended")
    print(
        "a judge that passes every bad input is a rubber stamp — it will make the suite go "
        "green while measuring nothing"
    )
    return 0 if ok == total else 1


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "judges":
        return probe_judges()
    if len(argv) >= 3 and argv[1] == "case":
        return probe_case(argv[2])
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
