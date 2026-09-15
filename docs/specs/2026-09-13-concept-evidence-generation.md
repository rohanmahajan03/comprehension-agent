# Evidence generation for hand-added concepts — design

**Status:** **implemented 2026-09-14.** Built as designed except where the "Built as" notes
below say otherwise. The two pieces deliberately left undone — measuring whether the extra
evidence actually improves questions, and giving *extracted* concepts the same treatment
(§9) — moved to `docs/specs/2026-09-14-concept-evidence-measurement-and-generalization.md`.

**Scope:** gives a concept added during graph review (`docs/specs/2026-09-12-human-in-the-loop`)
the same kind of chapter-grounded textual evidence an extracted concept has, via a targeted
LLM re-scan of the source text. Adds `Concept.source_quotes`, one new service
(`evidence_finder.py`), one endpoint, one Alembic migration, and a frontend affordance in
`ReviewGraphPage`. Does **not** change how `question_generator` or `graph_builder` work.

### What shipped

| | |
|---|---|
| `app/services/evidence_finder.py` | new — `find_evidence()`, `find_edge_evidence()`, `_propose_raw_evidence()` seam |
| `app/services/text_match.py` | new — `normalize_ws()` / `is_verbatim()` / `verbatim_only()`, the verbatim rule, shared |
| `app/models/schemas.py` | `Concept.source_quotes`, `EvidenceProposal` |
| `app/db/models.py` + `alembic/versions/f3a7d12c48be_*` | `concepts.source_quotes` JSONB, `server_default '[]'` |
| `app/routers/graph_edit.py` | `POST .../concepts/{id}/evidence`; `source_quotes` on the PATCH; edge scan in `add_prereq` |
| `app/services/question_generator.py` | `source_passages()` emits each quote as its own passage |
| `app/store/{memory,postgres}_store.py` | carry the new field |
| `frontend/` | `findEvidence()`, the proposal panel, the not-found notice, `EvidenceProposal` type |
| `tests/test_text_match.py`, `tests/test_question_generator.py` | new free suites |
| `tests/test_graph_review.py`, `tests/conftest.py` | endpoint coverage + `stub_evidence_finder` |

Live-checked against the real API and a real Postgres: verbatim quotes for `hash_index` out
of the Case 3 excerpt, an honest `found: false` for a concept that excerpt never teaches, and
a hand-drawn `compaction → append_only_log` edge picking up a real justifying sentence where
it would previously have stored `""`.

## 1. Why

A concept the reviewer adds by hand reaches `question_generator` with exactly one evidence
passage: the sentence they typed. Measured, not assumed:

```
ORPHAN (no prereqs wired): 1 passage  -> [(s1, target_concept)]
WIRED by hand to limits:   3 passages -> [(s1, target_concept), (s2, prerequisite), (s3, sibling)]
```

An extracted concept arrives with its own chapter-drawn summary, each prerequisite's summary,
and the verbatim source quote justifying each dependency. A hand-added one has none of that
provenance — nothing ever goes back to the chapter on its behalf. Three consequences:

1. **Thin question sets.** Rules 1 and 4 of `question_generator`'s prompt require every
   question to be fully answerable from the evidence supplied. One sentence supports
   `conceptual_correctness` and little else — `conceptual_distinction` needs a contrast the
   evidence establishes, `enumeration_completeness` a bounded list, `applied_reasoning` a
   stated mechanism. So a hand-added concept realistically gets one or two questions where an
   extracted one gets four.
2. **No provenance.** `grounding` for those questions is the reviewer's prose, not the
   chapter. The "verbatim fidelity is structural" property still holds for how passages are
   *assembled*, but the passages no longer trace to the source document.
3. **Drift toward neighbours.** Measured in `tests/question_geval`'s check 6 (target focus) on
   extracted concepts, where the identical imbalance exists — see §9. A thin target beside
   rich neighbour passages makes the neighbour's question the best-supported one.

Hand-added edges have the same hole: they carry `evidence[prereq_id] = ""` because no source
quote exists for a relationship a human asserted, so `source_passages()` skips the
`prerequisite_link` passage entirely (correctly — there is nothing to cite).

> **Built as:** 1 and 2 are addressed for hand-added concepts, and the edge hole is closed
> when the chapter supplies a justifying sentence. **3 is not addressed at all** — it is a
> statement about *extracted* concepts, which this pass never touches. Nothing here has moved
> check 6 off 0.86; the follow-on spec is where that gets attempted.

