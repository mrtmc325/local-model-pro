# Codex Reasoning Switch Plan

## Objective

Build a reasoning visibility switch for local/static models in `local-model-pro` that supports:

- `hidden`
- `summary`
- `verbose`
- `debug`

The feature must:

- keep the final answer separate from reasoning
- avoid claiming access to true hidden chain-of-thought
- degrade gracefully for unsupported models
- reuse existing local inference plumbing
- stream typed events to the frontend

---

## Primary Codex Instruction

```text
You are modifying an existing local model chat application repository.

Your task is to add a reasoning visibility switch for local/static models with minimal invasive changes.

Important product rules:
- Do NOT claim access to true hidden chain-of-thought.
- Treat reasoning as a visible reasoning summary / verbose notes / debug view feature.
- Preserve existing behavior for answer-only mode.
- Reuse the project’s existing model provider, configuration, request pipeline, and chat flow whenever possible.
- Prefer extending existing files over creating duplicate chat stacks.
- Prefer TypeScript-safe changes over any.
- Preserve current styling and UX conventions already used in the repo.

Required reasoning modes:
- hidden
- summary
- verbose
- debug

Expected behavior:
- hidden: show final answer only
- summary: show concise reasoning summary separately from answer
- verbose: show detailed reasoning notes separately from answer
- debug: show concise reasoning plus debug metadata

Implementation requirements:
1. Inspect the repo first.
2. Identify existing frontend chat controls, frontend chat response rendering, shared types if present, backend chat route, and local model inference code.
3. Extend the request/response contract to support reasoningMode and typed stream events.
4. Add model capability resolution and downgrade logic.
5. Add adapter-based prompting for local models.
6. Stream typed events for thinking, answer, meta, error, and done.
7. Render reasoning in a separate panel from answer.
8. Show the actual routed reasoning mode returned by the backend.
9. Add tests.
10. Keep edits small, natural, and consistent with the project’s code style.

Do not stop after repo inspection. Implement the full feature end to end.
```

---

## Repo Discovery Prompt

```text
Inspect this repository and produce a short implementation map for a reasoning visibility switch feature.

Find and report:
1. Where shared chat request/response types live
2. Where the backend chat endpoint is implemented
3. Where local model inference is performed
4. Where the frontend model selector / controls live
5. Where the frontend renders assistant responses
6. Whether streaming is already implemented, and if so how
7. Which framework is used for frontend and backend
8. Which local model provider(s) are already supported

Then choose the smallest-change implementation plan that adds:
- reasoningMode in requests
- capability-based mode downgrade
- typed streaming chunks
- separate reasoning and answer rendering
- tests

After reporting the map, immediately implement the feature in the most natural files.
```

---

## Main Implementation Prompt

```text
Implement a reasoning visibility switch for local/static models in this repository.

Goal:
Users can choose how much reasoning to see without pretending the app exposes true hidden chain-of-thought.

Reasoning modes:
- hidden
- summary
- verbose
- debug

Behavior:
- hidden: final answer only
- summary: concise reasoning summary in a separate panel
- verbose: detailed reasoning notes in a separate panel
- debug: concise reasoning plus debug notes / metadata

Requirements:
1. Extend the existing chat request type to accept reasoningMode.
2. Add or extend the chat response streaming format to emit typed events:
   - meta
   - thinking
   - answer
   - error
   - done
3. Add backend model capabilities:
   - supportsStreaming
   - supportsReasoningSummary
   - supportsVerboseReasoning
   - supportsSystemPrompt
4. Add resolveReasoningMode() downgrade rules:
   - verbose -> summary if verbose unsupported
   - summary/verbose -> hidden if reasoning summaries unsupported
   - debug remains debug but may only include meta if structured reasoning unsupported
5. Add a ModelAdapter abstraction with:
   - buildPrompt(messages, reasoningMode)
   - parseOutput(raw)
   - optional requiresTwoPass(reasoningMode)
6. Implement a generic adapter for local models that asks for:
   - <thinking>...</thinking>
   - <answer>...</answer>
   - optional <debug>...</debug>
7. Update the current backend chat route to:
   - resolve the actual mode
   - emit meta first
   - run inference
   - emit thinking separately from answer
   - emit done at the end
8. Update the frontend to:
   - add a reasoning mode dropdown near existing model/chat controls
   - persist the chosen mode in localStorage
   - send reasoningMode with each request
   - render reasoning separately from answer
   - show the actual routedReasoningMode returned by the backend
9. Add a fallback two-pass mode for models that ignore structured tags:
   - first pass generates answer
   - second pass generates reasoning summary
10. Add tests for:
   - reasoning mode downgrade
   - adapter output parsing
   - frontend stream chunk handling

Constraints:
- Use the repo’s existing inference/provider code and configuration.
- Do not create a second independent chat pipeline unless absolutely necessary.
- Keep current answer rendering behavior for hidden mode.
- Use labels like:
  - No reasoning
  - Reasoning summary
  - Verbose notes
  - Debug view
- Do not use labels like:
  - Chain of Thought
  - Internal Thoughts
  - Raw Thoughts

Please inspect existing files first, then apply the changes directly.
```

