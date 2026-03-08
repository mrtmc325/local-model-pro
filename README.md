# Local Model Pro

Local framework to run a small local model over WebSocket with terminal + browser chat.

It is designed for Apple Silicon setups (like MacBook Pro M1 Pro) using Ollama as the model runtime, with shared memory backed by SQLite + Qdrant.

## Features

- Built-in web frontend at `/` for browser chat
- Downloaded-model picker powered by Ollama `/api/tags`
- FastAPI WebSocket server (`/ws/chat`)
- Streaming token relay from Ollama (`/api/chat`)
- Built-in web search (`/api/web/search`) with optional web-assist mode
- New `Knowledge Assist` (default ON):
  - 3-pass recursive intent/query planning (`reason`, `meaning`, `purpose`)
  - Memory-first lookup against shared local insights (Qdrant)
  - Optional web lookup after memory retrieval
- New `Grounded Mode` (default ON):
  - Forces Knowledge Assist ON
  - Profiles: `strict` (memory-first only for chat) and `balanced` (memory + optional web for chat)
  - Claim/evidence grounding with confidence, citations, and conflict signaling
  - Clarifying-question fallback for exact requests when evidence is weak/conflicting
  - Auditable grounded claim/evidence ledger in SQLite
- Persistent transcript storage in SQLite using `me` / `you` speaker format
- Insights-only retrieval policy (raw transcripts are not injected into generation context)
- Terminal prompt CLI client
- Runtime commands (`/help`, `/model`, `/web`, `/knowledge`, `/grounded`, `/profile`, `/search`, `/reset`, `/status`, `/exit`)

## Prerequisites

1. Python 3.11+ (3.14 works)
2. Ollama installed and running
3. A local chat model pulled in Ollama, for example:

```bash
ollama pull qwen2.5:7b
```

4. A local embedding model pulled in Ollama, for example:

```bash
ollama pull nomic-embed-text
```

## Install

From this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Run the server

```bash
source .venv/bin/activate
local-model-pro-server --host 127.0.0.1 --port 8765 --model qwen2.5:7b
```

Environment variable overrides:

- `OLLAMA_BASE_URL` (default: `http://127.0.0.1:11434`)
- `DEFAULT_MODEL` (default: `qwen2.5:7b`)
- `DEFAULT_TEMPERATURE` (default: `0.2`)
- `DEFAULT_NUM_CTX` (default: `4096`)
- `WEB_SEARCH_MAX_RESULTS` (default: `5`, max `10`)
- `WEB_ASSIST_DEFAULT` (default: `false`)
- `KNOWLEDGE_ASSIST_DEFAULT` (default: `true`)
- `KNOWLEDGE_RECURSION_PASSES` (default: `3`)
- `KNOWLEDGE_PLANNER_MODEL` (default: empty, uses active chat model)
- `KNOWLEDGE_INSIGHT_MODEL` (default: empty, uses active chat model)
- `SQLITE_DB_PATH` (default: `./data/local_model_pro.db`)
- `QDRANT_URL` (default: `http://127.0.0.1:6333`)
- `QDRANT_COLLECTION` (default: `local_model_pro_insights`)
- `KNOWLEDGE_MEMORY_TOP_K` (default: `5`)
- `KNOWLEDGE_MEMORY_SCORE_THRESHOLD` (default: `0.25`)
- `EMBEDDING_MODEL` (default: `nomic-embed-text`)
- `GROUNDED_MODE_DEFAULT` (default: `true`)
- `GROUNDED_PROFILE_DEFAULT` (default: `balanced`, options: `strict|balanced`)
- `GROUNDED_TIMEOUT_SECONDS` (default: `25`)
- `DEFAULT_ACTOR_ID` (default: `anonymous`)
- `DIRECT_SAVE_ENABLED` (default: `true`)
- `MEMORY_EXPORT_DIR` (default: `/data/memory_exports`)
- `DIRECT_SAVE_MAX_TURNS` (default: `5000`)
- `URL_REVIEW_ENABLED` (default: `true`)
- `URL_REVIEW_MAX_URLS` (default: `3`)
- `URL_REVIEW_TIMEOUT_SECONDS` (default: `20`)
- `URL_REVIEW_MAX_BYTES` (default: `2000000`)
- `WEB_ASSIST_PAGE_REVIEW_ENABLED` (default: `true`)
- `WEB_ASSIST_PAGE_REVIEW_MAX_URLS` (default: `2`)

## Run with Docker Compose

This setup runs `Local Model Pro` + `Qdrant` in containers and uses Ollama from your host machine.

```bash
docker compose up -d --build
```

Check health:

```bash
curl http://127.0.0.1:8765/health
```

Open the frontend:

```bash
open http://127.0.0.1:8765/
```

In the frontend:

1. Click `Refresh` to load downloaded Ollama models.
2. Select a model (or type a tag manually).
3. Keep `Knowledge Assist` enabled to run recursive prompt breakdown and shared-memory retrieval.
4. Keep `Grounded Mode` enabled to enforce evidence + confidence behavior.
5. Choose profile:
   - `balanced`: web evidence can be included in chat when `Web Assist` is ON
   - `strict`: chat grounding stays memory-first; web remains available via direct web search