## 2. What the pass does

One LLM call per added concept, scanning the chapter text for that concept specifically. Two
outputs, matching the two things an extracted concept has:

- **`source_quotes`** — verbatim passages from the chapter that explain this concept. New
  field (§4).
- **a chapter-grounded `summary`** — offered as a replacement for the reviewer's, never
  silently applied (§6).

Plus, when a prerequisite is wired by hand, the same service fills in the
`evidence[prereq_id]` quote justifying that specific dependency — the one thing that would
make a hand-drawn edge indistinguishable from an extracted one.

**The chapter may genuinely not discuss the concept.** That is a legitimate reason to add one
— the reviewer may be introducing an idea the chapter assumes rather than teaches. The pass
must be able to report "found nothing" and leave the reviewer's own summary standing, rather
than manufacturing quotes to fill the schema. So the response carries an explicit `found`
flag.

> **Built as:** as described, with one hardening. `found` is **recomputed from the quotes that
> survive verification**, not taken from the model: a proposal whose every quote turned out to
> be a paraphrase has found nothing, whatever it claimed, and returning `found: true` with an
> empty list would be a shape no caller should have to reason about. `_MAX_QUOTES = 4` caps
> how much of the chapter one concept can claim — past that the model pads with passages that
> merely mention the term, which the prompt's rule 2 exists to exclude.

## 3. Verbatim fidelity is enforced in code, not asked for

This project has a scar here: `question_generator` spent three rounds of prompt-strengthening
failing to stop the model corrupting passages it retyped, and only became reliable when the
model stopped retyping them at all (citing `source_ids` instead, assembled in code).
`graph_builder` has the same exposure today — `tests/graph_geval` still reports "two edges
with paraphrased-not-verbatim evidence quotes."

That trick isn't available here: this pass has to pull text *out* of a document, so the model
necessarily reproduces it. The mitigation is verification rather than instruction:

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

Same normalization as `tests/graph_geval`'s evidence check (whitespace collapsed, em-dash
spacing normalized), and ideally the same helper — this is a third copy of that rule, so it
should move somewhere shared.

