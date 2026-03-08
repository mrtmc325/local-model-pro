from __future__ import annotations

import asyncio
import argparse
import json
import re
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
from local_model_pro.ingestion_intents import PromptIngestionIntent, parse_prompt_ingestion_intent
from local_model_pro.knowledge_assist import (
    EvidenceCard,
    GroundedResponse,
    KnowledgeAssistService,
    QueryPlan,
    SavedMemoryEvent,
    URLReviewSavedItem,
)
from local_model_pro.ollama_client import OllamaClient, OllamaStreamError
from local_model_pro.qdrant_memory import MemoryResult, QdrantMemoryIndex
from local_model_pro.web_search import WebSearchClient, WebSearchError, WebSearchResult

app = FastAPI(title="Local Model Pro Server", version="0.1.0")

runtime_default_model = settings.default_model
runtime_ollama_base_url = settings.ollama_base_url
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

conversation_store = ConversationStore(db_path=settings.sqlite_db_path)
_REASONING_MODES = {"hidden", "summary", "verbose", "debug"}


@dataclass
class ChatSession:
    session_id: str
    model: str
    actor_id: str = settings.default_actor_id
    system_prompt: str | None = None
    web_assist_enabled: bool = settings.web_assist_default
    knowledge_assist_enabled: bool = settings.knowledge_assist_default
    grounded_mode_enabled: bool = settings.grounded_mode_default
    grounded_profile: str = settings.grounded_profile_default
    reasoning_mode: str = "hidden"
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
    exact_required: bool


@dataclass(frozen=True)
class IngestionResolution:
    intent: PromptIngestionIntent
    save_event: SavedMemoryEvent | None
    review_items: list[URLReviewSavedItem]
    review_evidence_cards: list[EvidenceCard]


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


