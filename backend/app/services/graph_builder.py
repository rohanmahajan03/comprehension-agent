"""Concept extraction + dependency graph construction (pipeline 1, step 2)."""

from graphlib import TopologicalSorter

from app.models import Concept, DependencyGraph

# Fixed sample graph shape used by the stub: (slug, name, summary, depends_on slugs)
_SAMPLE_CONCEPTS: list[tuple[str, str, str, list[str]]] = [
    ("limits", "Limits", "The value a function approaches as its input approaches a point.", []),
    (
        "continuity",
        "Continuity",
        "A function is continuous when its limit at a point equals its value there.",
        ["limits"],
    ),
    (
        "derivatives",
        "Derivatives",
        "The instantaneous rate of change of a function, defined as a limit of difference quotients.",
        ["limits", "continuity"],
    ),
    (
        "chain-rule",
        "Chain Rule",
        "How to differentiate a composition of functions.",
        ["derivatives"],
    ),
    (
        "implicit-differentiation",
        "Implicit Differentiation",
        "Differentiating relations that are not solved for one variable, using the chain rule.",
        ["chain-rule"],
    ),
]


def build_graph(doc_id: str, text: str) -> DependencyGraph:
    """Extract concepts and prerequisite links from raw chapter text.

    # TODO: Replace with real logic — call an LLM to (1) segment the chapter text
    # into distinct concepts with names and summaries, (2) infer prerequisite
    # ("depends_on") edges between them, and (3) validate the result is a DAG.
    # The stub below ignores `text` and returns a fixed calculus-flavored graph.
    """
    concepts = [
        Concept(
            id=f"{doc_id}:{slug}",
            name=name,
            summary=summary,
            depends_on=[f"{doc_id}:{dep}" for dep in deps],
        )
        for slug, name, summary, deps in _SAMPLE_CONCEPTS
    ]
    return DependencyGraph(doc_id=doc_id, concepts=concepts)


def topological_order(graph: DependencyGraph) -> list[Concept]:
    """Order concepts so every prerequisite comes before the concepts that need it."""
    by_id = {c.id: c for c in graph.concepts}
    sorter = TopologicalSorter({c.id: c.depends_on for c in graph.concepts})
    return [by_id[cid] for cid in sorter.static_order() if cid in by_id]
