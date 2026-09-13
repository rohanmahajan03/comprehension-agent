"""Human-in-the-loop graph editing (pipeline 1, between steps 2 and 3).

Every endpoint here requires the chapter to still be a DRAFT — see `_draft_graph` — which
it is only when the upload asked for review (`TextbookUpload.review`). Once a chapter is
finalized its graph is frozen, because questions, study sessions, and history entries all
point into it by concept id (docs/specs/2026-09-12-human-in-the-loop §8).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.models import Concept, DependencyGraph, DocumentStatus
from app.services import graph_builder
from app.store import Store, get_store

router = APIRouter(prefix="/api/graph", tags=["graph-edit"])


class NewConceptPayload(BaseModel):
    # Namespaced into a full concept id as {doc_id}:{slug}, so it has to look like the
    # slugs graph_builder produces — the id convention is load-bearing (see CLAUDE.md).
    slug: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class ConceptEditPayload(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    summary: str | None = Field(default=None, min_length=1)


class PrereqPayload(BaseModel):
    prereq_id: str


def _draft_graph(doc_id: str) -> tuple[Store, DependencyGraph]:
    """The guards every mutation here shares: the document exists, is still a draft, and
    has a graph.

    Draft status is the whole gate. A chapter uploaded without `review` is FINALIZED from
    the start, so these endpoints reject it exactly as they reject an approved one — there
    is no separate "is the feature on" switch to check.
    """
    store = get_store()
    status = store.get_document_status(doc_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"No document '{doc_id}'")
    if status is not DocumentStatus.DRAFT:
        raise HTTPException(
            status_code=409,
            detail="Chapter is finalized; its graph is locked. Upload with review enabled "
            "to edit a graph before its questions are written.",
        )

    graph = store.get_graph(doc_id)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"No graph found for doc '{doc_id}'")
    return store, graph


DraftGraph = Annotated[tuple[Store, DependencyGraph], Depends(_draft_graph)]


def _require_concept(graph: DependencyGraph, concept_id: str) -> Concept:
    concept = next((c for c in graph.concepts if c.id == concept_id), None)
    if concept is None:
        raise HTTPException(status_code=404, detail=f"Unknown concept '{concept_id}'")
    return concept


@router.post("/{doc_id}/concepts", response_model=Concept, status_code=201)
def add_concept(doc_id: str, payload: NewConceptPayload, draft: DraftGraph) -> Concept:
    store, graph = draft
    concept_id = f"{doc_id}:{payload.slug}"
    if any(c.id == concept_id for c in graph.concepts):
        raise HTTPException(status_code=409, detail=f"Concept '{concept_id}' already exists")

    concept = Concept(id=concept_id, name=payload.name, summary=payload.summary)
    graph.concepts.append(concept)
    store.save_graph(graph)
    return concept


@router.patch("/{doc_id}/concepts/{concept_id}", response_model=Concept)
def edit_concept(concept_id: str, payload: ConceptEditPayload, draft: DraftGraph) -> Concept:
    store, graph = draft
    concept = _require_concept(graph, concept_id)
    if payload.name is not None:
        concept.name = payload.name
    if payload.summary is not None:
        # The summary is this concept's own evidence passage for question generation
        # (source_passages()'s `target_concept` role), so editing it edits what every
        # question about the concept will be grounded in.
        concept.summary = payload.summary
    store.save_graph(graph)
    return concept


@router.delete("/{doc_id}/concepts/{concept_id}", status_code=204)
def delete_concept(concept_id: str, draft: DraftGraph) -> None:
    store, graph = draft
    _require_concept(graph, concept_id)

    # Dependents lose the prerequisite outright rather than being rewired around it: the
    # reviewer deleted this concept because it shouldn't be in the chapter, and inventing
    # replacement edges would be this code guessing at the chapter's structure.
    remaining = [c for c in graph.concepts if c.id != concept_id]
    for concept in remaining:
        if concept_id in concept.depends_on:
            concept.depends_on = [d for d in concept.depends_on if d != concept_id]
            concept.evidence.pop(concept_id, None)

    # Two calls, not one: save_graph only ever upserts the concepts it's handed, so the
    # deleted row needs its own delete (see Store.delete_concept). Stripping the
    # references first means the graph is never persisted pointing at a missing id.
    store.save_graph(DependencyGraph(doc_id=graph.doc_id, concepts=remaining))
    store.delete_concept(concept_id)


@router.post("/{doc_id}/concepts/{concept_id}/prereqs", status_code=204)
def add_prereq(concept_id: str, payload: PrereqPayload, draft: DraftGraph) -> None:
    """Make `concept_id` depend on `payload.prereq_id`."""
    store, graph = draft
    concept = _require_concept(graph, concept_id)
    prereq = _require_concept(graph, payload.prereq_id)

    if payload.prereq_id == concept_id:
        raise HTTPException(status_code=422, detail="A concept cannot depend on itself")
    if graph_builder.creates_cycle(graph, payload.prereq_id, concept_id):
        # Names, not ids: this detail is read by the reviewer who just tried the edit, and
        # an id is mostly the doc_id prefix they never chose. Callers branch on the status.
        raise HTTPException(
            status_code=422,
            detail=f"“{prereq.name}” already depends on “{concept.name}”, so this would "
            "create a cycle",
        )

    if payload.prereq_id not in concept.depends_on:
        concept.depends_on.append(payload.prereq_id)
        # No source-text quote exists for a hand-added edge. An empty evidence entry is
        # what question_generator.source_passages() already skips (its add() ignores
        # falsy text), so this edge simply contributes no `prerequisite_link` passage —
        # the prerequisite's own summary still reaches the generator.
        concept.evidence[payload.prereq_id] = ""
    store.save_graph(graph)


@router.delete("/{doc_id}/concepts/{concept_id}/prereqs/{prereq_id}", status_code=204)
def delete_prereq(concept_id: str, prereq_id: str, draft: DraftGraph) -> None:
    store, graph = draft
    concept = _require_concept(graph, concept_id)
    if prereq_id not in concept.depends_on:
        raise HTTPException(
            status_code=404, detail=f"'{concept_id}' does not depend on '{prereq_id}'"
        )

    concept.depends_on = [d for d in concept.depends_on if d != prereq_id]
    concept.evidence.pop(prereq_id, None)
    store.save_graph(graph)
