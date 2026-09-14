# Evidence generation for hand-added concepts — design

**Status:** proposed (not yet implemented)
**Scope:** gives a concept added during graph review (`docs/specs/2026-09-12-human-in-the-loop`) the same kind of chapter-grounded textual evidence an extracted concept has, via a targeted LLM re-scan of the source text. Adds `Concept.source_quotes`, one new service (`evidence_finder.py`), one endpoint, one Alembic migration, and a frontend affordance in `ReviewGraphPage`. Does **not** change how `question_generator` or `graph_builder` work.

## 1. Why

A concept the reviewer adds by hand reaches `question_generator` with exactly one evidence passage: the sentence they typed. Measured, not assumed:

```
ORPHAN (no prereqs wired): 1 passage  -> [(s1, target_concept)]
WIRED by hand to limits:   3 passages -> [(s1, target_concept), (s2, prerequisite), (s3, sibling)]
```

An extracted concept arrives with its own chapter-drawn summary, each prerequisite's summary, and the verbatim source quote justifying each dependency. A hand-added one has none of that provenance — nothing ever goes back to the chapter on its behalf. Three consequences:

1. **Thin question sets.** Rules 1 and 4 of `question_generator`'s prompt require every question to be fully answerable from the evidence supplied. One sentence supports `conceptual_correctness` and little else — `conceptual_distinction` needs a contrast the evidence establishes, `enumeration_completeness` a bounded list, `applied_reasoning` a stated mechanism. So a hand-added concept realistically gets one or two questions where an extracted one gets four.
2. **No provenance.** `grounding` for those questions is the reviewer's prose, not the chapter. The "verbatim fidelity is structural" property still holds for how passages are *assembled*, but the passages no longer trace to the source document.
3. **Drift toward neighbours.** Measured in `tests/question_geval`'s check 6 (target focus) on extracted concepts, where the identical imbalance exists — see §9. A thin target beside rich neighbour passages makes the neighbour's question the best-supported one.

Hand-added edges have the same hole: they carry `evidence[prereq_id] = ""` because no source quote exists for a relationship a human asserted, so `source_passages()` skips the `prerequisite_link` passage entirely (correctly — there is nothing to cite).

## 2. What the pass does

One LLM call per added concept, scanning the chapter text for that concept specifically. Two outputs, matching the two things an extracted concept has:

- **`source_quotes`** — verbatim passages from the chapter that explain this concept. New field (§4).
- **a chapter-grounded `summary`** — offered as a replacement for the reviewer's, never silently applied (§6).

Plus, when a prerequisite is wired by hand, the same service fills in the `evidence[prereq_id]` quote justifying that specific dependency — the one thing that would make a hand-drawn edge indistinguishable from an extracted one.

**The chapter may genuinely not discuss the concept.** That is a legitimate reason to add one — the reviewer may be introducing an idea the chapter assumes rather than teaches. The pass must be able to report "found nothing" and leave the reviewer's own summary standing, rather than manufacturing quotes to fill the schema. So the response carries an explicit `found` flag.

## 3. Verbatim fidelity is enforced in code, not asked for

This project has a scar here: `question_generator` spent three rounds of prompt-strengthening failing to stop the model corrupting passages it retyped, and only became reliable when the model stopped retyping them at all (citing `source_ids` instead, assembled in code). `graph_builder` has the same exposure today — `tests/graph_geval` still reports "two edges with paraphrased-not-verbatim evidence quotes."

That trick isn't available here: this pass has to pull text *out* of a document, so the model necessarily reproduces it. The mitigation is verification rather than instruction:

```python
def _verbatim_only(quotes: list[str], chapter: str) -> list[str]:
    """Drop any quote that isn't actually in the chapter, whitespace-normalized.

    The model is asked for verbatim text and mostly complies; graph_geval shows it
    sometimes paraphrases instead. A paraphrase presented as a source quote is worse than
    no quote — it launders invention into provenance — so this discards rather than
    repairs, and the caller reports how many survived.
    """
    haystack = _normalize_ws(chapter)
    return [q for q in quotes if _normalize_ws(q) in haystack]
```