> **Built as:** `app/services/text_match.py`, and the sharing happened —
> `tests/graph_geval/support.py` deleted its `_normalize_ws` and now calls `is_verbatim()`, so
> the suite grades the extractor against the same definition of "verbatim" production
> enforces. Three differences from the sketch:
>
> - Split into three functions rather than one: `normalize_ws()` (the rule),
>   `is_verbatim(quote, source)` (one quote — what the PATCH and the edge path need), and
>   `verbatim_only(quotes, source)` (the filter, which also dedupes and preserves order).
> - **Normalization is whitespace collapse and nothing else.** "Em-dash spacing normalized"
>   turned out to be a description of what whitespace collapse already achieves for a quote
>   whose line wrapped inside an em-dash clause — not a separate rule. Going further and
>   equating `a — b` with `a—b` would forgive exactly the corruption this project has watched
>   a model produce (`write_amplification`'s em-dash replaced by a stray artifact), so the
>   rule forgives rewrapping and *only* rewrapping.
> - Contiguity, which §3's parenthetical flags as the reason to check each quote whole, is now
>   stated as an invariant in `is_verbatim`'s docstring: a quote stitched from two distant
>   sentences is not a substring of the source, so it fails — but only while quotes are checked
>   whole. `tests/test_text_match.py` pins that case, along with a paraphrase, a dropped middle
>   clause, and an em-dash swapped for a hyphen.

## 4. Data model

```python
class Concept(BaseModel):
    ...
    source_quotes: list[str] = Field(
        default_factory=list,
        description="Verbatim chapter passages explaining this concept, beyond its summary",
    )
```

`concepts.source_quotes` as JSONB, defaulting to `[]`, alongside the existing
`depends_on`/`evidence` — nothing queries it independently of a full-graph load, same
reasoning as those. One additive Alembic migration with a `server_default` of `'[]'`; every
existing row is correct as an empty list, since extracted concepts have none today (§9 is
where that changes).

Both `Store` implementations already round-trip the whole `Concept`, so `save_graph`/`get_graph`
need only carry the new field.

**This field is deliberately not `summary`.** Folding quotes into the summary would conflate
"what this concept is" with "what the chapter says about it," and `source_passages()` would
emit one blob instead of separable passages. Keeping them apart means the target concept gets
the same shape prerequisites already get — a summary *plus* supporting quotes.

> **Built as:** exactly this. Migration `f3a7d12c48be`, `NOT NULL` with `server_default '[]'`
> — safe on a populated table for the same reason `documents.status` was, and verified by
> inserting a row that omits the column and reading back `[]`. Both stores carry the field;
> `test_postgres_store.py`'s JSONB round-trip and a new `TestGraphRoundTrip` in
> `test_memory_store.py` assert an em-dash-bearing quote survives byte-identical, which
> matters more here than for the other two JSONB columns: this field's entire contract is that
> `is_verbatim()` will still succeed against it later.

## 5. How it reaches question generation

`source_passages()` grows one loop, and nothing else in `question_generator` changes:

```python
    passages: list[SourcePassage] = [
        {"id": "s1", "role": "target_concept", "concept_name": concept.name, "text": concept.summary}
    ]
    for quote in concept.source_quotes:
        add("target_concept", concept.name, quote)
```

Each quote becomes its own `target_concept`-role passage, so the model can cite them
individually by id and `grounding` stays the verbatim join it already is. A concept with three
good quotes goes from one passage to four, which is the entire point: rule 4 can now support
the question types that one sentence cannot.

> **Built as:** exactly this, placed before the prerequisite loop so passage ids stay
> contiguous, and with no change to `_SYSTEM_PROMPT` — the `target_concept` role already
> reads correctly when several passages carry it, and this prompt has a documented history of
> destabilizing when rules are added. `tests/test_question_generator.py` is new and pins the
> passage-assembly rules directly, which until now only the billed `question_geval` exercised.
>
> Worth knowing for the follow-on: `question_geval`'s `_target_focus_context()` already folds
> *every* `target_concept`-role passage into the judge's "target" blob and everything else into
> "neighbours", so `source_quotes` reach check 6 correctly with no suite change.

## 6. Endpoint and trigger

```
POST /api/graph/{doc_id}/concepts/{concept_id}/evidence  ->  EvidenceProposal
```

Gated by `_draft_graph` like every other editing endpoint, so it is unreachable once a chapter
is finalized.

**It proposes; it does not apply.** The response carries the found quotes and a suggested
summary, and the reviewer accepts or edits before anything is written — via the `PATCH` and
the concept-edit UI that already exist. Two reasons: this is a human-in-the-loop feature, and
silently overwriting the summary someone just typed with model output inverts that; and the
reviewer is the only one who can judge whether a quote the model found is actually about the
concept they meant.

**Triggering:** the UI calls it automatically right after a successful add, so there is no
extra click and no way to end up with a thin concept by forgetting one. But it is a *separate
request from the add*, which matters for failure: if the re-scan errors or the chapter has
nothing, the concept is already saved with the reviewer's summary and nothing is lost.
`POST .../concepts` stays a fast, LLM-free write.

A "Find evidence in the chapter" button on the concept row re-runs it on demand — useful after
editing the concept's name or summary, which changes what the scan is looking for.

**Prerequisite quotes** reuse the same service from `add_prereq`: when an edge is wired by
hand, scan for a sentence justifying that specific dependency and, if one is found verbatim,
store it as `evidence[prereq_id]` instead of `""`. Silent and non-blocking — a wired edge with
no supporting sentence keeps today's behavior exactly (empty evidence, skipped
`prerequisite_link` passage), which is already correct.

