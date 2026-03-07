from __future__ import annotations

import asyncio
import argparse
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from local_model_pro.config import settings
from local_model_pro.conversation_store import ConversationStore
from local_model_pro.knowledge_assist import KnowledgeAssistService, QueryPlan
from local_model_pro.ollama_client import OllamaClient, OllamaStreamError
from local_model_pro.qdrant_memory import MemoryResult, QdrantMemoryIndex
from local_model_pro.web_search import WebSearchClient, WebSearchError, WebSearchResult

app = FastAPI(title="Local Model Pro Server", version="0.1.0")

runtime_default_model = settings.default_model
runtime_ollama_base_url = settings.ollama_base_url
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

conversation_store = ConversationStore(db_path=settings.sqlite_db_path)


@dataclass
class ChatSession:
    session_id: str
    model: str
    system_prompt: str | None = None
    web_assist_enabled: bool = settings.web_assist_default
    knowledge_assist_enabled: bool = settings.knowledge_assist_default
    messages: list[dict[str, str]] = field(default_factory=list)

    def reset(self) -> None:
        self.messages.clear()
        if self.system_prompt:
            self.messages.append({"role": "system", "content": self.system_prompt})


@dataclass(frozen=True)
class AssistResolution:
    query_plan: QueryPlan | None
    memory_query: str
    web_query: str
    memory_results: list[MemoryResult]


def _safe_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Expected non-empty string")
    return cleaned


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError("Expected a boolean.")


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload))


def _serialize_web_results(results: list[WebSearchResult]) -> list[dict[str, str]]:
    return [
        {
            "title": item.title,
            "url": item.url,
            "snippet": item.snippet,
        }
        for item in results
    ]


def _serialize_memory_results(results: list[MemoryResult]) -> list[dict[str, Any]]:
    return [
        {
            "insight": item.insight,
            "score": item.score,
            "source_session": item.source_session,
            "speaker": item.speaker,
            "created_at": item.created_at,
        }
        for item in results
    ]


def _serialize_query_plan(plan: QueryPlan) -> dict[str, Any]:
    return {
        "reason": plan.reason,
        "meaning": plan.meaning,
        "purpose": plan.purpose,
        "db_query": plan.db_query,
        "web_query": plan.web_query,
        "fallback": plan.fallback,
    }


def _build_web_context(*, query: str, results: list[WebSearchResult]) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        f"Web context retrieved at {timestamp} for query: {query}",
        "Use the sources below for current facts. Prefer citing URLs in the answer.",
    ]
    for idx, item in enumerate(results, start=1):
        lines.append(f"{idx}. {item.title}")
        lines.append(f"   URL: {item.url}")
        if item.snippet:
            lines.append(f"   Snippet: {item.snippet}")
    return "\n".join(lines)


def _build_memory_context(*, query: str, results: list[MemoryResult]) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        f"Knowledge memory retrieved at {timestamp} for query: {query}",
        "Use these abstracted insights as supporting context. Do not assume they are direct quotes.",
    ]
    for idx, item in enumerate(results, start=1):
        lines.append(f"{idx}. Insight: {item.insight}")
        lines.append(f"   Score: {item.score:.3f}")
        lines.append(f"   Source session: {item.source_session}")
    return "\n".join(lines)


async def _run_web_search(
    web_search: WebSearchClient,
    *,
    query: str,
    max_results: int,
) -> list[WebSearchResult]:
    return await asyncio.to_thread(
        web_search.search,
        query=query,
        max_results=max_results,
    )


def _schedule_background(coro: Any) -> None:
    task = asyncio.create_task(coro)

    def _swallow_exc(done: asyncio.Task[Any]) -> None:
        try:
            _ = done.result()
        except Exception:
            return

    task.add_done_callback(_swallow_exc)


async def _resolve_assist(
    *,
    session: ChatSession,
    prompt: str,
    request_id: str,
    websocket: WebSocket,
    knowledge: KnowledgeAssistService,
) -> AssistResolution:
    query_plan: QueryPlan | None = None
    memory_query = prompt
    web_query = prompt
    memory_results: list[MemoryResult] = []

    if not session.knowledge_assist_enabled:
        return AssistResolution(
            query_plan=None,
            memory_query=memory_query,
            web_query=web_query,
            memory_results=memory_results,
        )

    query_plan = await knowledge.build_query_plan(
        prompt=prompt,
        history=session.messages,
        model=session.model,
    )
    memory_query = query_plan.db_query.strip() or prompt
    web_query = query_plan.web_query.strip() or prompt

    await _send_json(
        websocket,
        {
            "type": "query_plan",
            "request_id": request_id,
            **_serialize_query_plan(query_plan),
        },
    )

    memory_results = await knowledge.search_memory(query=memory_query)
    await _send_json(
        websocket,
        {
            "type": "memory_results",
            "request_id": request_id,
            "query": memory_query,
            "results": _serialize_memory_results(memory_results),
        },
    )

    return AssistResolution(
        query_plan=query_plan,
        memory_query=memory_query,
        web_query=web_query,
        memory_results=memory_results,
    )


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/api/service")
async def service_info() -> dict[str, Any]:
    return {
        "service": "Local Model Pro",
        "status": "online",
        "http": {
            "health": "/health",
            "docs": "/docs",
            "models": "/api/models",
            "web_search": "/api/web/search?q=<query>",
        },
        "websocket": {
            "chat": "/ws/chat",
        },
        "default_model": runtime_default_model,
        "web_assist_default": settings.web_assist_default,
        "knowledge_assist_default": settings.knowledge_assist_default,
        "memory": {
            "backend": "sqlite+qdrant",
            "db_path": settings.sqlite_db_path,
            "qdrant_url": settings.qdrant_url,
            "qdrant_collection": settings.qdrant_collection,
        },
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/models")
async def list_models() -> dict[str, Any]:
    ollama = OllamaClient(base_url=runtime_ollama_base_url)
    try:
        models = await ollama.list_models()
    except OllamaStreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "default_model": runtime_default_model,
        "models": models,
    }