Same normalization as `tests/graph_geval`'s evidence check (whitespace collapsed, em-dash spacing normalized), and ideally the same helper — this is a third copy of that rule, so it should move somewhere shared.

## 4. Data model

```python
class Concept(BaseModel):
    ...
    source_quotes: list[str] = Field(
        default_factory=list,
        description="Verbatim chapter passages explaining this concept, beyond its summary",
    )
```

`concepts.source_quotes` as JSONB, defaulting to `[]`, alongside the existing `depends_on`/`evidence` — nothing queries it independently of a full-graph load, same reasoning as those. One additive Alembic migration with a `server_default` of `'[]'`; every existing row is correct as an empty list, since extracted concepts have none today (§9 is where that changes).

Both `Store` implementations already round-trip the whole `Concept`, so `save_graph`/`get_graph` need only carry the new field.

**This field is deliberately not `summary`.** Folding quotes into the summary would conflate "what this concept is" with "what the chapter says about it," and `source_passages()` would emit one blob instead of separable passages. Keeping them apart means the target concept gets the same shape prerequisites already get — a summary *plus* supporting quotes.

## 5. How it reaches question generation

`source_passages()` grows one loop, and nothing else in `question_generator` changes:

```python
    passages: list[SourcePassage] = [
        {"id": "s1", "role": "target_concept", "concept_name": concept.name, "text": concept.summary}
    ]
    for quote in concept.source_quotes:
        add("target_concept", concept.name, quote)
```

Each quote becomes its own `target_concept`-role passage, so the model can cite them individually by id and `grounding` stays the verbatim join it already is. A concept with three good quotes goes from one passage to four, which is the entire point: rule 4 can now support the question types that one sentence cannot.

## 6. Endpoint and trigger

```
POST /api/graph/{doc_id}/concepts/{concept_id}/evidence  ->  EvidenceProposal
```

Gated by `_draft_graph` like every other editing endpoint, so it is unreachable once a chapter is finalized.

**It proposes; it does not apply.** The response carries the found quotes and a suggested summary, and the reviewer accepts or edits before anything is written — via the `PATCH` and the concept-edit UI that already exist. Two reasons: this is a human-in-the-loop feature, and silently overwriting the summary someone just typed with model output inverts that; and the reviewer is the only one who can judge whether a quote the model found is actually about the concept they meant.

**Triggering:** the UI calls it automatically right after a successful add, so there is no extra click and no way to end up with a thin concept by forgetting one. But it is a *separate request from the add*, which matters for failure: if the re-scan errors or the chapter has nothing, the concept is already saved with the reviewer's summary and nothing is lost. `POST .../concepts` stays a fast, LLM-free write.

A "Find evidence in the chapter" button on the concept row re-runs it on demand — useful after editing the concept's name or summary, which changes what the scan is looking for.

**Prerequisite quotes** reuse the same service from `add_prereq`: when an edge is wired by hand, scan for a sentence justifying that specific dependency and, if one is found verbatim, store it as `evidence[prereq_id]` instead of `""`. Silent and non-blocking — a wired edge with no supporting sentence keeps today's behavior exactly (empty evidence, skipped `prerequisite_link` passage), which is already correct.

## 7. The service

New `backend/app/services/evidence_finder.py`, following `graph_builder.py`'s shape (`claude-haiku-4-5`, `temperature=0`, JSON-schema-constrained). Extraction, not judgment — the same job `graph_builder` already does well, narrowed to one concept.

```python
class EvidenceProposal(TypedDict):
    found: bool
    summary: str          # "" when found is False
    quotes: list[str]     # verbatim; post-verified in code
    dropped: int          # quotes discarded as non-verbatim, for the reviewer to see

def find_evidence(chapter_text: str, concept: Concept) -> EvidenceProposal: ...
def find_edge_evidence(chapter_text: str, concept: Concept, prereq: Concept) -> str | None: ...
```

Prompt requirements worth stating explicitly, since they are where this can go wrong:

- Quote **verbatim and contiguously**; never stitch together sentences from different parts of the chapter into one quote. (Stitching passes a substring check only if the check is per-quote, which is why §3 verifies each quote whole.)
- Return `found: false` rather than the nearest-looking passage. The chapter not covering a concept is an expected outcome, not a failure to work around.
- Prefer passages that *explain* the concept — its mechanism, its purpose, what distinguishes it — over passages that merely mention the term, since rule 4 downstream needs mechanism, not name-drops.
- Do not invent a definition when the chapter only names the concept in passing.

`_extract_raw_*`-style internal seam so a future regression suite can grade the raw proposal before it is folded into a `Concept`.

## 8. Testing

**Free (no API key):**
- `_verbatim_only` unit tests: exact match passes; whitespace and em-dash variants pass; a paraphrase is dropped; a quote stitched from two distant sentences is dropped.
- Endpoint tests in `test_graph_review.py` against a stubbed `evidence_finder`: proposal returned and *not* auto-applied; a failing scan leaves the concept intact with the reviewer's summary; `found: false` proposes nothing; the endpoint 409s on a finalized chapter.
- A `source_passages()` test asserting `source_quotes` become separate `target_concept` passages — currently `question_geval` would be the only thing exercising that, and it is billed.
- Store round-trip for the new field in `test_memory_store.py` / `test_postgres_store.py`.

**Billed:** a `question_geval` case for a concept carrying `source_quotes`, measuring whether the extra passages actually raise type recall and hold target focus. This is the number that says whether the pass was worth building.

**Before building any of it**, run the cheap premise check described in §9 — roughly four calls and a few seconds, against the hypothesis the whole design rests on.

## 9. The generalization — deferred, deliberately

**The same imbalance exists for extracted concepts, and it is measured.** `tests/question_geval`'s check 6 (target focus) fails at **0.86, 4 of 28 at-risk questions off-target**: questions written for one concept whose correct answer is really about a prerequisite or sibling. A `write_ahead_log` question asks how many physical writes a logical write causes — that is its sibling `write_amplification`'s question. A `compaction` question tests segmentation instead.

Every concept that drifts — `write_ahead_log`, `compaction`, `bloom_filter`, `hash_index` — has a 1–2 sentence summary from `graph_builder` sitting beside rich neighbour passages. The read is that rule 4 (only ask what the evidence fully supports) makes the neighbour's question the best-supported one available, so that is what gets written.

**A prompt fix was tried and reverted.** A rule 10 telling the model that prerequisites and siblings are context rather than subject matter moved target focus 0.86 → 0.85 — noise, with the off-target set turning over almost entirely — while knocking evidence basis 0.94 → 0.82, below its own threshold. Same destabilization adding rules 8–9 caused. An instruction about what to *prefer* cannot beat a constraint about what is *possible*.

So the fix is the same as this document's: **give extracted concepts their own `source_quotes`**, populated by `graph_builder` during extraction rather than by a separate re-scan. The field added in §4 is deliberately general enough to carry that.

**Not in this pass**, for two reasons. It changes `graph_builder`'s output shape and prompt, which `tests/graph_geval` grades and which is the one service every other pipeline stage depends on. And the premise deserves a cheap test first:

> Take `write_ahead_log` alone. Generate its questions twice — once with its current summary, once with a thickened one drawn from the source text — and run both through the target-focus judge. Four calls, seconds, pennies. If drift doesn't drop, the thin-evidence hypothesis is wrong and both this document and the follow-on need rethinking.

That probe is the cheapest thing on this page and gates the most work, so it should run first. `tests/diagnoser_geval/probe.py` is the pattern to copy.

## 10. Out of scope

- **Re-scanning on chapter edit.** Chapter text is immutable after upload; nothing can invalidate a quote.
- **Auto-applying proposals.** See §6 — the reviewer accepts.
- **Finding prerequisites for the added concept.** The pass generates *evidence*, not graph structure: it never proposes which concepts the new one should depend on. Wiring stays manual, which keeps the human the authority on structure and keeps this pass a pure extraction job.
- **Backfilling `source_quotes` for existing chapters.** Additive field, empty on every current row; §9 is where extracted concepts start getting them, and only for chapters ingested after that ships.