> **Built as:** all of it, plus three things this section did not specify:
>
> - **How acceptance is expressed.** `ConceptEditPayload` gained `source_quotes: list[str] | None`,
>   which **replaces the whole list** — that is what makes accepting *part* of a proposal
>   expressible (untick a quote, PATCH what's left). `None` means "leave the quotes alone",
>   so every pre-existing edit path is unchanged and cannot wipe accepted evidence.
> - **The PATCH re-checks every quote against the chapter** and 422s otherwise. `evidence_finder`
>   is not the only way into the field — this endpoint takes a list from a client, and a
>   reviewer "fixing" a typo in a proposed quote turns provenance back into prose. Enforcing
>   the invariant at the write is what lets everything downstream treat `source_quotes` as
>   chapter text without re-checking.
> - **A user-facing not-found notice**, which this document specified only as a flag on the
>   wire. `ReviewGraphPage` says *"Could not find evidence for this concept in the chapter"*,
>   names the consequence (its questions come from the summary alone) and both legitimate
>   responses — reword to match the chapter's own terms, or leave it, because the chapter may
>   assume the idea rather than teach it. It is **transient component state, not stored**: an
>   empty `source_quotes` cannot distinguish "we looked and found nothing" from "nobody has
>   looked", and the reviewer needs those told apart. When quotes were discarded as
>   non-verbatim the notice says so too, which separates "the chapter doesn't cover this" from
>   "the model paraphrased everything it returned".
>
> The edge scan is wrapped in a bare `except Exception` that logs and returns `""`: failing the
> edit would lose the reviewer's structural work over a missing quote, so a broken scan lands
> on exactly the pre-scan behavior. The panel stays open when a save is rejected — a 422 on a
> non-verbatim quote has to leave the reviewer something to fix.

## 7. The service

New `backend/app/services/evidence_finder.py`, following `graph_builder.py`'s shape
(`claude-haiku-4-5`, `temperature=0`, JSON-schema-constrained). Extraction, not judgment — the
same job `graph_builder` already does well, narrowed to one concept.

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

- Quote **verbatim and contiguously**; never stitch together sentences from different parts of
  the chapter into one quote. (Stitching passes a substring check only if the check is
  per-quote, which is why §3 verifies each quote whole.)
- Return `found: false` rather than the nearest-looking passage. The chapter not covering a
  concept is an expected outcome, not a failure to work around.
- Prefer passages that *explain* the concept — its mechanism, its purpose, what distinguishes
  it — over passages that merely mention the term, since rule 4 downstream needs mechanism,
  not name-drops.
- Do not invent a definition when the chapter only names the concept in passing.

`_extract_raw_*`-style internal seam so a future regression suite can grade the raw proposal
before it is folded into a `Concept`.

> **Built as:** signatures as written; all four prompt requirements became numbered rules
> (1–2 verbatim + contiguous, 3–5 the `found: false` and no-invention rules, 6 the `_MAX_QUOTES`
> cap, 7–8 how to write the summary). Two shape changes:
>
> - `EvidenceProposal` is a **Pydantic model in `schemas.py`**, not a `TypedDict` in the
>   service. It is a service return type *and* an API response body the frontend mirrors by
>   hand — exactly `DiagnosisResult`'s situation, so it lives where `DiagnosisResult` lives.
>   The raw `TypedDict` still exists as `RawEvidenceProposal`, which is what the seam returns.
> - The seam is `_propose_raw_evidence()`, matching `_extract_raw_graph()` /
>   `_generate_raw_for_concept()`. It returns the model's answer **before** verification, which
>   is the shape a suite needs to tell "quoted badly" apart from "found nothing" — two very
>   different failures that `find_evidence()` deliberately collapses into one `found: false`.
>
> One prompt rule was added that this section didn't anticipate, and it earns its place: rule 8
> tells the model the human's summary **identifies which concept is meant but is not evidence**
> — it may be vague or wrong, and the job is to report what the chapter says rather than
> confirm what the summary claims. Without it the pass risks laundering the reviewer's guess
> back as chapter provenance, which is the exact failure mode §3 is built to prevent.

## 8. Testing

**Free (no API key):**
- `_verbatim_only` unit tests: exact match passes; whitespace and em-dash variants pass; a
  paraphrase is dropped; a quote stitched from two distant sentences is dropped.
- Endpoint tests in `test_graph_review.py` against a stubbed `evidence_finder`: proposal
  returned and *not* auto-applied; a failing scan leaves the concept intact with the reviewer's
  summary; `found: false` proposes nothing; the endpoint 409s on a finalized chapter.
- A `source_passages()` test asserting `source_quotes` become separate `target_concept`
  passages — currently `question_geval` would be the only thing exercising that, and it is
  billed.
- Store round-trip for the new field in `test_memory_store.py` / `test_postgres_store.py`.

**Billed:** a `question_geval` case for a concept carrying `source_quotes`, measuring whether
the extra passages actually raise type recall and hold target focus. This is the number that
says whether the pass was worth building.

**Before building any of it**, run the cheap premise check described in §9 — roughly four calls
and a few seconds, against the hypothesis the whole design rests on.

> **Built as:** every free item, and then some. `tests/test_text_match.py` (13 tests) and
> `tests/test_question_generator.py` (4) are new files; `test_graph_review.py` grew 12 tests
> covering the four listed cases plus partial acceptance, the omitted-field case (an edit that
> doesn't send `source_quotes` must not wipe them), the non-verbatim 422, a rewrapped quote
> being accepted, and a failed *edge* scan still storing the edge. `stub_evidence_finder` in
> `tests/conftest.py` calls a sentence evidence for a concept when it names that concept — crude,
> but it exercises the real branch structure rather than hard-coding an outcome, so whether a
> scan finds anything follows from the chapter text a test uploads.
>
> **The billed item was not built**, and neither was the §9 probe that this section says gates
> everything. Both moved to the follow-on spec, which sequences them: the probe first, the
> measurement second, the generalization only if the first two say so. Building the mechanism
> before measuring it was a deliberate call, defensible because the 1-passage floor for
> hand-added concepts is measured (§1) rather than hypothesized — unlike §9's drift claim,
> which genuinely rests on an untested premise. It does mean **nobody has yet shown that a
> concept with `source_quotes` gets better questions than one without.**

## 9. The generalization — deferred, deliberately

> **Superseded by `docs/specs/2026-09-14-concept-evidence-measurement-and-generalization.md`,**
> which carries this analysis forward with a sequence for acting on it. Kept here because the
> measurement below is the reason `Concept.source_quotes` is shaped generally rather than as a
> hand-added-concepts-only field, and because the reverted prompt fix is the kind of thing worth
> not re-attempting.

**The same imbalance exists for extracted concepts, and it is measured.**
`tests/question_geval`'s check 6 (target focus) fails at **0.86, 4 of 28 at-risk questions
off-target**: questions written for one concept whose correct answer is really about a
prerequisite or sibling. A `write_ahead_log` question asks how many physical writes a logical
write causes — that is its sibling `write_amplification`'s question. A `compaction` question
tests segmentation instead.

Every concept that drifts — `write_ahead_log`, `compaction`, `bloom_filter`, `hash_index` —
has a 1–2 sentence summary from `graph_builder` sitting beside rich neighbour passages. The
read is that rule 4 (only ask what the evidence fully supports) makes the neighbour's question
the best-supported one available, so that is what gets written.

**A prompt fix was tried and reverted.** A rule 10 telling the model that prerequisites and
siblings are context rather than subject matter moved target focus 0.86 → 0.85 — noise, with
the off-target set turning over almost entirely — while knocking evidence basis 0.94 → 0.82,
below its own threshold. Same destabilization adding rules 8–9 caused. An instruction about
what to *prefer* cannot beat a constraint about what is *possible*.

So the fix is the same as this document's: **give extracted concepts their own `source_quotes`**,
populated by `graph_builder` during extraction rather than by a separate re-scan. The field
added in §4 is deliberately general enough to carry that.

**Not in this pass**, for two reasons. It changes `graph_builder`'s output shape and prompt,
which `tests/graph_geval` grades and which is the one service every other pipeline stage
depends on. And the premise deserves a cheap test first:

> Take `write_ahead_log` alone. Generate its questions twice — once with its current summary,
> once with a thickened one drawn from the source text — and run both through the target-focus
> judge. Four calls, seconds, pennies. If drift doesn't drop, the thin-evidence hypothesis is
> wrong and both this document and the follow-on need rethinking.

That probe is the cheapest thing on this page and gates the most work, so it should run first.
`tests/diagnoser_geval/probe.py` is the pattern to copy.

## 10. Out of scope

- **Re-scanning on chapter edit.** Chapter text is immutable after upload; nothing can
  invalidate a quote.
- **Auto-applying proposals.** See §6 — the reviewer accepts.
- **Finding prerequisites for the added concept.** The pass generates *evidence*, not graph
  structure: it never proposes which concepts the new one should depend on. Wiring stays
  manual, which keeps the human the authority on structure and keeps this pass a pure
  extraction job.
- **Backfilling `source_quotes` for existing chapters.** Additive field, empty on every current
  row; §9 is where extracted concepts start getting them, and only for chapters ingested after
  that ships.

> **Still accurate, all four.** The last one is now the follow-on spec's call to make: once
> `graph_builder` fills `source_quotes` at extraction time, a chapter ingested before that
> ships is permanently thinner than one ingested after, and that document decides whether
> that's acceptable or worth a backfill path.
