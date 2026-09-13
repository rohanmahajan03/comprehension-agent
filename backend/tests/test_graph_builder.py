"""Unit tests for graph_builder's pure graph logic. No LLM calls — free and fast.

`creates_cycle` is the one check standing between either edge-producing path and a graph
`topological_order` would raise on: `build_graph` applies it to LLM-extracted edges,
`routers/graph_edit.py` to the ones a reviewer draws by hand.
"""

from graphlib import CycleError

import pytest

from app.models import Concept, DependencyGraph
from app.services.graph_builder import creates_cycle, topological_order


def _graph(deps: dict[str, list[str]]) -> DependencyGraph:
    return DependencyGraph(
        doc_id="d",
        concepts=[
            Concept(id=cid, name=cid.title(), summary=f"About {cid}.", depends_on=prereqs)
            for cid, prereqs in deps.items()
        ],
    )


def test_unrelated_concepts_can_be_linked() -> None:
    graph = _graph({"a": [], "b": ["a"], "c": []})
    assert creates_cycle(graph, frm="c", to="b") is False


def test_a_direct_back_edge_is_a_cycle() -> None:
    """b already depends on a, so making a depend on b closes a two-node loop."""
    graph = _graph({"a": [], "b": ["a"]})
    assert creates_cycle(graph, frm="b", to="a") is True


def test_a_transitive_back_edge_is_a_cycle() -> None:
    """The case a one-hop check would miss: c depends on a only through b."""
    graph = _graph({"a": [], "b": ["a"], "c": ["b"]})
    assert creates_cycle(graph, frm="c", to="a") is True


def test_a_concept_cannot_depend_on_itself() -> None:
    graph = _graph({"a": []})
    assert creates_cycle(graph, frm="a", to="a") is True


def test_a_second_path_to_a_shared_prerequisite_is_not_a_cycle() -> None:
    """A diamond is still a DAG. Both b and c depend on a; making c depend on b adds a
    second route to a, which is ordinary structure, not a loop."""
    graph = _graph({"a": [], "b": ["a"], "c": ["a"]})
    assert creates_cycle(graph, frm="b", to="c") is False


def test_unknown_ids_are_walked_over_rather_than_raising() -> None:
    """`depends_on` is a plain id list with no referential integrity behind it, so the walk
    has to tolerate an id the graph doesn't contain."""
    graph = _graph({"a": ["ghost"], "b": []})
    assert creates_cycle(graph, frm="a", to="b") is False
    assert creates_cycle(graph, frm="missing", to="a") is False


def test_every_edge_the_check_allows_leaves_a_sortable_graph() -> None:
    """The invariant the check exists for: topological_order raises on a cycle, and this is
    what keeps one from ever being built."""
    graph = _graph({"a": [], "b": ["a"], "c": ["b"]})
    by_id = {c.id: c for c in graph.concepts}

    assert creates_cycle(graph, frm="c", to="a") is True
    by_id["a"].depends_on.append("c")  # add it anyway, as an unguarded path would
    with pytest.raises(CycleError):
        topological_order(graph)