def _safe_profile(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected grounded profile string.")
    profile = value.strip().lower()
    if profile not in {"strict", "balanced"}:
        raise ValueError("grounded_profile must be one of: strict, balanced")
    return profile


def _safe_reasoning_mode(value: Any, *, default: str = "hidden") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError("reasoning_mode must be one of: hidden, summary, verbose, debug")
    mode = value.strip().lower()
    if mode not in _REASONING_MODES:
        raise ValueError("reasoning_mode must be one of: hidden, summary, verbose, debug")
    return mode


def _chunks(text: str, chunk_size: int = 64) -> list[str]:
    if not text:
        return []
    return [text[idx : idx + chunk_size] for idx in range(0, len(text), chunk_size)]


def _build_reasoning_instruction(reasoning_mode: str) -> str:
    mode = reasoning_mode.strip().lower()
    if mode == "hidden":
        return ""
    detail = {
        "summary": "Keep reasoning concise (2-4 short lines) and tied to retrieved context only.",
        "verbose": "Provide detailed reasoning notes tied to retrieved context only.",
        "debug": "Provide concise reasoning and include lightweight retrieval/debug notes.",
    }.get(mode, "Keep reasoning concise and grounded to retrieved context.")
    debug_line = (
        "\n- Include <debug> only in debug mode with retrieval transparency metadata."
        if mode == "debug"
        else ""
    )
    return (
        "Reasoning visibility mode is enabled.\n"
        "Return response in XML tags with this exact structure:\n"
        "<reasoning>...</reasoning>\n"
        "<answer>...</answer>\n"
        f"{'<debug>...</debug>' if mode == 'debug' else ''}\n"
        "Rules:\n"
        f"- {detail}\n"
        "- Do not reveal hidden/internal chain-of-thought.\n"
        "- Keep final answer content inside <answer> only."
        f"{debug_line}"
    )


def _extract_tag_block(text: str, tag: str) -> str:
    pattern = re.compile(rf"<{tag}>(.*?)</{tag}>", re.IGNORECASE | re.DOTALL)
    match = pattern.search(text)
    if not match:
        return ""
    return match.group(1).strip()


def _parse_reasoning_output(raw_text: str, reasoning_mode: str) -> tuple[str, str, str]:
    payload = (raw_text or "").strip()
    if not payload:
        return "", "", ""

    reasoning_text = _extract_tag_block(payload, "reasoning")
    answer_text = _extract_tag_block(payload, "answer")
    debug_text = _extract_tag_block(payload, "debug") if reasoning_mode == "debug" else ""

    if not answer_text:
        # Graceful fallback for models that ignore structured tags.
        return "", payload, ""
    return reasoning_text, answer_text, debug_text


def _build_debug_metadata(
    *,
    assist: AssistResolution,
    web_results: list[WebSearchResult],
    web_review_items: list[URLReviewSavedItem] | None = None,
    reasoning_mode: str,
    grounded: GroundedResponse | None = None,
    evidence_cards: list[EvidenceCard] | None = None,
) -> dict[str, Any]:
    memory_ids = [item.evidence_id for item in assist.memory_results if item.evidence_id][:5]
    metadata: dict[str, Any] = {
        "reasoning_mode": reasoning_mode,
        "memory_query": assist.memory_query,
        "memory_hits": len(assist.memory_results),
        "top_memory_evidence_ids": memory_ids,
        "web_used": bool(web_results),
        "web_result_count": len(web_results),
        "exact_required": assist.exact_required,
    }
    if web_review_items is not None:
        saved_count = sum(1 for item in web_review_items if item.status == "saved")
        metadata["web_page_reviewed_count"] = saved_count
        metadata["web_page_review_failed_count"] = max(0, len(web_review_items) - saved_count)
    if evidence_cards is not None:
        metadata["top_evidence_labels"] = [card.label for card in evidence_cards[:5]]
        metadata["top_evidence_ids"] = [card.evidence_id for card in evidence_cards[:5]]
    if grounded is not None:
        metadata["grounded_status"] = grounded.status
        metadata["grounded_confidence"] = round(grounded.overall_confidence, 3)
        metadata["clarify_needed"] = grounded.status == "insufficient"
    return metadata


def _debug_metadata_to_text(meta: dict[str, Any]) -> str:
    lines = [
        f"reasoning_mode={meta.get('reasoning_mode')}",
        f"memory_query={meta.get('memory_query')}",
        f"memory_hits={meta.get('memory_hits')}",
        f"top_memory_evidence_ids={meta.get('top_memory_evidence_ids')}",
        f"web_used={meta.get('web_used')}",
        f"web_result_count={meta.get('web_result_count')}",
        f"web_page_reviewed_count={meta.get('web_page_reviewed_count')}",
        f"web_page_review_failed_count={meta.get('web_page_review_failed_count')}",
        f"exact_required={meta.get('exact_required')}",
    ]
    if "top_evidence_labels" in meta:
        lines.append(f"top_evidence_labels={meta.get('top_evidence_labels')}")
    if "top_evidence_ids" in meta:
        lines.append(f"top_evidence_ids={meta.get('top_evidence_ids')}")
    if "grounded_status" in meta:
        lines.append(f"grounded_status={meta.get('grounded_status')}")
    if "grounded_confidence" in meta:
        lines.append(f"grounded_confidence={meta.get('grounded_confidence')}")
    if "clarify_needed" in meta:
        lines.append(f"clarify_needed={meta.get('clarify_needed')}")
    return "\n".join(lines)


def _memory_scope(item: MemoryResult, session: ChatSession) -> str:
    if item.source_session == session.session_id:
        return "same_session"
    if item.actor_id == session.actor_id:
        return "same_user"
    return "shared"


def _filter_memory_for_grounded_synthesis(
    *,
    memory_results: list[MemoryResult],
    session: ChatSession,
    exact_required: bool,
    has_web_results: bool,
) -> tuple[list[MemoryResult], int]:
    """
    For exact/recency prompts backed by fresh web retrieval, avoid recycling
    actor-owned memory summaries into grounded synthesis.
    """
    if not (exact_required and has_web_results):
        return memory_results, 0

    filtered: list[MemoryResult] = []
    excluded_count = 0
    for item in memory_results:
        scope = _memory_scope(item, session)
        if scope in {"same_session", "same_user"}:
            excluded_count += 1
            continue
        filtered.append(item)
    return filtered, excluded_count


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload))