6. Optional: enable `Web Assist` to include live web context after memory retrieval.
   - When enabled, top web results are fetched/scraped and summarized into `web_review` context.
   - Tune depth with `WEB_ASSIST_PAGE_REVIEW_MAX_URLS` (recommended `1-2` for lower latency).
7. Click `Connect`, then chat.
8. Use `Search Web` for direct web lookups (memory-first if Knowledge Assist is enabled).

Stop:

```bash
docker compose down
```

## Run the terminal chat client

In another terminal:

```bash
source .venv/bin/activate
local-model-pro-cli --url ws://127.0.0.1:8765/ws/chat --model qwen2.5:7b --knowledge-assist on --grounded-mode on --grounded-profile balanced --web-assist off
```

## Retrieval order

For each prompt when `Knowledge Assist` is enabled:

1. Session memory (current chat history)
2. Shared local memory retrieval (Qdrant insights)
3. Optional web retrieval (if `Web Assist` is enabled)

Only insight abstractions are used from shared memory. Raw transcript text is persisted but not directly injected into model context.

When `Grounded Mode` is enabled:

1. Knowledge recursion (`reason/meaning/purpose`) runs first.
2. Local memory retrieval runs before web retrieval.
3. Grounding evaluates claims against evidence cards.
4. Responses include source/confidence line, claim confidence section, and source footer.
5. Exact concrete requests fail closed with a clarifying question when evidence is weak/conflicting.

## Wire Protocol (JSON over WebSocket)

Client -> server:

- `{"type":"hello","model":"qwen2.5:7b","actor_id":"anonymous","system_prompt":"...optional...","web_assist_enabled":false,"knowledge_assist_enabled":true,"grounded_mode_enabled":true,"grounded_profile":"balanced"}`
- `{"type":"chat","prompt":"..."}`
- `{"type":"set_model","model":"llama3.1:8b"}`
- `{"type":"set_web_mode","enabled":true}`
- `{"type":"set_knowledge_mode","enabled":true}`
- `{"type":"set_grounded_mode","enabled":true}`
- `{"type":"set_grounded_profile","profile":"strict"}`
- `{"type":"web_search","query":"latest weather alert in vermont","max_results":5}`
- `{"type":"reset"}`
- `{"type":"status"}`

Server -> client:

- `{"type":"ready","session_id":"...","actor_id":"...","model":"...","web_assist_enabled":false,"knowledge_assist_enabled":true,"grounded_mode_enabled":true,"grounded_profile":"balanced"}`
- `{"type":"query_plan","reason":"...","meaning":"...","purpose":"...","db_query":"...","web_query":"...","fallback":false,"exact_required":true}`
- `{"type":"memory_results","query":"...","results":[{"insight":"...","score":0.0,"source_session":"...","actor_scope":"same_user","evidence_id":"..."}]}`
- `{"type":"memory_saved","request_id":"...","artifact_id":"...","session_id":"...","actor_id":"...","author":"...","file_path":"...","indexed_count":2,"note":"..."}`
- `{"type":"evidence_used","results":[{"label":"E1","source_type":"memory_same_user","confidence":0.88,"content":"...","url":null}]}`
- `{"type":"grounding_status","status":"full|partial|insufficient","profile":"balanced","exact_required":true,"overall_confidence":0.81,"note":"..."}`
- `{"type":"clarify_needed","question":"..."}`
- `{"type":"url_review_saved","request_id":"...","items":[{"url":"https://example.com","status":"saved|failed","raw_file":"...","meaning_file":"...","artifact_id":"...","indexed_count":1,"error":null}]}`
- `{"type":"web_review_context","request_id":"...","items":[{"url":"https://example.com","status":"saved|failed","final_url":"...","title":"...","meaning":"...","key_facts":["..."],"error":null}]}`
- `{"type":"start","request_id":"..."}`
- `{"type":"token","request_id":"...","text":"..."}`
- `{"type":"done","request_id":"...","model":"...","web_assist_enabled":false,"knowledge_assist_enabled":true,"grounded_mode_enabled":true,"grounded_profile":"balanced"}`
- `{"type":"status","model":"...","message_count":N,"web_assist_enabled":false,"knowledge_assist_enabled":true,"grounded_mode_enabled":true,"grounded_profile":"balanced"}`
- `{"type":"web_mode","enabled":true}`
- `{"type":"knowledge_mode","enabled":true}`
- `{"type":"grounded_mode","enabled":true}`
- `{"type":"grounded_profile","profile":"strict"}`
- `{"type":"web_results","query":"...","retrieved_at":"...","results":[...]}`
- `{"type":"info","message":"..."}`
- `{"type":"error","message":"..."}`

## Frontend Endpoints

- `/` -> browser UI
- `/api/models` -> models detected from local Ollama
- `/api/web/search?q=<query>` -> direct web search results
- `/api/service` -> service metadata

## Notes

- This is a framework scaffold. You can add auth, tenant boundaries, and policy enforcement as follow-up steps.
- The shared memory pool is global by default.
- For high-trust workflows (medical/legal/emergency), always validate with trusted primary references.