---

## Strict File-Targeted Prompt

```text
Implement the reasoning visibility switch by modifying the smallest number of existing files possible.

Preferred file responsibilities:
- shared types: extend existing chat request/response types
- backend chat route: add reasoningMode handling and typed streaming events
- backend model layer: add capabilities, resolveReasoningMode, and adapter parsing
- frontend controls: add reasoning dropdown
- frontend response view: add separate reasoning panel
- tests: add focused coverage only for the new feature

Do not create duplicate routing, duplicate chat containers, or duplicate provider code.
Do not refactor unrelated parts of the application.
Keep all edits tightly scoped to the reasoning feature.
```

---

## Shared Data Contracts

### Reasoning mode

```ts
export type ReasoningMode = "hidden" | "summary" | "verbose" | "debug";
```

### Chat message

```ts
export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}
```

### Chat request

```ts
export interface ChatRequest {
  model: string;
  messages: ChatMessage[];
  reasoningMode?: ReasoningMode;
  stream?: boolean;
  temperature?: number;
  maxTokens?: number;
}
```

### Stream chunks

```ts
export interface ChatChunk {
  type: "thinking" | "answer" | "meta" | "error" | "done";
  content?: string;
  meta?: {
    model?: string;
    provider?: string;
    routedReasoningMode?: ReasoningMode;
    promptTokens?: number;
    completionTokens?: number;
    latencyMs?: number;
  };
  error?: string;
}
```

### Model capabilities

```ts
export interface ReasoningCapabilities {
  supportsStreaming: boolean;
  supportsReasoningSummary: boolean;
  supportsVerboseReasoning: boolean;
  supportsSystemPrompt: boolean;
}
```

---

## Example Capability Registry Data

```ts
export const MODEL_CAPABILITIES: Record<string, ReasoningCapabilities> = {
  "deepseek-r1-distill": {
    supportsStreaming: true,
    supportsReasoningSummary: true,
    supportsVerboseReasoning: true,
    supportsSystemPrompt: true,
  },
  "llama3.1": {
    supportsStreaming: true,
    supportsReasoningSummary: true,
    supportsVerboseReasoning: false,
    supportsSystemPrompt: true,
  },
  "mistral": {
    supportsStreaming: true,
    supportsReasoningSummary: true,
    supportsVerboseReasoning: false,
    supportsSystemPrompt: true,
  },
  "qwen2.5": {
    supportsStreaming: true,
    supportsReasoningSummary: true,
    supportsVerboseReasoning: false,
    supportsSystemPrompt: true,
  },
  "generic-local": {
    supportsStreaming: true,
    supportsReasoningSummary: false,
    supportsVerboseReasoning: false,
    supportsSystemPrompt: true,
  },
};
```

---

## Capability Resolution Logic Prompt

```text
Add model capability resolution for reasoning modes.

Implement:
- a ReasoningCapabilities type
- a model capability registry
- getModelCapabilities(model)
- resolveReasoningMode(requested, caps)

Rules:
- hidden always resolves to hidden
- summary resolves to summary if summary supported, else hidden
- verbose resolves to verbose if supported, else summary if summary supported, else hidden
- debug resolves to debug, but if structured reasoning is unsupported it may emit only meta/debug info and no reasoning content

Use this logic in the backend immediately before inference starts and return the final routedReasoningMode to the frontend in meta events.
```

---

## Model Adapter Prompt

```text
Add a ModelAdapter abstraction for local model output shaping.

Requirements:
- buildPrompt(messages, reasoningMode)
- parseOutput(raw)
- optional requiresTwoPass(reasoningMode)

Implement a GenericLocalAdapter that:
- asks the model to return <answer>...</answer>
- optionally asks the model to return <thinking>...</thinking>
- optionally asks the model to return <debug>...</debug>
- parses those sections safely
- falls back to raw output as answer if tags are missing

Do not force a repo-wide refactor. Introduce the abstraction in the smallest way that fits the current inference pipeline.
```

---

## Generic Adapter Prompt Templates

### Hidden mode system prompt

```text
You are a local inference assistant.
Return the final response clearly and directly.
Output only the final response.
Do not include reasoning sections or XML tags.
```