def _serialize_web_results(results: list[WebSearchResult]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in results:
        source_type = KnowledgeAssistService.classify_source_type_for_url(item.url)
        out.append(
            {
                "title": item.title,
                "url": item.url,
                "snippet": item.snippet,
                "source_type": source_type,
                "source_tag": "user story / forum"
                if source_type == "web_user_story_forum"
                else source_type.replace("web_", ""),
                "confidence": KnowledgeAssistService.source_confidence(source_type, 0.64),
            }
        )
    return out


def _serialize_memory_results(
    results: list[MemoryResult],
    *,
    session: ChatSession,
) -> list[dict[str, Any]]:
    return [
        {
            "insight": item.insight,
            "score": item.score,
            "source_session": item.source_session,
            "speaker": item.speaker,
            "created_at": item.created_at,
            "source_type": {
                "same_session": "memory_same_session",
                "same_user": "memory_same_user",
                "shared": "memory_shared",
            }[_memory_scope(item, session)],
            "memory_source_type": item.source_type,
            "actor_scope": _memory_scope(item, session),
            "pii_flag": item.pii_flag,
            "verbatim": item.quote_text,
            "evidence_id": item.evidence_id,
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


def _serialize_evidence_cards(cards: list[EvidenceCard]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for card in cards:
        rows.append(
            {
                "label": card.label,
                "evidence_id": card.evidence_id,
                "source_type": card.source_type,
                "actor_scope": card.actor_scope,
                "content": card.content,
                "url": card.url,
                "source_session": card.source_session,
                "confidence": card.confidence,
                "pii_flag": card.pii_flag,
                "used_verbatim": card.used_verbatim,
            }
        )
    return rows


def _serialize_url_review_items(items: list[URLReviewSavedItem]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        rows.append(
            {
                "url": item.url,
                "status": item.status,
                "raw_file": item.raw_file,
                "meaning_file": item.meaning_file,
                "artifact_id": item.artifact_id,
                "indexed_count": item.indexed_count,
                "error": item.error,
                "final_url": item.final_url,
                "title": item.title,
                "meaning": item.meaning,
                "key_facts": item.key_facts or [],
            }
        )
    return rows


def _build_review_context(items: list[URLReviewSavedItem]) -> str:
    lines = ["Reviewed URL context (meaning + key facts):"]
    idx = 1
    for item in items:
        if item.status != "saved":
            continue
        meaning = (item.meaning or "").strip()
        if not meaning:
            continue
        lines.append(f"{idx}. {item.title or item.url}")
        lines.append(f"   URL: {item.final_url or item.url}")
        lines.append(f"   Meaning: {meaning}")
        for fact in (item.key_facts or [])[:4]:
            lines.append(f"   Fact: {fact}")
        idx += 1
    return "\n".join(lines)


def _relabel_evidence_cards(cards: list[EvidenceCard], *, start_index: int) -> list[EvidenceCard]:
    next_index = max(1, start_index)
    relabeled: list[EvidenceCard] = []
    for card in cards:
        relabeled.append(
            EvidenceCard(
                evidence_id=card.evidence_id,
                source_type=card.source_type,
                actor_scope=card.actor_scope,
                label=f"E{next_index}",
                content=card.content,
                url=card.url,
                source_session=card.source_session,
                confidence=card.confidence,
                pii_flag=card.pii_flag,
                used_verbatim=card.used_verbatim,
            )
        )
        next_index += 1
    return relabeled


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


def _build_memory_context(*, query: str, results: list[MemoryResult], session: ChatSession) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        f"Knowledge memory retrieved at {timestamp} for query: {query}",
        "Use these memory records as supporting context; quotes are allowed where marked verbatim.",
    ]
    for idx, item in enumerate(results, start=1):
        scope = _memory_scope(item, session)
        lines.append(f"{idx}. Insight: {item.insight}")
        lines.append(f"   Scope: {scope}  Score: {item.score:.3f}")
        if item.quote_text and scope in {"same_session", "same_user"}:
            lines.append(f"   Verbatim quote: {item.quote_text}")
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


async def _run_pre_assist_ingestion(
    *,
    session: ChatSession,
    prompt: str,
    request_id: str,
    websocket: WebSocket,
    knowledge: KnowledgeAssistService,
) -> IngestionResolution:
    intent = parse_prompt_ingestion_intent(prompt, max_urls=max(1, settings.url_review_max_urls))
    save_event: SavedMemoryEvent | None = None
    review_items: list[URLReviewSavedItem] = []
    review_evidence_cards: list[EvidenceCard] = []

    if intent.save_requested:
        if settings.direct_save_enabled:
            try:
                save_event = await knowledge.save_direct_memory(
                    session_id=session.session_id,
                    actor_id=session.actor_id,
                    request_id=request_id,
                    model=session.model,
                    save_text=intent.save_text or prompt,
                    author=intent.author,
                )
            except Exception as exc:
                await _send_json(
                    websocket,
                    {
                        "type": "memory_saved",
                        "request_id": request_id,
                        "artifact_id": "",
                        "session_id": session.session_id,
                        "actor_id": session.actor_id,
                        "author": intent.author,
                        "file_path": "",
                        "indexed_count": 0,
                        "note": f"Save failed: {exc}",
                    },
                )
                await _send_json(
                    websocket,
                    {
                        "type": "info",
                        "message": f"Direct save requested but failed: {exc}",
                    },
                )
            else:
                await _send_json(
                    websocket,
                    {
                        "type": "memory_saved",
                        "request_id": request_id,
                        "artifact_id": save_event.artifact_id,
                        "session_id": session.session_id,
                        "actor_id": session.actor_id,
                        "author": save_event.author,
                        "file_path": save_event.file_path,
                        "indexed_count": save_event.indexed_count,
                        "note": save_event.note,
                    },
                )
        else:
            await _send_json(
                websocket,
                {
                    "type": "memory_saved",
                    "request_id": request_id,
                    "artifact_id": "",
                    "session_id": session.session_id,
                    "actor_id": session.actor_id,
                    "author": intent.author,
                    "file_path": "",
                    "indexed_count": 0,
                    "note": "Direct save is disabled by configuration.",
                },
            )

    if intent.review_requested:
        if settings.url_review_enabled:
            review_items, review_evidence_cards = await knowledge.review_and_save_urls(
                session_id=session.session_id,
                actor_id=session.actor_id,
                request_id=request_id,
                model=session.model,
                urls=intent.review_urls,
                author=intent.author,
            )
        else:
            review_items = [
                URLReviewSavedItem(
                    url=url,
                    status="failed",
                    raw_file=None,
                    meaning_file=None,
                    artifact_id=None,
                    indexed_count=0,
                    error="URL review is disabled by configuration.",
                )
                for url in intent.review_urls
            ]
        await _send_json(
            websocket,
            {
                "type": "url_review_saved",
                "request_id": request_id,
                "items": _serialize_url_review_items(review_items),
            },
        )

        failures = [item for item in review_items if item.status != "saved"]
        if failures:
            await _send_json(
                websocket,
                {
                    "type": "info",
                    "message": (
                        f"URL review completed with {len(failures)} failure(s). "
                        "Continuing chat with available context."
                    ),
                },
            )

    return IngestionResolution(
        intent=intent,
        save_event=save_event,
        review_items=review_items,
        review_evidence_cards=review_evidence_cards,
    )


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
            exact_required=False,
        )

    query_plan = await knowledge.build_query_plan(
        prompt=prompt,
        history=session.messages,
        model=session.model,
    )
    memory_query = query_plan.db_query.strip() or prompt
    web_query = query_plan.web_query.strip() or prompt
    exact_required = knowledge.is_exact_concrete_request(prompt, query_plan)

    await _send_json(
        websocket,
        {
            "type": "query_plan",
            "request_id": request_id,
            "exact_required": exact_required,
            **_serialize_query_plan(query_plan),
        },
    )

    memory_results = await knowledge.search_memory(
        query=memory_query,
        actor_id=session.actor_id,
        current_session_id=session.session_id,
        query_plan=query_plan,
    )
    await _send_json(
        websocket,
        {
            "type": "memory_results",
            "request_id": request_id,
            "query": memory_query,
            "results": _serialize_memory_results(memory_results, session=session),
        },
    )

    return AssistResolution(
        query_plan=query_plan,
        memory_query=memory_query,
        web_query=web_query,
        memory_results=memory_results,
        exact_required=exact_required,
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
        "grounded_mode_default": settings.grounded_mode_default,
        "grounded_profile_default": settings.grounded_profile_default,
        "memory": {
            "backend": "sqlite+qdrant",
            "db_path": settings.sqlite_db_path,
            "export_dir": settings.memory_export_dir,
            "qdrant_url": settings.qdrant_url,
            "qdrant_collection": settings.qdrant_collection,
            "shared_default": True,
        },
        "capabilities": {
            "knowledge_assist": True,
            "grounded_mode": True,
            "grounded_profiles": ["strict", "balanced"],
            "reasoning_modes": ["hidden", "summary", "verbose", "debug"],
            "reasoning_default": "hidden",
            "web_assist": True,
            "evidence_panel_events": True,
            "direct_save": settings.direct_save_enabled,
            "url_review": settings.url_review_enabled,
            "web_assist_page_review": settings.web_assist_page_review_enabled,
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
            "set_grounded_mode",
            "set_grounded_profile",
            "set_reasoning_mode",
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
            "grounded_mode",
            "grounded_profile",
            "grounding_status",
            "evidence_used",
            "clarify_needed",
            "reasoning",
            "debug",
            "memory_saved",
            "url_review_saved",
            "web_review_context",
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
    if session.grounded_profile not in {"strict", "balanced"}:
        session.grounded_profile = "balanced"
    if session.grounded_mode_enabled:
        session.knowledge_assist_enabled = True

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
        actor_id=session.actor_id,
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
            "actor_id": session.actor_id,
            "model": session.model,
            "web_assist_enabled": session.web_assist_enabled,
            "knowledge_assist_enabled": session.knowledge_assist_enabled,
            "grounded_mode_enabled": session.grounded_mode_enabled,
            "grounded_profile": session.grounded_profile,
            "reasoning_mode": session.reasoning_mode,
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
                actor_id = incoming.get("actor_id")
                if isinstance(actor_id, str) and actor_id.strip():
                    session.actor_id = actor_id.strip()
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
                if "grounded_mode_enabled" in incoming:
                    try:
                        session.grounded_mode_enabled = _safe_bool(incoming.get("grounded_mode_enabled"))
                    except ValueError as exc:
                        await _send_json(websocket, {"type": "error", "message": str(exc)})
                        continue
                if "grounded_profile" in incoming:
                    try:
                        session.grounded_profile = _safe_profile(incoming.get("grounded_profile"))
                    except ValueError as exc:
                        await _send_json(websocket, {"type": "error", "message": str(exc)})
                        continue
                if "reasoning_mode" in incoming:
                    try:
                        session.reasoning_mode = _safe_reasoning_mode(
                            incoming.get("reasoning_mode"),
                            default=session.reasoning_mode,
                        )
                    except ValueError as exc:
                        await _send_json(websocket, {"type": "error", "message": str(exc)})
                        continue
                if session.grounded_mode_enabled:
                    session.knowledge_assist_enabled = True

                await knowledge.save_session(
                    session_id=session.session_id,
                    model=session.model,
                    system_prompt=session.system_prompt,
                    actor_id=session.actor_id,
                )
                await _send_json(
                    websocket,
                    {
                        "type": "ready",
                        "session_id": session.session_id,
                        "actor_id": session.actor_id,
                        "model": session.model,
                        "web_assist_enabled": session.web_assist_enabled,
                        "knowledge_assist_enabled": session.knowledge_assist_enabled,
                        "grounded_mode_enabled": session.grounded_mode_enabled,
                        "grounded_profile": session.grounded_profile,
                        "reasoning_mode": session.reasoning_mode,
                    },
                )
                continue

            if msg_type == "status":
                await _send_json(
                    websocket,
                    {
                        "type": "status",
                        "actor_id": session.actor_id,
                        "model": session.model,
                        "message_count": len(session.messages),
                        "web_assist_enabled": session.web_assist_enabled,
                        "knowledge_assist_enabled": session.knowledge_assist_enabled,
                        "grounded_mode_enabled": session.grounded_mode_enabled,
                        "grounded_profile": session.grounded_profile,
                        "reasoning_mode": session.reasoning_mode,
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
                    actor_id=session.actor_id,
                )
                await _send_json(websocket, {"type": "info", "message": f"Model set to {session.model}"})
                continue

            if msg_type == "set_web_mode":
                try:
                    session.web_assist_enabled = _safe_bool(incoming.get("enabled"))
                except ValueError as exc:
                    await _send_json(websocket, {"type": "error", "message": str(exc)})
                    continue
                await _send_json(websocket, {"type": "web_mode", "enabled": session.web_assist_enabled})
                await _send_json(
                    websocket,
                    {
                        "type": "info",
                        "message": (
                            "Web assist enabled for prompts."
                            if session.web_assist_enabled
                            else "Web assist disabled."
                        ),
                    },
                )
                continue

            if msg_type == "set_knowledge_mode":
                try:
                    desired = _safe_bool(incoming.get("enabled"))
                except ValueError as exc:
                    await _send_json(websocket, {"type": "error", "message": str(exc)})
                    continue
                if session.grounded_mode_enabled and not desired:
                    await _send_json(
                        websocket,
                        {
                            "type": "info",
                            "message": "Grounded mode forces Knowledge Assist on.",
                        },
                    )
                    await _send_json(websocket, {"type": "knowledge_mode", "enabled": True})
                    continue
                session.knowledge_assist_enabled = desired
                await _send_json(websocket, {"type": "knowledge_mode", "enabled": session.knowledge_assist_enabled})
                continue

            if msg_type == "set_grounded_mode":
                try:
                    session.grounded_mode_enabled = _safe_bool(incoming.get("enabled"))
                except ValueError as exc:
                    await _send_json(websocket, {"type": "error", "message": str(exc)})
                    continue
                if session.grounded_mode_enabled:
                    session.knowledge_assist_enabled = True
                    await _send_json(websocket, {"type": "knowledge_mode", "enabled": True})
                await _send_json(
                    websocket,
                    {
                        "type": "grounded_mode",
                        "enabled": session.grounded_mode_enabled,
                    },
                )
                await _send_json(
                    websocket,
                    {
                        "type": "info",
                        "message": (
                            "Grounded mode enabled."
                            if session.grounded_mode_enabled
                            else "Grounded mode disabled."
                        ),
                    },
                )
                continue

            if msg_type == "set_grounded_profile":
                try:
                    session.grounded_profile = _safe_profile(incoming.get("profile"))
                except ValueError as exc:
                    await _send_json(websocket, {"type": "error", "message": str(exc)})
                    continue
                await _send_json(
                    websocket,
                    {
                        "type": "grounded_profile",
                        "profile": session.grounded_profile,
                    },
                )
                continue

            if msg_type == "set_reasoning_mode":
                try:
                    session.reasoning_mode = _safe_reasoning_mode(
                        incoming.get("mode"),
                        default=session.reasoning_mode,
                    )
                except ValueError as exc:
                    await _send_json(websocket, {"type": "error", "message": str(exc)})
                    continue
                await _send_json(
                    websocket,
                    {
                        "type": "info",
                        "message": f"Reasoning mode set to {session.reasoning_mode}.",
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

                serialized_web = _serialize_web_results(results)
                await _send_json(
                    websocket,
                    {
                        "type": "web_results",
                        "query": assist.web_query,
                        "original_query": query,
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        "results": serialized_web,
                    },
                )

                if session.grounded_mode_enabled:
                    run_id = str(uuid.uuid4())
                    await knowledge.log_grounded_run_start(
                        run_id=run_id,
                        session_id=session.session_id,
                        actor_id=session.actor_id,
                        mode="grounded_web",
                        profile=session.grounded_profile,
                        prompt=query,
                    )
                    memory_cards = knowledge.memory_to_evidence_cards(
                        memory_results=assist.memory_results,
                        actor_id=session.actor_id,
                        current_session_id=session.session_id,
                        start_index=1,
                    )
                    web_cards = knowledge.web_to_evidence_cards(
                        web_results=serialized_web,
                        start_index=1 + len(memory_cards),
                    )
                    cards = [*memory_cards, *web_cards]
                    await knowledge.log_grounded_evidence(run_id=run_id, cards=cards)
                    await _send_json(
                        websocket,
                        {
                            "type": "evidence_used",
                            "request_id": request_id,
                            "run_id": run_id,
                            "results": _serialize_evidence_cards(cards),
                        },
                    )
                    await _send_json(
                        websocket,
                        {
                            "type": "grounding_status",
                            "request_id": request_id,
                            "run_id": run_id,
                            "action": "web_search",
                            "status": "full",
                            "profile": session.grounded_profile,
                            "exact_required": assist.exact_required,
                            "overall_confidence": sum(item.confidence for item in cards) / max(1, len(cards)),
                            "note": "Web results are annotated with source tags and confidence.",
                        },
                    )
                    await knowledge.log_grounded_run_finish(
                        run_id=run_id,
                        status="full",
                        note="Web evidence emitted.",
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
            try:
                request_reasoning_mode = _safe_reasoning_mode(
                    incoming.get("reasoning_mode"),
                    default=session.reasoning_mode,
                )
            except ValueError as exc:
                await _send_json(websocket, {"type": "error", "message": str(exc)})
                continue
            session.reasoning_mode = request_reasoning_mode

            request_id = str(uuid.uuid4())
            await knowledge.save_turn(
                session_id=session.session_id,
                speaker="me",
                content=prompt,
                request_id=request_id,
                model=session.model,
                actor_id=session.actor_id,
            )

            ingestion = await _run_pre_assist_ingestion(
                session=session,
                prompt=prompt,
                request_id=request_id,
                websocket=websocket,
                knowledge=knowledge,
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

            use_web_for_chat = (
                session.web_assist_enabled
                and (
                    not session.grounded_mode_enabled
                    or session.grounded_profile == "balanced"
                )
            )
            web_results: list[WebSearchResult] = []
            serialized_web_results: list[dict[str, Any]] = []
            search_review_items: list[URLReviewSavedItem] = []
            search_review_evidence_cards: list[EvidenceCard] = []
            if use_web_for_chat:
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
                    serialized_web_results = _serialize_web_results(web_results)
                    await _send_json(
                        websocket,
                        {
                            "type": "web_results",
                            "query": assist.web_query,
                            "original_query": prompt,
                            "retrieved_at": datetime.now(timezone.utc).isoformat(),
                            "results": serialized_web_results,
                            "request_id": request_id,
                        },
                    )

                    if (
                        serialized_web_results
                        and settings.url_review_enabled
                        and settings.web_assist_page_review_enabled
                    ):
                        try:
                            search_review_items, search_review_evidence_cards = (
                                await knowledge.review_web_results_for_context(
                                    model=session.model,
                                    web_results=serialized_web_results,
                                    max_urls=settings.web_assist_page_review_max_urls,
                                    start_index=1,
                                )
                            )
                        except Exception as exc:
                            err_text = str(exc).strip() or exc.__class__.__name__
                            await _send_json(
                                websocket,
                                {
                                    "type": "info",
                                    "request_id": request_id,
                                    "message": (
                                        "Web page review failed, continuing with search snippets: "
                                        f"{err_text}"
                                    ),
                                },
                            )
                        else:
                            if search_review_items:
                                saved_count = sum(
                                    1 for item in search_review_items if item.status == "saved"
                                )
                                failed_count = max(0, len(search_review_items) - saved_count)
                                await _send_json(
                                    websocket,
                                    {
                                        "type": "web_review_context",
                                        "request_id": request_id,
                                        "items": _serialize_url_review_items(search_review_items),
                                    },
                                )
                                await _send_json(
                                    websocket,
                                    {
                                        "type": "info",
                                        "request_id": request_id,
                                        "message": (
                                            "Reviewed top web pages for context "
                                            f"(saved={saved_count}, failed={failed_count})."
                                        ),
                                    },
                                )

            if session.grounded_mode_enabled:
                if not session.knowledge_assist_enabled:
                    session.knowledge_assist_enabled = True

                run_id = str(uuid.uuid4())
                await knowledge.log_grounded_run_start(
                    run_id=run_id,
                    session_id=session.session_id,
                    actor_id=session.actor_id,
                    mode="grounded",
                    profile=session.grounded_profile,
                    prompt=prompt,
                )

                memory_results_for_grounded, excluded_memory_count = _filter_memory_for_grounded_synthesis(
                    memory_results=assist.memory_results,
                    session=session,
                    exact_required=assist.exact_required,
                    has_web_results=bool(web_results),
                )
                memory_cards = knowledge.memory_to_evidence_cards(
                    memory_results=memory_results_for_grounded,
                    actor_id=session.actor_id,
                    current_session_id=session.session_id,
                    start_index=1,
                )
                review_cards = _relabel_evidence_cards(
                    ingestion.review_evidence_cards,
                    start_index=1 + len(memory_cards),
                )
                search_review_cards = _relabel_evidence_cards(
                    search_review_evidence_cards,
                    start_index=1 + len(memory_cards) + len(review_cards),
                )
                web_cards = knowledge.web_to_evidence_cards(
                    web_results=serialized_web_results,
                    start_index=1 + len(memory_cards) + len(review_cards) + len(search_review_cards),
                )
                evidence_cards = [
                    *memory_cards,
                    *review_cards,
                    *search_review_cards,
                    *web_cards,
                ]

                if excluded_memory_count:
                    await _send_json(
                        websocket,
                        {
                            "type": "info",
                            "request_id": request_id,
                            "run_id": run_id,
                            "message": (
                                "Excluded actor-owned memory evidence for exact query with web results "
                                f"(excluded={excluded_memory_count})."
                            ),
                        },
                    )

                await knowledge.log_grounded_evidence(run_id=run_id, cards=evidence_cards)
                await _send_json(
                    websocket,
                    {
                        "type": "evidence_used",
                        "request_id": request_id,
                        "run_id": run_id,
                        "results": _serialize_evidence_cards(evidence_cards),
                    },
                )

                try:
                    grounded: GroundedResponse = await asyncio.wait_for(
                        knowledge.generate_grounded_response(
                            prompt=prompt,
                            model=session.model,
                            grounded_profile=session.grounded_profile,
                            exact_required=assist.exact_required,
                            evidence_cards=evidence_cards,
                            reasoning_mode=session.reasoning_mode,
                        ),
                        timeout=max(5, settings.grounded_timeout_seconds),
                    )
                except asyncio.TimeoutError:
                    grounded = GroundedResponse(
                        status="insufficient",
                        answer_text="",
                        claims=[],
                        overall_confidence=0.0,
                        clarify_question="Grounded mode timed out. What exact field or fact should I verify first?",
                        note="Timed out while grounding.",
                    )

                grounded_debug_meta = _build_debug_metadata(
                    assist=assist,
                    web_results=web_results,
                    web_review_items=search_review_items,
                    reasoning_mode=session.reasoning_mode,
                    grounded=grounded,
                    evidence_cards=evidence_cards,
                )

                if session.reasoning_mode in {"summary", "verbose", "debug"} and grounded.reasoning_text:
                    await _send_json(
                        websocket,
                        {
                            "type": "reasoning",
                            "request_id": request_id,
                            "run_id": run_id,
                            "mode": session.reasoning_mode,
                            "text": grounded.reasoning_text,
                        },
                    )
                if session.reasoning_mode == "debug":
                    debug_segments = []
                    if grounded.debug_text:
                        debug_segments.append(grounded.debug_text)
                    debug_segments.append(_debug_metadata_to_text(grounded_debug_meta))
                    await _send_json(
                        websocket,
                        {
                            "type": "debug",
                            "request_id": request_id,
                            "run_id": run_id,
                            "mode": session.reasoning_mode,
                            "text": "\n\n".join(segment for segment in debug_segments if segment.strip()),
                            "meta": grounded_debug_meta,
                        },
                    )

                await knowledge.log_grounded_claims(
                    run_id=run_id,
                    claims=grounded.claims,
                    cards=evidence_cards,
                    is_exact_required=assist.exact_required,
                )
                await knowledge.log_grounded_run_finish(
                    run_id=run_id,
                    status=grounded.status,
                    note=grounded.note,
                )

                await _send_json(
                    websocket,
                    {
                        "type": "grounding_status",
                        "request_id": request_id,
                        "run_id": run_id,
                        "status": grounded.status,
                        "profile": session.grounded_profile,
                        "exact_required": assist.exact_required,
                        "overall_confidence": grounded.overall_confidence,
                        "note": grounded.note,
                    },
                )

                if grounded.status == "insufficient":
                    await _send_json(
                        websocket,
                        {
                            "type": "clarify_needed",
                            "request_id": request_id,
                            "run_id": run_id,
                            "question": grounded.clarify_question,
                        },
                    )
                    await _send_json(
                        websocket,
                        {
                            "type": "done",
                            "request_id": request_id,
                            "run_id": run_id,
                            "model": session.model,
                            "web_assist_enabled": session.web_assist_enabled,
                            "knowledge_assist_enabled": session.knowledge_assist_enabled,
                            "grounded_mode_enabled": session.grounded_mode_enabled,
                            "grounded_profile": session.grounded_profile,
                            "reasoning_mode": session.reasoning_mode,
                        },
                    )
                    continue

                await _send_json(websocket, {"type": "start", "request_id": request_id, "run_id": run_id})
                for chunk in _chunks(grounded.answer_text):
                    await _send_json(
                        websocket,
                        {"type": "token", "request_id": request_id, "run_id": run_id, "text": chunk},
                    )

                assistant_text = grounded.answer_text.strip()
                if assistant_text:
                    session.messages.append({"role": "assistant", "content": assistant_text})
                    await knowledge.save_turn(
                        session_id=session.session_id,
                        speaker="you",
                        content=assistant_text,
                        request_id=request_id,
                        model=session.model,
                        actor_id=session.actor_id,
                    )

                _schedule_background(
                    knowledge.index_turn_insights(
                        session_id=session.session_id,
                        speaker="me",
                        content=prompt,
                        model=session.model,
                        actor_id=session.actor_id,
                    )
                )
                if assistant_text:
                    _schedule_background(
                        knowledge.index_turn_insights(
                            session_id=session.session_id,
                            speaker="you",
                            content=assistant_text,
                            model=session.model,
                            actor_id=session.actor_id,
                        )
                    )

                await _send_json(
                    websocket,
                    {
                        "type": "done",
                        "request_id": request_id,
                        "run_id": run_id,
                        "model": session.model,
                        "web_assist_enabled": session.web_assist_enabled,
                        "knowledge_assist_enabled": session.knowledge_assist_enabled,
                        "grounded_mode_enabled": session.grounded_mode_enabled,
                        "grounded_profile": session.grounded_profile,
                        "reasoning_mode": session.reasoning_mode,
                    },
                )
                continue

            all_review_items = [*ingestion.review_items, *search_review_items]
            has_review_context = any(item.status == "saved" and item.meaning for item in all_review_items)
            if assist.memory_results or web_results or has_review_context:
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
                                session=session,
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
                review_context = _build_review_context(all_review_items)
                if has_review_context:
                    context_messages.append(
                        {
                            "role": "system",
                            "content": review_context,
                        }
                    )
                model_messages = [
                    *history_without_latest,
                    *context_messages,
                    latest_user_message,
                ]

            if session.reasoning_mode != "hidden":
                model_messages = [
                    *model_messages,
                    {
                        "role": "system",
                        "content": _build_reasoning_instruction(session.reasoning_mode),
                    },
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
                    if session.reasoning_mode == "hidden":
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

            raw_assistant_text = "".join(assistant_chunks).strip()
            assistant_text = raw_assistant_text
            if session.reasoning_mode != "hidden":
                reasoning_text, parsed_answer, model_debug_text = _parse_reasoning_output(
                    raw_assistant_text,
                    session.reasoning_mode,
                )
                assistant_text = parsed_answer.strip()
                if not assistant_text:
                    assistant_text = raw_assistant_text

                if reasoning_text:
                    await _send_json(
                        websocket,
                        {
                            "type": "reasoning",
                            "request_id": request_id,
                            "mode": session.reasoning_mode,
                            "text": reasoning_text,
                        },
                    )

                if session.reasoning_mode == "debug":
                    debug_meta = _build_debug_metadata(
                        assist=assist,
                        web_results=web_results,
                        web_review_items=search_review_items,
                        reasoning_mode=session.reasoning_mode,
                    )
                    debug_segments = []
                    if model_debug_text:
                        debug_segments.append(model_debug_text.strip())
                    debug_segments.append(_debug_metadata_to_text(debug_meta))
                    await _send_json(
                        websocket,
                        {
                            "type": "debug",
                            "request_id": request_id,
                            "mode": session.reasoning_mode,
                            "text": "\n\n".join(segment for segment in debug_segments if segment.strip()),
                            "meta": debug_meta,
                        },
                    )

                for chunk in _chunks(assistant_text):
                    await _send_json(
                        websocket,
                        {"type": "token", "request_id": request_id, "text": chunk},
                    )
            if assistant_text:
                session.messages.append({"role": "assistant", "content": assistant_text})
                await knowledge.save_turn(
                    session_id=session.session_id,
                    speaker="you",
                    content=assistant_text,
                    request_id=request_id,
                    model=session.model,
                    actor_id=session.actor_id,
                )

            if session.knowledge_assist_enabled:
                _schedule_background(
                    knowledge.index_turn_insights(
                        session_id=session.session_id,
                        speaker="me",
                        content=prompt,
                        model=session.model,
                        actor_id=session.actor_id,
                    )
                )
                if assistant_text:
                    _schedule_background(
                        knowledge.index_turn_insights(
                            session_id=session.session_id,
                            speaker="you",
                            content=assistant_text,
                            model=session.model,
                            actor_id=session.actor_id,
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
                    "grounded_mode_enabled": session.grounded_mode_enabled,
                    "grounded_profile": session.grounded_profile,
                    "reasoning_mode": session.reasoning_mode,
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
