# Codex Reasoning Switch Repo Review Addendum

## Purpose

This document builds on the earlier `codex_reasoning_switch_plan.md` and updates the implementation guidance based on an actual review of the `local-model-pro` repository.

The main conclusion is:

**The repo already uses the local knowledge database during answer generation.**

So the better path is **not** to build a second retrieval pipeline for reasoning. Instead, extend the existing retrieval and grounded evidence flow so that the user-facing reasoning summary, verbose notes, or debug view are generated from the **same retrieved memory evidence** already used for the final answer.

---

## Executive Recommendation

### Better path than the original generic plan

The previous plan was a generic reasoning-switch design for a typical local model app. It is still structurally useful, but after reviewing this repo, the implementation should be **repo-native**.

### What is better in this repo

Use the existing knowledge-assisted flow rather than inserting a separate generic RAG layer.

That means:

- keep the current memory retrieval path
- keep the current grounded evidence flow
- add reasoning output on top of the existing retrieval/evidence objects
- keep reasoning and answer separate in the UI
- expose retrieval metadata in debug mode

### Why this is better

Because this codebase already has:

- a memory retrieval pipeline
- grounded synthesis objects
- evidence-card construction
- existing WebSocket event flow
- a documented insights-only retrieval policy

So a repo-specific implementation is cleaner, smaller, safer, and more consistent than the original fully-generic adapter-first plan.

---

## Repo Review Findings

### Existing answer grounding already happens

The current server flow already does the following:

1. saves the incoming prompt
2. builds a query plan
3. searches local memory
4. optionally searches the web
5. injects memory/web context into model generation
6. in grounded mode, converts memory results into evidence cards
7. synthesizes a grounded answer from those evidence cards

### Important repo-specific components

These were identified in the repo review:

- `src/local_model_pro/server.py`
  - handles chat, query planning, memory retrieval orchestration, and streaming
- `src/local_model_pro/knowledge_assist.py`
  - contains `KnowledgeAssistService.search_memory()`
  - contains `memory_to_evidence_cards()`
  - contains `generate_grounded_response()`
- `src/local_model_pro/static/app.js`
  - already handles evidence-related UI events
- `README.md`
  - documents the memory-first retrieval behavior and insights-only injection policy

### Most important conclusion

**The answer path is already grounded by the local knowledge database.**

So the real missing feature is not retrieval itself.

The missing feature is:

**a separate, user-facing reasoning layer that is generated from the same retrieved evidence.**

---

## Comparison: Original Plan vs Repo-Aware Plan

## Option A: Original generic reasoning-switch plan

### Summary

Add a generic reasoning mode framework with adapter-based prompting and separate reasoning rendering.

### Pros

- reusable across many local-model apps
- good abstraction for future providers
- clean long-term architecture if the repo becomes more general

### Cons in this repo

- risks duplicating logic that already exists
- may accidentally bypass the current knowledge-assisted path
- may create a second retrieval model instead of reusing the current one
- may require more refactoring than necessary

---

## Option B: Repo-aware reasoning-on-existing-evidence plan

### Summary

Keep the existing retrieval/evidence architecture and add reasoning output directly on top of it.

### Pros

- smallest change to the codebase
- grounded reasoning stays aligned with grounded answer generation
- avoids creating a second retrieval system
- preserves the repo’s current memory-first behavior
- better matches current server and frontend event flow

### Cons

- less generic than the earlier design
- some abstractions may still be useful later if the project grows beyond its current architecture

---

## Recommendation

### Preferred implementation path

**Option B is better for this repo right now.**

Use the existing knowledge-assisted architecture as the source of truth.

Then selectively borrow from the original plan only where useful:

- add `reasoning_mode`
- add separate reasoning UI rendering
- add reasoning/debug event types
- add structured prompt sections where needed

But do **not** replace the current retrieval/evidence pipeline.

---

## Architecture Recommendation

## Current effective flow

```text
user prompt
  -> query planning
  -> search local memory database
  -> optional web retrieval
  -> memory/web context or evidence cards
  -> answer generation
```

## Recommended new flow