### Summary mode system prompt

```text
You are a local inference assistant.
Return your output using these exact sections:

<thinking>
A concise reasoning summary with at most 6 short bullets or short paragraphs.
Do not claim access to hidden thoughts.
Only summarize the visible reasoning process, assumptions, and constraints.
</thinking>

<answer>
The final answer for the user.
</answer>

Always include <answer>.
Keep <thinking> concise and useful.
```

### Verbose mode system prompt

```text
You are a local inference assistant.
Return your output using these exact sections:

<thinking>
Detailed reasoning notes explaining how you approached the answer.
Do not claim access to hidden thoughts.
Describe visible reasoning steps, assumptions, tradeoffs, and constraints.
</thinking>

<answer>
The final answer for the user.
</answer>

Always include <answer>.
Keep the reasoning readable and structured.
```

### Debug mode system prompt

```text
You are a local inference assistant.
Return your output using these exact sections:

<thinking>
A concise reasoning summary describing the visible approach, assumptions, and constraints.
Do not claim access to hidden thoughts.
</thinking>

<debug>
Include brief debug notes such as ambiguities, assumptions, format choices, and confidence.
Do not include hidden internal thoughts.
</debug>

<answer>
The final answer for the user.
</answer>

Always include <answer>.
Keep all sections concise and structured.
```

---

## Two-Pass Fallback Prompt Data

### First pass prompt

```text
Answer the user directly and clearly.
Do not include reasoning sections.
Provide only the answer.
```

### Second pass prompt

```text
Summarize how the answer was derived.
Do not claim access to hidden thoughts.
Describe only visible steps, assumptions, tradeoffs, and constraints.
Return a concise reasoning summary suitable for a user-facing reasoning panel.
```

### Codex prompt for fallback implementation

```text
Add a two-pass fallback for models that do not reliably follow structured output tags.

Fallback behavior:
- pass 1: generate final answer only
- pass 2: generate concise reasoning summary based on the original conversation and the produced answer

Use the fallback only when:
- the selected adapter says it is needed, or
- tagged output parsing fails repeatedly, or
- the model family is known to ignore structured section formatting

Keep the fallback optional and model-aware.
```

---

## Backend Route Prompt

```text
Update the existing backend chat route to support typed reasoning stream events.

Requirements:
- accept reasoningMode in the incoming request
- resolve actual mode using model capabilities
- emit an initial meta event with:
  - model
  - provider
  - routedReasoningMode
- perform inference using the adapter
- emit thinking content separately from answer content
- emit final meta with latency if available
- emit done at the end
- emit error if inference fails

Do not replace the current provider integration. Reuse it.
If the current route already streams, adapt it to stream typed JSON events instead of mixing everything together.
```

---

## Frontend Control Prompt

```text
Update the frontend chat controls to add a reasoning visibility selector.

Requirements:
- add a dropdown near the existing model/chat controls
- options:
  - No reasoning
  - Reasoning summary
  - Verbose notes
  - Debug view
- store the selected value in localStorage
- initialize the selector from localStorage on load
- send the selected reasoningMode with each chat request
- preserve existing control styling and layout conventions
```

---

## Frontend Stream Handling Prompt

```text
Update the frontend chat streaming handler to support typed events.

Requirements:
- parse SSE JSON events with types:
  - meta
  - thinking
  - answer
  - error
  - done
- append thinking content only to reasoning state
- append answer content only to answer state
- update a routedReasoningMode state value from meta events
- preserve existing error handling and request lifecycle behavior
- reset thinking and answer state for each new request
```

---

## Frontend Rendering Prompt

```text
Update the assistant response rendering so reasoning and answer are displayed separately.

Requirements:
- if reasoningMode is hidden, render only the answer area
- if reasoningMode is summary, verbose, or debug, render a separate reasoning panel next to or above the answer
- add a small badge that shows the actual routed mode used by the backend, e.g. "Mode used: summary"
- do not mix reasoning text into the answer container
- preserve existing markdown or rich text rendering for the answer if the app already supports it
```

---

## Local Storage Data

Use this exactly or adapt into current storage helpers.

```ts
const STORAGE_KEY = "local-model-pro.reasoningMode";
```

Valid values:

- `hidden`
- `summary`
- `verbose`
- `debug`

Default:

- `summary`

Reason for default:

- useful without overwhelming
- safer than assuming verbose
- more informative than hidden for users testing local models

---

## Example API Request Payloads

### Hidden

```json
{
  "model": "llama3.1",
  "messages": [
    { "role": "user", "content": "Explain TLS simply." }
  ],
  "reasoningMode": "hidden",
  "stream": true,
  "temperature": 0.4,
  "maxTokens": 512
}
```

