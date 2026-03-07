from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from local_model_pro.config import settings
from local_model_pro.ollama_client import OllamaClient, OllamaStreamError

app = FastAPI(title="Local Model Pro Server", version="0.1.0")

runtime_default_model = settings.default_model
runtime_ollama_base_url = settings.ollama_base_url


@dataclass
class ChatSession:
    session_id: str
    model: str
    system_prompt: str | None = None
    messages: list[dict[str, str]] = field(default_factory=list)

    def reset(self) -> None:
        self.messages.clear()
        if self.system_prompt:
            self.messages.append({"role": "system", "content": self.system_prompt})


def _safe_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Expected non-empty string")
    return cleaned


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload))


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "service": "Local Model Pro",
        "status": "online",
        "http": {
            "health": "/health",
            "docs": "/docs",
        },
        "websocket": {
            "chat": "/ws/chat",
        },
        "default_model": runtime_default_model,
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ws/chat")
async def chat_ws_http_hint() -> dict[str, Any]:
    return {
        "detail": "This path expects a WebSocket upgrade.",
        "how_to_connect": "Use a WebSocket client to ws://127.0.0.1:8765/ws/chat",
        "cli_client": "local-model-pro-cli --url ws://127.0.0.1:8765/ws/chat --model qwen2.5:7b",
    }


@app.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    session = ChatSession(
        session_id=str(uuid.uuid4()),
        model=runtime_default_model,
    )
    ollama = OllamaClient(base_url=runtime_ollama_base_url)
    await _send_json(
        websocket,
        {
            "type": "info",
            "message": "Connected. Send a hello payload to set model/system prompt.",
        },
    )
    await _send_json(
        websocket,
        {"type": "ready", "session_id": session.session_id, "model": session.model},
    )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                incoming = json.loads(raw)
            except json.JSONDecodeError:
                await _send_json(websocket, {"type": "error", "message": "Invalid JSON payload."})
                continue

            msg_type = incoming.get("type")
            if msg_type == "hello":
                model = incoming.get("model")
                if isinstance(model, str) and model.strip():
                    session.model = model.strip()
                system_prompt = incoming.get("system_prompt")
                if isinstance(system_prompt, str) and system_prompt.strip():
                    session.system_prompt = system_prompt.strip()
                    session.reset()
                await _send_json(
                    websocket,
                    {
                        "type": "ready",
                        "session_id": session.session_id,
                        "model": session.model,
                    },
                )
                continue

            if msg_type == "status":
                await _send_json(
                    websocket,
                    {
                        "type": "status",
                        "model": session.model,
                        "message_count": len(session.messages),
                    },
                )
                continue

            if msg_type == "set_model":
                try:
                    session.model = _safe_text(incoming.get("model"))
                except ValueError as exc:
                    await _send_json(websocket, {"type": "error", "message": str(exc)})
                    continue
                await _send_json(websocket, {"type": "info", "message": f"Model set to {session.model}"})
                continue

            if msg_type == "reset":
                session.reset()
                await _send_json(websocket, {"type": "info", "message": "Conversation reset."})
                continue

            if msg_type != "chat":
                await _send_json(
                    websocket,
                    {"type": "error", "message": f"Unsupported message type: {msg_type}"},
                )
                continue

            try:
                prompt = _safe_text(incoming.get("prompt"))
            except ValueError as exc:
                await _send_json(websocket, {"type": "error", "message": str(exc)})
                continue

            request_id = str(uuid.uuid4())
            session.messages.append({"role": "user", "content": prompt})
            await _send_json(websocket, {"type": "start", "request_id": request_id})

            assistant_chunks: list[str] = []
            try:
                async for chunk in ollama.stream_chat(
                    model=session.model,
                    messages=session.messages,
                    temperature=settings.default_temperature,
                    num_ctx=settings.default_num_ctx,
                ):
                    assistant_chunks.append(chunk)
                    await _send_json(
                        websocket,
                        {"type": "token", "request_id": request_id, "text": chunk},
                    )
            except OllamaStreamError as exc:
                await _send_json(websocket, {"type": "error", "message": str(exc)})
                # Remove user message when generation fails so history remains coherent.
                if session.messages and session.messages[-1]["role"] == "user":
                    session.messages.pop()
                continue
            except Exception as exc:  # pragma: no cover - safety net
                await _send_json(websocket, {"type": "error", "message": f"Unexpected error: {exc}"})
                if session.messages and session.messages[-1]["role"] == "user":
                    session.messages.pop()
                continue

            assistant_text = "".join(assistant_chunks).strip()
            if assistant_text:
                session.messages.append({"role": "assistant", "content": assistant_text})

            await _send_json(
                websocket,
                {
                    "type": "done",
                    "request_id": request_id,
                    "model": session.model,
                },
            )
    except WebSocketDisconnect:
        return


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Model Pro WebSocket chat server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    parser.add_argument(
        "--model",
        default=settings.default_model,
        help=f"Default model name (default: {settings.default_model})",
    )
    parser.add_argument(
        "--ollama-base-url",
        default=settings.ollama_base_url,
        help=f"Ollama base URL (default: {settings.ollama_base_url})",
    )
    return parser


def main() -> None:
    global runtime_default_model, runtime_ollama_base_url
    parser = _build_parser()
    args = parser.parse_args()

    runtime_default_model = args.model
    runtime_ollama_base_url = args.ollama_base_url

    uvicorn.run(
        "local_model_pro.server:app",
        host=args.host,
        port=args.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