```text
user prompt
  -> query planning
  -> search local memory database
  -> optional web retrieval
  -> memory/web context or evidence cards
  -> grounded reasoning summary / verbose notes / debug metadata
  -> grounded final answer
```

### Critical rule

**Reasoning must be built from the same retrieval/evidence set as the answer.**

Not from a separate hidden model pass with different context.

---

## Best Implementation Strategy for This Repo

## 1. Add `reasoning_mode`

Add a request-level setting with values:

- `hidden`
- `summary`
- `verbose`
- `debug`

### Behavior

- `hidden`: current behavior, answer only
- `summary`: show short grounded reasoning summary
- `verbose`: show more detailed grounded notes
- `debug`: show reasoning + retrieval metadata

---

## 2. Reuse `search_memory()` exactly as-is

The local knowledge database path should remain the single retrieval source of truth.

### Requirement

Do not add a second retrieval service.

Use the existing `KnowledgeAssistService.search_memory()` pipeline and continue to respect the repo’s current filtering and scope behavior.

---

## 3. Reuse the current grounded evidence flow

Where the repo currently converts memory results into evidence cards and synthesizes a grounded answer, extend that same path to also produce reasoning text.

### Recommendation

Extend `GroundedResponse` with:

```python
reasoning_text: str = ""
debug_text: str = ""
```

### Why

This allows grounded mode to return:

- final answer
- reasoning summary or notes
- debug information

all from the same evidence objects.

---

## 4. Keep the repo’s insights-only retrieval policy

This repo intentionally does **not** inject full raw transcripts by default.

That is a good design and should remain in place.

### Preserve this policy

Reasoning should be based on:

- memory insights
- allowed quote snippets where the repo already permits them
- evidence cards
- current confidence/conflict state

Not on unrestricted raw transcript dumps.

---

## 5. Add structured reasoning only where needed

In the non-grounded chat path, when `reasoning_mode` is enabled, reuse the current memory/web context assembly and ask the model for:

```xml
<reasoning>...</reasoning>
<answer>...</answer>
```

Then parse and stream those separately.

### Important

Do not re-architect the entire generation path if a small structured-output prompt extension is enough.

---

## 6. Use existing streaming/event architecture

This repo already emits multiple event types through the server/frontend path.

So add new reasoning-specific events rather than replacing the event system.

### Suggested event additions

- `reasoning`
- `debug`

or, if incremental streaming is preferred:

- `reasoning_start`
- `reasoning_token`
- `reasoning_done`

### Recommendation

For simplicity, use full-text reasoning/debug events first.

---

## Specific Repo-Aware Prompt for Codex

```text
Inspect the existing Local Model Pro repository and extend the current knowledge-assisted chat pipeline so the reasoning output is grounded on the same retrieved local memory evidence as the final answer.

Important constraints:
- Reuse the existing retrieval path in KnowledgeAssistService.search_memory().
- Reuse the existing grounded evidence flow in server.py and knowledge_assist.py.
- Do not create a second retrieval system.
- Do not expose raw chain-of-thought.
- Implement a user-facing reasoning summary / verbose notes / debug view.

Implementation requirements:
1. Add a reasoning_mode setting for chat requests with values:
   - hidden
   - summary
   - verbose
   - debug

2. In the normal non-grounded chat path:
   - keep the existing memory/web retrieval flow
   - use the existing memory/web context assembly
   - when reasoning_mode is not hidden, prompt the model to return:
     <reasoning>...</reasoning>
     <answer>...</answer>
   - parse those sections and send reasoning separately from answer

3. In grounded mode:
   - extend GroundedResponse with reasoning_text and debug_text
   - generate reasoning_text from the same evidence_cards used for answer_text
   - the reasoning should summarize which evidence scopes were used, whether support was partial/full, and whether conflicts or exact-request failures occurred
   - do not generate hidden internal thought text

4. Add websocket events for reasoning output and optional debug metadata.

5. In debug mode, include retrieval metadata such as:
   - memory_query
   - number of memory hits
   - top evidence ids or labels
   - whether web evidence was used
   - grounded status/confidence

6. Preserve the repo’s current insights-only retrieval policy. Do not inject raw transcript data beyond the existing quote_text rules.

7. Add tests covering:
   - reasoning output uses retrieved memory evidence
   - grounded reasoning uses the same evidence cards as grounded answer generation
   - no-memory-hit behavior still works
   - debug mode emits retrieval metadata
```