### Summary

```json
{
  "model": "llama3.1",
  "messages": [
    { "role": "user", "content": "Explain TLS simply." }
  ],
  "reasoningMode": "summary",
  "stream": true
}
```

### Verbose

```json
{
  "model": "deepseek-r1-distill",
  "messages": [
    { "role": "user", "content": "Compare REST and GraphQL for an internal API." }
  ],
  "reasoningMode": "verbose",
  "stream": true
}
```

### Debug

```json
{
  "model": "generic-local",
  "messages": [
    { "role": "user", "content": "Design a small CLI parser." }
  ],
  "reasoningMode": "debug",
  "stream": true
}
```

---

## Example SSE Stream Data

### Summary success path

```text
data: {"type":"meta","meta":{"model":"llama3.1","provider":"local","routedReasoningMode":"summary"}}

data: {"type":"thinking","content":"- TLS encrypts data between your browser and a server.\n- It also helps verify you are talking to the right server.\n- It prevents others on the network from easily reading or altering traffic."}

data: {"type":"answer","content":"TLS is a security protocol used to protect data sent over a network. It encrypts the connection, helps confirm the server’s identity, and reduces the risk of tampering."}

data: {"type":"meta","meta":{"model":"llama3.1","provider":"local","routedReasoningMode":"summary","latencyMs":842}}

data: {"type":"done"}
```

### Verbose downgraded to summary

```text
data: {"type":"meta","meta":{"model":"llama3.1","provider":"local","routedReasoningMode":"summary"}}

data: {"type":"thinking","content":"Compared requested mode against model capabilities. Verbose notes unsupported, so reasoning summary was used instead.\n\nMain comparison points:\n- schema flexibility\n- caching simplicity\n- over-fetching and under-fetching\n- team complexity"}

data: {"type":"answer","content":"For an internal API, REST is often simpler to operate and cache, while GraphQL is better when clients need flexible queries across many related resources..."}

data: {"type":"done"}
```

### Debug with no reasoning support

```text
data: {"type":"meta","meta":{"model":"generic-local","provider":"local","routedReasoningMode":"debug"}}

data: {"type":"thinking","content":"[debug]\nStructured reasoning not supported for this model. Showing debug metadata only."}

data: {"type":"answer","content":"A small CLI parser can be built with a command registry, argument tokenizer, flag parser, and help renderer..."}

data: {"type":"done"}
```

---

## Example Parser Test Inputs

### Input 1

```text
<thinking>
Step 1
Step 2
</thinking>
<answer>
Hello world
</answer>
```

Expected:

- `thinking = "Step 1\nStep 2"`
- `answer = "Hello world"`

### Input 2

```text
<answer>Only answer available</answer>
```

Expected:

- `thinking = undefined`
- `answer = "Only answer available"`

### Input 3

```text
This model ignored the tags and just returned plain text.
```

Expected:

- `answer = full raw output`
- `thinking = undefined`

### Input 4

```text
<thinking>Reasoning summary</thinking>
<debug>assumption: user wants a TS example</debug>
<answer>Use a discriminated union.</answer>
```

Expected:

- `thinking = "Reasoning summary"`
- `debug = "assumption: user wants a TS example"`
- `answer = "Use a discriminated union."`

---

## Acceptance Criteria

```text
Acceptance criteria:

Backend:
- Chat request accepts reasoningMode
- Model capability resolution exists and is used before inference
- The backend returns routedReasoningMode in meta events
- The backend emits typed events: meta, thinking, answer, error, done
- Missing tagged sections do not break answer rendering
- Hidden mode still behaves like answer-only mode
- Two-pass fallback is available for models that ignore structured output

Frontend:
- A reasoning mode dropdown is visible near existing chat controls
- The selected mode is persisted in localStorage
- reasoningMode is sent with each request
- Reasoning is rendered in a separate panel from answer
- The UI shows the actual routed mode used by the backend
- Hidden mode renders only the answer panel

Tests:
- Mode downgrade behavior is covered
- Tagged output parsing is covered
- Stream event handling is covered

Product:
- The feature is not labeled as true chain-of-thought
- Labels use reasoning summary / verbose notes / debug view language
```

---

## Focused Test Prompt