@app.get("/api/web/search")
async def web_search_http(q: str, max_results: int | None = None) -> dict[str, Any]:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    limit = settings.web_search_max_results if max_results is None else max_results
    limit = max(1, min(limit, 10))
    web_search = WebSearchClient()
    try:
        results = await _run_web_search(web_search, query=query, max_results=limit)
    except WebSearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "query": query,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "results": _serialize_web_results(results),
    }


@app.get("/ws/chat")
async def chat_ws_http_hint() -> dict[str, Any]:
    return {
        "detail": "This path expects a WebSocket upgrade.",
        "how_to_connect": "Use a WebSocket client to ws://127.0.0.1:8765/ws/chat",
        "cli_client": "local-model-pro-cli --url ws://127.0.0.1:8765/ws/chat --model qwen2.5:7b",
        "message_types": [
            "hello",
            "chat",
            "set_model",
            "status",
            "reset",
            "set_web_mode",
            "set_knowledge_mode",
            "web_search",
        ],
        "event_types": [
            "ready",
            "status",
            "start",
            "token",
            "done",
            "web_mode",
            "knowledge_mode",
            "query_plan",
            "memory_results",
            "web_results",
            "info",
            "error",
        ],
    }


@app.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    session = ChatSession(
        session_id=str(uuid.uuid4()),
        model=runtime_default_model,
    )
    ollama = OllamaClient(base_url=runtime_ollama_base_url)
    web_search = WebSearchClient()
    knowledge = KnowledgeAssistService(
        settings=settings,
        ollama=ollama,
        store=conversation_store,
        memory_index=QdrantMemoryIndex(
            base_url=settings.qdrant_url,
            collection=settings.qdrant_collection,
        ),
    )

    await knowledge.save_session(
        session_id=session.session_id,
        model=session.model,
        system_prompt=session.system_prompt,
    )

    await _send_json(
        websocket,
        {
            "type": "info",
            "message": "Connected. Send a hello payload to set model/system prompt.",
        },
    )
    await _send_json(
        websocket,
        {
            "type": "ready",
            "session_id": session.session_id,
            "model": session.model,
            "web_assist_enabled": session.web_assist_enabled,
            "knowledge_assist_enabled": session.knowledge_assist_enabled,
        },
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
                if "web_assist_enabled" in incoming:
                    try:
                        session.web_assist_enabled = _safe_bool(incoming.get("web_assist_enabled"))
                    except ValueError as exc:
                        await _send_json(websocket, {"type": "error", "message": str(exc)})
                        continue
                if "knowledge_assist_enabled" in incoming:
                    try:
                        session.knowledge_assist_enabled = _safe_bool(
                            incoming.get("knowledge_assist_enabled")
                        )
                    except ValueError as exc:
                        await _send_json(websocket, {"type": "error", "message": str(exc)})
                        continue
                await knowledge.save_session(
                    session_id=session.session_id,
                    model=session.model,
                    system_prompt=session.system_prompt,
                )
                await _send_json(
                    websocket,
                    {
                        "type": "ready",
                        "session_id": session.session_id,
                        "model": session.model,
                        "web_assist_enabled": session.web_assist_enabled,
                        "knowledge_assist_enabled": session.knowledge_assist_enabled,
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
                        "web_assist_enabled": session.web_assist_enabled,
                        "knowledge_assist_enabled": session.knowledge_assist_enabled,
                    },
                )
                continue

            if msg_type == "set_model":
                try:
                    session.model = _safe_text(incoming.get("model"))
                except ValueError as exc:
                    await _send_json(websocket, {"type": "error", "message": str(exc)})
                    continue
                await knowledge.save_session(
                    session_id=session.session_id,
                    model=session.model,
                    system_prompt=session.system_prompt,
                )
                await _send_json(websocket, {"type": "info", "message": f"Model set to {session.model}"})
                continue

            if msg_type == "set_web_mode":
                try:
                    session.web_assist_enabled = _safe_bool(incoming.get("enabled"))
                except ValueError as exc:
                    await _send_json(websocket, {"type": "error", "message": str(exc)})
                    continue
                await _send_json(
                    websocket,
                    {
                        "type": "web_mode",
                        "enabled": session.web_assist_enabled,
                    },
                )
                await _send_json(
                    websocket,
                    {
                        "type": "info",
                        "message": (
                            "Web assist enabled for chat prompts."
                            if session.web_assist_enabled
                            else "Web assist disabled."
                        ),
                    },
                )
                continue

            if msg_type == "set_knowledge_mode":
                try:
                    session.knowledge_assist_enabled = _safe_bool(incoming.get("enabled"))
                except ValueError as exc:
                    await _send_json(websocket, {"type": "error", "message": str(exc)})
                    continue
                await _send_json(
                    websocket,
                    {
                        "type": "knowledge_mode",
                        "enabled": session.knowledge_assist_enabled,
                    },
                )
                await _send_json(
                    websocket,
                    {
                        "type": "info",
                        "message": (
                            "Knowledge assist enabled for recursive retrieval."
                            if session.knowledge_assist_enabled
                            else "Knowledge assist disabled."
                        ),
                    },
                )
                continue

            if msg_type == "web_search":
                try:
                    query = _safe_text(incoming.get("query"))
                except ValueError as exc:
                    await _send_json(websocket, {"type": "error", "message": str(exc)})
                    continue
                raw_limit = incoming.get("max_results")
                if raw_limit is None:
                    max_results = settings.web_search_max_results
                elif isinstance(raw_limit, int):
                    max_results = raw_limit
                else:
                    await _send_json(websocket, {"type": "error", "message": "max_results must be an integer."})
                    continue
                max_results = max(1, min(max_results, 10))

                request_id = str(uuid.uuid4())
                assist = await _resolve_assist(
                    session=session,
                    prompt=query,
                    request_id=request_id,
                    websocket=websocket,
                    knowledge=knowledge,
                )

                try:
                    results = await _run_web_search(
                        web_search,
                        query=assist.web_query,
                        max_results=max_results,
                    )
                except WebSearchError as exc:
                    await _send_json(websocket, {"type": "error", "message": str(exc)})
                    continue
                await _send_json(
                    websocket,
                    {
                        "type": "web_results",
                        "query": assist.web_query,
                        "original_query": query,
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        "results": _serialize_web_results(results),
                    },
                )
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
            await knowledge.save_turn(
                session_id=session.session_id,
                speaker="me",
                content=prompt,
                request_id=request_id,
                model=session.model,
            )

            session.messages.append({"role": "user", "content": prompt})
            model_messages = list(session.messages)

            assist = await _resolve_assist(
                session=session,
                prompt=prompt,
                request_id=request_id,
                websocket=websocket,
                knowledge=knowledge,
            )

            web_results: list[WebSearchResult] = []
            if session.web_assist_enabled:
                try:
                    web_results = await _run_web_search(
                        web_search,
                        query=assist.web_query,
                        max_results=settings.web_search_max_results,
                    )
                except WebSearchError as exc:
                    await _send_json(
                        websocket,
                        {
                            "type": "info",
                            "message": f"Web assist unavailable, continuing without web context: {exc}",
                        },
                    )
                else:
                    await _send_json(
                        websocket,
                        {
                            "type": "web_results",
                            "query": assist.web_query,
                            "original_query": prompt,
                            "retrieved_at": datetime.now(timezone.utc).isoformat(),
                            "results": _serialize_web_results(web_results),
                            "request_id": request_id,
                        },
                    )

            if assist.memory_results or web_results:
                history_without_latest = session.messages[:-1]
                latest_user_message = session.messages[-1]
                context_messages: list[dict[str, str]] = []
                if assist.memory_results:
                    context_messages.append(
                        {
                            "role": "system",
                            "content": _build_memory_context(
                                query=assist.memory_query,
                                results=assist.memory_results,
                            ),
                        }
                    )
                if web_results:
                    context_messages.append(
                        {
                            "role": "system",
                            "content": _build_web_context(query=assist.web_query, results=web_results),
                        }
                    )
                model_messages = [
                    *history_without_latest,
                    *context_messages,
                    latest_user_message,
                ]

            await _send_json(websocket, {"type": "start", "request_id": request_id})

            assistant_chunks: list[str] = []
            try:
                async for chunk in ollama.stream_chat(
                    model=session.model,
                    messages=model_messages,
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
                await knowledge.save_turn(
                    session_id=session.session_id,
                    speaker="you",
                    content=assistant_text,
                    request_id=request_id,
                    model=session.model,
                )

            if session.knowledge_assist_enabled:
                _schedule_background(
                    knowledge.index_turn_insights(
                        session_id=session.session_id,
                        speaker="me",
                        content=prompt,
                        model=session.model,
                    )
                )
                if assistant_text:
                    _schedule_background(
                        knowledge.index_turn_insights(
                            session_id=session.session_id,
                            speaker="you",
                            content=assistant_text,
                            model=session.model,
                        )
                    )

            await _send_json(
                websocket,
                {
                    "type": "done",
                    "request_id": request_id,
                    "model": session.model,
                    "web_assist_enabled": session.web_assist_enabled,
                    "knowledge_assist_enabled": session.knowledge_assist_enabled,
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
