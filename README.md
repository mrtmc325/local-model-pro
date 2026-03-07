# Local Model Pro

Minimal local framework to run a small model over a local WebSocket and chat from a terminal CLI with streamed output.

It is designed for Apple Silicon setups (like MacBook Pro M1 Pro) using Ollama as the local model runtime.

## Features

- FastAPI WebSocket server (`/ws/chat`)
- Streaming token relay from Ollama (`/api/chat`)
- Per-connection conversation memory
- Terminal prompt CLI client
- Simple runtime commands (`/help`, `/model`, `/reset`, `/status`, `/exit`)

## Prerequisites

1. Python 3.11+ (3.14 works)
2. Ollama installed and running
3. A local model pulled in Ollama, for example:

```bash
ollama pull qwen2.5:7b-instruct
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
local-model-pro-server --host 127.0.0.1 --port 8765 --model qwen2.5:7b-instruct
```

Environment variable overrides:

- `OLLAMA_BASE_URL` (default: `http://127.0.0.1:11434`)
- `DEFAULT_MODEL` (default: `qwen2.5:7b-instruct`)
- `DEFAULT_TEMPERATURE` (default: `0.2`)
- `DEFAULT_NUM_CTX` (default: `4096`)

## Run the terminal chat client

In another terminal:

```bash
source .venv/bin/activate
local-model-pro-cli --url ws://127.0.0.1:8765/ws/chat --model qwen2.5:7b-instruct
```

Then chat:

```text
you> build me a 48-hour hiking emergency checklist
ai> ...
```

## Wire Protocol (JSON over WebSocket)

Client -> server:

- `{"type":"hello","model":"qwen2.5:7b-instruct","system_prompt":"...optional..."}`
- `{"type":"chat","prompt":"..."}`
- `{"type":"set_model","model":"llama3.1:8b"}`
- `{"type":"reset"}`
- `{"type":"status"}`

Server -> client:

- `{"type":"ready","session_id":"...","model":"..."}`
- `{"type":"start","request_id":"..."}`
- `{"type":"token","request_id":"...","text":"..."}`
- `{"type":"done","request_id":"...","model":"..."}`
- `{"type":"status","model":"...","message_count":N}`
- `{"type":"info","message":"..."}`
- `{"type":"error","message":"..."}`

## Notes

- This is a framework scaffold. You can add auth, logging, multi-user sessions, RAG, and persistence as next steps.
- The model can still hallucinate. For emergency/survival workflows, pair with trusted reference documents via RAG.