```text
Add focused tests for the reasoning visibility switch.

Required tests:
1. resolveReasoningMode:
   - hidden stays hidden
   - summary -> hidden when summary unsupported
   - verbose -> summary when verbose unsupported but summary supported
   - verbose -> hidden when neither verbose nor summary supported
2. GenericLocalAdapter.parseOutput:
   - extracts thinking and answer
   - extracts debug if present
   - falls back to raw output as answer when tags are missing
3. Frontend stream handling:
   - thinking chunks append only to reasoning state
   - answer chunks append only to answer state
   - meta updates routedReasoningMode
   - hidden mode still allows normal answer rendering

Keep tests small and aligned with the repo’s existing test framework.
```

---

## Cleanup / Hardening Prompt

```text
Review the implemented reasoning visibility switch and harden it.

Check for:
- duplicated chat request types
- duplicated streaming logic
- duplicated provider calls
- reasoning text accidentally mixed into answer rendering
- unsafe any usage where types should be explicit
- mode downgrade inconsistencies between backend and frontend
- parser edge cases when tags are missing or malformed
- stale state not being reset between requests
- localStorage value validation

Then make minimal fixes only where needed.
```

---

## PR Description Prompt

```text
Write a concise PR description for the reasoning visibility switch feature.

Include:
- what the feature does
- why it avoids claiming true hidden chain-of-thought
- backend changes
- frontend changes
- fallback behavior
- tests added
- any model limitations or known follow-ups
```

---

## Human Review Checklist

Check these after Codex finishes:

- Answer-only mode still works exactly as before
- Reasoning does not appear inside the answer panel
- Mode used badge reflects backend downgrade
- Parser failure still shows an answer
- Existing provider config still works
- No unnecessary large refactor happened
- New labels do not say “chain of thought”

---

## One-Shot End-to-End Mega Prompt

```text
Inspect this repository and implement a reasoning visibility switch for local/static models end to end.

Product goal:
Allow users to choose how much reasoning they see for local model responses without claiming access to true hidden chain-of-thought.

Reasoning modes:
- hidden
- summary
- verbose
- debug

Required UX:
- Add a dropdown near the current model/chat controls with labels:
  - No reasoning
  - Reasoning summary
  - Verbose notes
  - Debug view
- Persist the selected mode in localStorage
- Send reasoningMode with each chat request
- Render reasoning in a separate panel from the answer
- Show a badge with the actual routed mode used by the backend

Required backend:
- Extend the existing chat request contract to accept reasoningMode
- Add model capability resolution with:
  - supportsStreaming
  - supportsReasoningSummary
  - supportsVerboseReasoning
  - supportsSystemPrompt
- Implement resolveReasoningMode with downgrade behavior:
  - hidden -> hidden
  - summary -> summary if supported else hidden
  - verbose -> verbose if supported else summary if supported else hidden
  - debug -> debug, but if structured reasoning unsupported it may show meta/debug only
- Add a ModelAdapter abstraction with:
  - buildPrompt(messages, reasoningMode)
  - parseOutput(raw)
  - optional requiresTwoPass(reasoningMode)
- Implement a GenericLocalAdapter that requests:
  - <thinking>...</thinking>
  - <answer>...</answer>
  - optional <debug>...</debug>
- Parse those sections safely
- Fall back to raw text as answer if tags are missing
- Update the existing chat route to emit SSE JSON events with types:
  - meta
  - thinking
  - answer
  - error
  - done
- Emit routedReasoningMode in meta
- Reuse the existing local model provider integration rather than replacing it
- Add an optional two-pass fallback for models that do not reliably follow tagged output format:
  - pass 1: answer only
  - pass 2: concise reasoning summary based on the conversation and answer

Required data contracts:
- ReasoningMode = "hidden" | "summary" | "verbose" | "debug"
- ChatRequest contains:
  - model
  - messages
  - reasoningMode?
  - stream?
  - temperature?
  - maxTokens?
- Stream chunk type contains:
  - type: "thinking" | "answer" | "meta" | "error" | "done"
  - content?
  - meta?
  - error?

Prompting rules:
- Do not label the feature as true chain-of-thought
- Do not use labels such as:
  - Chain of Thought
  - Internal Thoughts
  - Raw Thoughts
- Use reasoning summary / verbose notes / debug view language
- Reasoning content must be user-facing summaries or notes, not claims of hidden internal thoughts

Testing requirements:
- Add tests for mode downgrade behavior
- Add tests for tagged output parsing
- Add tests for frontend stream chunk handling

Implementation style:
- Inspect the repo first
- Modify the smallest natural set of existing files
- Do not duplicate the chat stack
- Preserve the current answer-only flow
- Prefer TypeScript-safe edits
- Keep styling and architecture consistent with the existing codebase

After inspection, implement the feature directly.
```

---

## Recommended Run Order

1. Repo discovery prompt
2. Main implementation prompt
3. Focused test prompt
4. Cleanup / hardening prompt
5. PR description prompt