---

## Suggested File-by-File Edits

## `src/local_model_pro/server.py`

### Update request parsing

Add `reasoning_mode` to the incoming chat request handling.

### Update standard chat flow

Where memory/web context is currently assembled for plain chat, add structured reasoning output when `reasoning_mode != hidden`.

### Update grounded flow

When grounded mode returns a `GroundedResponse`, emit:

- reasoning event if present
- debug event if present
- answer event as usual

### Add debug metadata emission

Send retrieval metadata in debug mode using the same event pipeline already used for evidence and plan messages.

---

## `src/local_model_pro/knowledge_assist.py`

### Extend `GroundedResponse`

Add:

```python
reasoning_text: str = ""
debug_text: str = ""
```

### Update `generate_grounded_response()`

Generate a grounded reasoning summary from:

- evidence card count
- support level
- conflicts or ambiguities
- exact/clarify state
- evidence scope summaries

### Keep answer generation logic grounded on same evidence cards

Do not split the reasoning and answer evidence sources.

---

## `src/local_model_pro/static/app.js`

### Add UI state

Track:

- `reasoningMode`
- `reasoningText`
- `debugText`

### Add controls

Add a selector with:

- No reasoning
- Reasoning summary
- Verbose notes
- Debug view

### Add rendering

Render reasoning separately from the answer.

### Add event handling

Handle new server event types for reasoning and debug.

---

## Tests

### Add or extend tests for:

- reasoning mode request handling
- grounded reasoning generation from evidence cards
- non-grounded structured reasoning parsing
- debug retrieval metadata emission
- no-memory-hit graceful behavior

---

## Suggested Reasoning Content Rules

The repo should not expose fake hidden thought.

### Good reasoning output examples

- "Used 3 local memory results from the same scope to answer the request."
- "The retrieved evidence supported the main answer, but did not provide a direct value for the requested exact field."
- "Two evidence entries appear to conflict, so the answer reflects the most recent supported record."
- "No relevant memory results were found, so the answer is based on general model knowledge and should be treated with lower confidence."

### Bad reasoning output examples

- raw internal monologue
- fabricated hidden thoughts
- reasoning that ignores retrieved evidence
- transcript-like dumps of raw memory content

---

## Debug Mode Recommendation

Debug mode should expose retrieval usage without exposing hidden internal thought.

### Suggested debug payload content

- memory query text
- number of retrieved memory hits
- ids or labels of top evidence items
- whether web retrieval was used
- grounded confidence / support status
- whether clarification was needed

This gives transparency while staying aligned with the repo’s current design.

---

## Repo-Aware Implementation Prompt Sequence

Recommended order for Codex:

1. inspect server.py, knowledge_assist.py, static/app.js, and existing tests
2. add `reasoning_mode` request support
3. extend grounded response objects with reasoning/debug text
4. add reasoning generation using existing evidence cards
5. add non-grounded structured reasoning using existing memory/web context
6. add frontend controls and rendering
7. add debug retrieval metadata
8. add tests
9. clean up event naming and state handling

---

## Final Recommendation

### Should this path replace the previous one?

**Yes, for this repository.**

The earlier markdown is still useful as a general design reference, but this repo-aware path is better because it:

- matches the actual codebase
- reuses the knowledge DB path already in place
- preserves the current retrieval policy
- minimizes refactoring
- guarantees reasoning and answer use the same evidence

### Best practical approach

Use the earlier plan for:

- reasoning mode naming
- UI separation of reasoning vs answer
- acceptance criteria
- testing ideas

Use this repo-aware addendum for:

- actual implementation strategy
- file targets
- retrieval grounding rules
- debug retrieval transparency

That combination is the strongest handoff for Codex on this codebase.

