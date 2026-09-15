"""Human-in-the-loop graph editing (pipeline 1, between steps 2 and 3).

Every endpoint here requires the chapter to still be a DRAFT — see `_draft_graph` — which
it is only when the upload asked for review (`TextbookUpload.review`). Once a chapter is
finalized its graph is frozen, because questions, study sessions, and history entries all
point into it by concept id (docs/specs/2026-09-12-human-in-the-loop §8).
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.models import Concept, DependencyGraph, DocumentStatus, EvidenceProposal
from app.services import evidence_finder, graph_builder
from app.services.text_match import is_verbatim
from app.store import Store, get_store

logger = logging.getLogger(__name__)

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
    # How an evidence proposal gets accepted — the whole list, replacing whatever is
    # stored, so unticking a quote in the review UI is expressible. None means "leave the
    # quotes alone", which is what every other edit sends.
    source_quotes: list[str] | None = Field(default=None)


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


def _require_chapter(store: Store, doc_id: str) -> str:
    """The chapter text every evidence scan searches.

    Separate from `_draft_graph`'s checks because it's only the evidence paths that need
    it — no other mutation here reads the source document at all.
    """
    chapter = store.get_document(doc_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail=f"No text stored for document '{doc_id}'")
    return chapter


def _checked_quotes(store: Store, doc_id: str, quotes: list[str]) -> list[str]:
    """Reject anything that isn't genuinely a passage of this chapter.

    `evidence_finder` already discards non-verbatim quotes, but it isn't the only way into
    the field: this endpoint accepts a list from a client, and a reviewer who "fixes" a
    typo in a proposed quote has turned provenance back into prose. Enforcing the invariant
    at the write rather than only at the source is what lets everything downstream treat
    `source_quotes` as chapter text without re-checking (design doc §3).
    """
    if not quotes:
        return []
    chapter = _require_chapter(store, doc_id)
    for quote in quotes:
        if not is_verbatim(quote, chapter):
            raise HTTPException(
                status_code=422,
                detail="Source quotes must appear verbatim in the chapter; this one does "
                f"not: “{quote[:120]}”",
            )
    return [q.strip() for q in quotes]


def _edge_evidence(store: Store, doc_id: str, concept: Concept, prereq: Concept) -> str:
    """Best-effort source quote for an edge a human drew — `""` when the chapter has none.

    Silent and non-blocking, both directions. The edge is the reviewer's assertion and
    stands on its own; the quote is a bonus that makes it indistinguishable from an
    extracted edge when one exists. So a chapter that never links the two concepts, and an
    LLM call that fails outright, both land on exactly the pre-existing behavior: an empty
    evidence entry, which `question_generator.source_passages()` already skips (its `add()`
    ignores falsy text), so the edge contributes no `prerequisite_link` passage and the
    prerequisite's own summary still reaches the generator.
    """
    chapter = store.get_document(doc_id)
    if not chapter:
        return ""
    try:
        return evidence_finder.find_edge_evidence(chapter, concept, prereq) or ""
    except Exception:
        # Swallowed on purpose: failing the edit would lose the reviewer's structural work
        # over a missing quote. Logged rather than silent so a systematically broken scan
        # is still findable.
        logger.warning(
            "Edge evidence scan failed for %s -> %s; storing the edge without a quote",
            prereq.id,
            concept.id,
            exc_info=True,
        )
        return ""


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
def edit_concept(
    doc_id: str, concept_id: str, payload: ConceptEditPayload, draft: DraftGraph
) -> Concept:
    store, graph = draft
    concept = _require_concept(graph, concept_id)
    if payload.name is not None:
        concept.name = payload.name
    if payload.summary is not None:
        # The summary is this concept's own evidence passage for question generation
        # (source_passages()'s `target_concept` role), so editing it edits what every
        # question about the concept will be grounded in.
        concept.summary = payload.summary
    if payload.source_quotes is not None:
        concept.source_quotes = _checked_quotes(store, doc_id, payload.source_quotes)
    store.save_graph(graph)
    return concept


@router.post("/{doc_id}/concepts/{concept_id}/evidence", response_model=EvidenceProposal)
def propose_evidence(doc_id: str, concept_id: str, draft: DraftGraph) -> EvidenceProposal:
    """Re-scan the chapter for passages that explain this concept.

    **Proposes, never applies** (design doc §6): the response is handed to the reviewer, who
    accepts it — whole, in part, or not at all — through the PATCH above. Two reasons this
    isn't a silent write. It's a human-in-the-loop feature, and overwriting the summary
    someone just typed with model output inverts that; and only the reviewer can judge
    whether a passage the model found is about the concept they actually meant.

    Deliberately a separate request from `add_concept`, not a step inside it: the concept is
    already saved by the time this runs, so a failed or empty scan costs nothing and leaves
    the reviewer's own summary standing. `POST .../concepts` stays a fast, LLM-free write.
    """
    store, graph = draft
    concept = _require_concept(graph, concept_id)
    return evidence_finder.find_evidence(_require_chapter(store, doc_id), concept)


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
def add_prereq(doc_id: str, concept_id: str, payload: PrereqPayload, draft: DraftGraph) -> None:
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
        concept.evidence[payload.prereq_id] = _edge_evidence(store, doc_id, concept, prereq)
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
