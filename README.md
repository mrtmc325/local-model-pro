# Local Model Pro

Local chat server and browser/terminal clients for Ollama models, with optional local filesystem and terminal tools.

## Features

- FastAPI server with WebSocket chat endpoint (`/ws/chat`)
- Browser chat UI at `/` with model picker
- Token streaming relay from Ollama
- Terminal CLI client
- Runtime model switching
- Reasoning-view front end with separate reasoning/answer rendering (when model emits thinking tags)
- Model lifecycle controls:
  - pull new models from Ollama registry
  - delete local models
  - poll pull-job progress/state
- Public model store hooks:
  - list configured model stores
  - open store search pages from frontend
  - optional API search against supported stores
- Profile settings API + UI:
  - per-actor preferences (theme, density, font scale, default reasoning mode, send shortcut)
  - default system prompt for new sessions
- Admin settings API + UI:
  - runtime platform policy toggles (pull/delete/tools/readonly)
  - lightweight local admin user registry
  - local admin event log
- Local workspace tools from chat:
  - list folders and tree views
  - find files
  - read text files
  - summarize file/folder context with your selected model
  - run terminal commands from the configured workspace root

## Prerequisites

1. Python 3.11+
2. Ollama installed and running
3. At least one local Ollama chat model, for example:

```bash
ollama pull qwen2.5:7b
```

## Install

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
- `DEFAULT_ACTOR_ID` (default: `anonymous`)
- `WORKSPACE_ROOT` (default: current working directory)
- `FILESYSTEM_TOOLS_ENABLED` (default: `true`)
- `TERMINAL_TOOLS_ENABLED` (default: `true`)
- `TERMINAL_REQUIRE_CONFIRM` (default: `true`)
- `TERMINAL_TIMEOUT_SECONDS` (default: `25`)
- `TERMINAL_MAX_OUTPUT_BYTES` (default: `60000`)
- `FS_READ_MAX_BYTES` (default: `120000`)
- `FS_LIST_MAX_ENTRIES` (default: `400`)
- `FS_FIND_MAX_RESULTS` (default: `60`)
- `FS_SUMMARY_MAX_FILES` (default: `8`)
- `FS_SUMMARY_FILE_CHARS` (default: `2400`)
- `ADMIN_STATE_PATH` (default: `<workspace_root>/data/admin_profile_state.json`)
- `ADMIN_API_TOKEN` (default: empty; if set, required as `X-Admin-Token` on `/api/v1/admin/*`)

Reasoning behavior:

- Frontend `Reasoning View` supports `hidden`, `summary`, and `full`
- Client sends `reasoning_mode` in each chat payload
- Server maps this to Ollama `think` controls
- Best results require thinking-capable models (for example: recent reasoning models, `gpt-oss`, `deepseek-r1`, `qwen3`)

## Run with Docker Compose

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

Stop:

```bash
docker compose down
```

## Run the terminal chat client

```bash
source .venv/bin/activate
local-model-pro-cli --url ws://127.0.0.1:8765/ws/chat --model qwen2.5:7b
```

CLI runtime commands:

- `/help`
- `/model <name>`
- `/reset`
- `/status`
- `/exit`

Server-side tool commands (send in chat input):

- `/tools`
- `/ls [path]`
- `/tree [path]`
- `/find <query> [path]`
- `/read <file_path>`
- `/summary [path]`
- `/run <command>` (preview if confirmation is required)
- `/run! <command>` (execute)

## Wire Protocol (JSON over WebSocket)

Client -> server:

- `{"type":"hello","model":"qwen2.5:7b","actor_id":"anonymous","system_prompt":"...optional..."}`
- `{"type":"chat","prompt":"..."}`
- `{"type":"set_model","model":"llama3.1:8b"}`
- `{"type":"reset"}`
- `{"type":"status"}`

Server -> client:

- `{"type":"ready","session_id":"...","actor_id":"...","model":"..."}`
- `{"type":"start","request_id":"..."}`
- `{"type":"token","request_id":"...","text":"..."}`
- `{"type":"done","request_id":"...","model":"..."}`
- `{"type":"status","model":"...","message_count":N,"actor_id":"..."}`
- `{"type":"info","message":"..."}`
- `{"type":"error","message":"..."}`

## Endpoints

- `/` browser chat UI
- `/health`
- `/api/models`
- `/api/models/pull` (POST)
- `/api/models/pull/{job_id}` (GET)
- `/api/models/delete` (POST)
- `/api/model-stores` (GET)
- `/api/model-stores/search?store_id=...&q=...` (GET)
- `/api/v1/profile/preferences` (GET, PATCH)
- `/api/v1/profile/preferences/reset` (POST)
- `/api/v1/admin/platform` (GET, PATCH)
- `/api/v1/admin/users` (GET, POST)
- `/api/v1/admin/users/{user_id}` (PATCH, DELETE)
- `/api/v1/admin/events` (GET)
- `/api/service`
- `/ws/chat`
