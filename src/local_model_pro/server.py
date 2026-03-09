from __future__ import annotations

import argparse
import asyncio
import json
import shlex
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from local_model_pro.admin_profile_store import (
    AdminProfileStore,
    PreferenceConflictError,
    PreferenceValidationError,
)
from local_model_pro.config import settings
from local_model_pro.local_tools import (
    CommandResult,
    LocalWorkspaceTools,
    WorkspaceSecurityError,
    WorkspaceToolError,
)
from local_model_pro.ollama_client import OllamaClient, OllamaStreamError

app = FastAPI(title="Local Model Pro Server", version="0.1.0")

runtime_default_model = settings.default_model
runtime_ollama_base_url = settings.ollama_base_url
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
admin_profile_store = AdminProfileStore(
    state_path=Path(settings.admin_state_path),
    default_actor_id=settings.default_actor_id,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


DEFAULT_MODEL_STORES: list[dict[str, Any]] = [
    {
        "id": "ollama_library",
        "name": "Ollama Library",
        "description": "Official Ollama model library",
        "search_url_template": "https://ollama.com/search?q={query}",
        "model_url_template": "https://ollama.com/library/{model}",
        "supports_api_search": False,
    },
    {
        "id": "huggingface",
        "name": "Hugging Face",
        "description": "Open model hub and metadata",
        "search_url_template": "https://huggingface.co/models?search={query}",
        "api_url_template": "https://huggingface.co/api/models?search={query}&limit=8",
        "supports_api_search": True,
    },
    {
        "id": "lmstudio_directory",
        "name": "LM Studio Model Directory",
        "description": "Curated model discovery site",
        "search_url_template": "https://lmstudio.ai/models?q={query}",
        "supports_api_search": False,
    },
]


@dataclass
class PullJob:
    job_id: str
    model: str
    status: str
    detail: str
    started_at: str
    finished_at: str | None = None
    total: int | None = None
    completed: int | None = None
    error: str | None = None


pull_jobs: dict[str, PullJob] = {}
pull_jobs_lock = asyncio.Lock()


@dataclass
class ChatSession:
    session_id: str
    model: str
    actor_id: str = settings.default_actor_id
    system_prompt: str | None = None
    messages: list[dict[str, str]] = field(default_factory=list)

    def reset(self) -> None:
        self.messages.clear()
        if self.system_prompt:
            self.messages.append({"role": "system", "content": self.system_prompt})


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload))


def _safe_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty")
    return cleaned


def _safe_reasoning_mode(value: Any) -> str:
    if not isinstance(value, str):
        return "summary"
    normalized = value.strip().lower()
    return normalized if normalized in {"hidden", "summary", "full"} else "summary"


def _resolve_think_setting(*, model: str, reasoning_mode: str) -> bool | str | None:
    mode = _safe_reasoning_mode(reasoning_mode)
    normalized_model = model.strip().lower()

    if mode == "hidden":
        return False
    if mode == "summary":
        if "gpt-oss" in normalized_model:
            return "low"
        return True
    if mode == "full":
        if "gpt-oss" in normalized_model:
            return "high"
        return True
    return None


class ModelMutationRequest(BaseModel):
    model: str


class ProfilePatchRequest(BaseModel):
    actor_id: str | None = None
    base_version: int | None = None
    patch: dict[str, Any]


class ProfileResetRequest(BaseModel):
    actor_id: str | None = None
    scope: str | None = None


class AdminUserCreateRequest(BaseModel):
    actor_id: str | None = None
    username: str
    role: str = "operator"


class AdminUserUpdateRequest(BaseModel):
    actor_id: str | None = None
    role: str | None = None
    status: str | None = None
    disabled_reason: str | None = None


class AdminPlatformPatchRequest(BaseModel):
    actor_id: str | None = None
    patch: dict[str, bool]


def _safe_actor_id(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return settings.default_actor_id


def _require_admin_token(x_admin_token: str | None) -> None:
    required_token = settings.admin_api_token.strip()
    if not required_token:
        return
    provided = (x_admin_token or "").strip()
    if not provided or provided != required_token:
        raise HTTPException(status_code=403, detail="Admin token is required.")


def _feature_enabled(feature_key: str) -> bool:
    if not admin_profile_store.is_enabled(feature_key):
        return False
    if admin_profile_store.is_enabled("readonly_mode") and feature_key in {
        "allow_model_pull",
        "allow_model_delete",
        "allow_shell_execute",
    }:
        return False
    return True


def _get_store_by_id(store_id: str) -> dict[str, Any] | None:
    for store in DEFAULT_MODEL_STORES:
        if str(store.get("id", "")).strip() == store_id:
            return store
    return None


async def _set_pull_job(job_id: str, **updates: Any) -> PullJob:
    async with pull_jobs_lock:
        job = pull_jobs[job_id]
        for key, value in updates.items():
            setattr(job, key, value)
        return job


async def _run_pull_model_job(*, job_id: str, model: str) -> None:
    try:
        await _set_pull_job(job_id, status="running", detail="Starting model pull...")

        url = f"{runtime_ollama_base_url.rstrip('/')}/api/pull"
        timeout = httpx.Timeout(timeout=3600.0, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json={"name": model, "stream": True}) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    message = body.decode("utf-8", errors="replace")[:500]
                    await _set_pull_job(
                        job_id,
                        status="failed",
                        detail="Pull failed.",
                        error=f"Ollama error {response.status_code}: {message}",
                        finished_at=_utc_now_iso(),
                    )
                    return

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    status = str(item.get("status", "")).strip() or "running"
                    await _set_pull_job(
                        job_id,
                        status="running",
                        detail=status,
                        total=int(item.get("total")) if isinstance(item.get("total"), int) else None,
                        completed=(
                            int(item.get("completed"))
                            if isinstance(item.get("completed"), int)
                            else None
                        ),
                    )

        await _set_pull_job(
            job_id,
            status="done",
            detail="Model pull completed.",
            finished_at=_utc_now_iso(),
            error=None,
        )
    except Exception as exc:  # pragma: no cover - safety net
        await _set_pull_job(
            job_id,
            status="failed",
            detail="Pull failed.",
            error=str(exc),
            finished_at=_utc_now_iso(),
        )


def _start_pull_model_job(*, job_id: str, model: str) -> None:
    asyncio.create_task(_run_pull_model_job(job_id=job_id, model=model))


async def _delete_model_on_ollama(model: str) -> dict[str, Any]:
    url = f"{runtime_ollama_base_url.rstrip('/')}/api/delete"
    timeout = httpx.Timeout(timeout=120.0, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request("DELETE", url, json={"name": model})
    body = response.text
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=body[:500] or "Delete failed")

    try:
        payload = response.json()
    except ValueError:
        payload = {"status": body[:500] or "ok"}
    if not isinstance(payload, dict):
        payload = {"status": "ok"}
    return payload


def _chunks(text: str, *, chunk_size: int = 280) -> list[str]:
    normalized = text.strip()
    if not normalized:
        return []
    return [normalized[idx : idx + chunk_size] for idx in range(0, len(normalized), chunk_size)]


def _format_command_result(result: CommandResult) -> str:
    lines = [
        f"$ {result.command}",
        f"exit_code: {result.returncode}",
    ]
    if result.timed_out:
        lines.append("status: timed_out")
    if result.output_truncated:
        lines.append("status: output_truncated")
    if result.stdout.strip():
        lines.extend(["", "stdout:", result.stdout.rstrip()])
    if result.stderr.strip():
        lines.extend(["", "stderr:", result.stderr.rstrip()])
    if not result.stdout.strip() and not result.stderr.strip():
        lines.extend(["", "(no output)"])
    return "\n".join(lines)


def _tool_help_text(*, terminal_require_confirm: bool) -> str:
    confirmation_note = (
        "Terminal confirmation is required. Use /run <cmd> to preview and /run! <cmd> to execute."
        if terminal_require_confirm
        else "Use /run <cmd> to execute shell commands in the workspace root."
    )
    return (
        "Local tools:\n"
        "- /tools\n"
        "- /ls [path]\n"
        "- /tree [path]\n"
        "- /find <query> [path]\n"
        "- /read <file_path>\n"
        "- /summary [path]\n"
        "- /run <command>\n"
        "- /run! <command>\n\n"
        f"Workspace root: {settings.workspace_root}\n"
        f"{confirmation_note}"
    )


async def _handle_local_tool_command(
    *,
    prompt: str,
    tools: LocalWorkspaceTools,
    model: str,
    ollama: OllamaClient,
    terminal_require_confirm: bool,
) -> str:
    trimmed = prompt.strip()
    if not trimmed.startswith("/"):
        raise WorkspaceToolError("Tool prompt must start with '/'.")

    if trimmed.startswith("/run!"):
        if not settings.terminal_tools_enabled or not _feature_enabled("allow_terminal_tools"):
            raise WorkspaceToolError("Terminal tools are disabled by configuration.")
        if not _feature_enabled("allow_shell_execute"):
            raise WorkspaceToolError("Terminal execute is disabled by admin policy.")
        command = trimmed[len("/run!") :].strip()
        if not command:
            raise WorkspaceToolError("Usage: /run! <command>")
        result = await tools.run_command(
            command=command,
            timeout_seconds=settings.terminal_timeout_seconds,
            max_output_bytes=settings.terminal_max_output_bytes,
        )
        return _format_command_result(result)

    if trimmed.startswith("/run"):
        if not settings.terminal_tools_enabled or not _feature_enabled("allow_terminal_tools"):
            raise WorkspaceToolError("Terminal tools are disabled by configuration.")
        command = trimmed[len("/run") :].strip()
        if not command:
            raise WorkspaceToolError("Usage: /run <command>")
        if terminal_require_confirm:
            return f"Preview: {command}\nRun /run! {command} to execute."
        result = await tools.run_command(
            command=command,
            timeout_seconds=settings.terminal_timeout_seconds,
            max_output_bytes=settings.terminal_max_output_bytes,
        )
        return _format_command_result(result)

    try:
        parts = shlex.split(trimmed)
    except ValueError as exc:
        raise WorkspaceToolError(f"Invalid command syntax: {exc}") from exc

    if not parts:
        raise WorkspaceToolError("Empty command.")

    cmd = parts[0].lower()
    if cmd == "/tools":
        return _tool_help_text(terminal_require_confirm=terminal_require_confirm)

    if cmd == "/ls":
        if not settings.filesystem_tools_enabled or not _feature_enabled("allow_filesystem_tools"):
            raise WorkspaceToolError("Filesystem tools are disabled by configuration.")
        target = parts[1] if len(parts) > 1 else "."
        return tools.list_directory(target)

    if cmd == "/tree":
        if not settings.filesystem_tools_enabled or not _feature_enabled("allow_filesystem_tools"):
            raise WorkspaceToolError("Filesystem tools are disabled by configuration.")
        target = parts[1] if len(parts) > 1 else "."
        return tools.render_tree(target, max_depth=4)

    if cmd == "/find":
        if not settings.filesystem_tools_enabled or not _feature_enabled("allow_filesystem_tools"):
            raise WorkspaceToolError("Filesystem tools are disabled by configuration.")
        if len(parts) < 2:
            raise WorkspaceToolError("Usage: /find <query> [path]")
        target = parts[2] if len(parts) > 2 else "."
        return tools.find_paths(query=parts[1], raw_path=target)

    if cmd == "/read":
        if not settings.filesystem_tools_enabled or not _feature_enabled("allow_filesystem_tools"):
            raise WorkspaceToolError("Filesystem tools are disabled by configuration.")
        if len(parts) < 2:
            raise WorkspaceToolError("Usage: /read <file_path>")
        return tools.read_text_file(parts[1])

    if cmd == "/summary":
        if not settings.filesystem_tools_enabled or not _feature_enabled("allow_filesystem_tools"):
            raise WorkspaceToolError("Filesystem tools are disabled by configuration.")
        target = parts[1] if len(parts) > 1 else "."
        context = tools.build_summary_context(target)
        summary = await ollama.chat(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You summarize local project files for an operator. "
                        "Use only provided context. Include sections: Overview, Important Files, "
                        "Risks, and Recommended Next Steps."
                    ),
                },
                {
                    "role": "user",
                    "content": context,
                },
            ],
            temperature=settings.default_temperature,
            num_ctx=settings.default_num_ctx,
        )
        return summary.strip() or "No summary generated."

    raise WorkspaceToolError("Unknown tool command. Type /tools for available commands.")


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/api/v1/profile/preferences")
async def get_profile_preferences(
    actor_id: str = Query(default=settings.default_actor_id),
) -> dict[str, Any]:
    snapshot = admin_profile_store.get_preferences(_safe_actor_id(actor_id))
    return {
        "actor_id": snapshot.actor_id,
        "version": snapshot.version,
        "preferences": snapshot.preferences,
        "updated_at": snapshot.updated_at,
    }


@app.patch("/api/v1/profile/preferences")
async def patch_profile_preferences(payload: ProfilePatchRequest) -> dict[str, Any]:
    actor_id = _safe_actor_id(payload.actor_id)
    try:
        snapshot, changed_keys = admin_profile_store.patch_preferences(
            actor_id=actor_id,
            base_version=payload.base_version,
            patch=payload.patch,
        )
    except PreferenceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PreferenceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "actor_id": snapshot.actor_id,
        "version": snapshot.version,
        "preferences": snapshot.preferences,
        "updated_at": snapshot.updated_at,
        "updated_keys": changed_keys,
    }


@app.post("/api/v1/profile/preferences/reset")
async def reset_profile_preferences(payload: ProfileResetRequest) -> dict[str, Any]:
    actor_id = _safe_actor_id(payload.actor_id)
    try:
        snapshot, changed_keys = admin_profile_store.reset_preferences(
            actor_id=actor_id,
            scope=payload.scope,
        )
    except PreferenceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "actor_id": snapshot.actor_id,
        "version": snapshot.version,
        "preferences": snapshot.preferences,
        "updated_at": snapshot.updated_at,
        "updated_keys": changed_keys,
    }


@app.get("/api/v1/admin/platform")
async def get_admin_platform(
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_token(x_admin_token)
    return {"platform": admin_profile_store.get_platform()}


@app.patch("/api/v1/admin/platform")
async def patch_admin_platform(
    payload: AdminPlatformPatchRequest,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_token(x_admin_token)
    actor_id = _safe_actor_id(payload.actor_id)
    try:
        platform = admin_profile_store.update_platform(patch=payload.patch, actor_id=actor_id)
    except PreferenceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"platform": platform}


@app.get("/api/v1/admin/users")
async def list_admin_users(
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_token(x_admin_token)
    return {"users": admin_profile_store.list_users()}


@app.post("/api/v1/admin/users")
async def create_admin_user(
    payload: AdminUserCreateRequest,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_token(x_admin_token)
    actor_id = _safe_actor_id(payload.actor_id)
    try:
        record = admin_profile_store.create_user(
            actor_id=actor_id,
            username=payload.username,
            role=payload.role,
        )
    except PreferenceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"user": record}


@app.patch("/api/v1/admin/users/{user_id}")
async def patch_admin_user(
    user_id: str,
    payload: AdminUserUpdateRequest,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_token(x_admin_token)
    actor_id = _safe_actor_id(payload.actor_id)
    patch = {
        key: value
        for key, value in {
            "role": payload.role,
            "status": payload.status,
            "disabled_reason": payload.disabled_reason,
        }.items()
        if value is not None
    }
    if not patch:
        raise HTTPException(status_code=422, detail="No update fields supplied.")
    try:
        record = admin_profile_store.update_user(actor_id=actor_id, user_id=user_id, patch=patch)
    except PreferenceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"user": record}


@app.delete("/api/v1/admin/users/{user_id}")
async def delete_admin_user(
    user_id: str,
    actor_id: str = Query(default=settings.default_actor_id),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_token(x_admin_token)
    try:
        admin_profile_store.disable_user(actor_id=_safe_actor_id(actor_id), user_id=user_id)
    except PreferenceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "disabled"}


@app.get("/api/v1/admin/events")
async def list_admin_events(
    limit: int = Query(default=100, ge=1, le=300),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_token(x_admin_token)
    return {"events": admin_profile_store.list_events(limit=limit)}


@app.get("/api/service")
async def service_info() -> dict[str, Any]:
    return {
        "service": "Local Model Pro",
        "status": "online",
        "http": {
            "health": "/health",
            "docs": "/docs",
            "models": "/api/models",
            "pull_model": "/api/models/pull",
            "pull_status": "/api/models/pull/{job_id}",
            "delete_model": "/api/models/delete",
            "model_stores": "/api/model-stores",
            "model_store_search": "/api/model-stores/search?store_id=...&q=...",
            "profile_preferences": "/api/v1/profile/preferences",
            "profile_preferences_reset": "/api/v1/profile/preferences/reset",
            "admin_users": "/api/v1/admin/users",
            "admin_platform": "/api/v1/admin/platform",
            "admin_events": "/api/v1/admin/events",
        },
        "websocket": {
            "chat": "/ws/chat",
        },
        "default_model": runtime_default_model,
        "capabilities": {
            "chat": True,
            "model_switching": True,
            "local_tools": True,
            "model_admin": True,
            "reasoning_view": {
                "supported": True,
                "modes": ["hidden", "summary", "full"],
            },
            "profile_settings": True,
            "admin_settings": True,
            "filesystem_tools_enabled": settings.filesystem_tools_enabled,
            "terminal_tools_enabled": settings.terminal_tools_enabled,
            "workspace_root": settings.workspace_root,
            "admin_token_required": bool(settings.admin_api_token.strip()),
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


@app.post("/api/models/pull")
async def pull_model(request: ModelMutationRequest) -> dict[str, Any]:
    if not _feature_enabled("allow_model_pull"):
        raise HTTPException(status_code=403, detail="Model pull is disabled by admin policy.")
    model = _safe_text(request.model, field_name="model")
    job_id = str(uuid.uuid4())
    job = PullJob(
        job_id=job_id,
        model=model,
        status="queued",
        detail="Queued pull request.",
        started_at=_utc_now_iso(),
    )
    async with pull_jobs_lock:
        pull_jobs[job_id] = job
        # Keep memory bounded.
        if len(pull_jobs) > 80:
            oldest_key = sorted(
                pull_jobs.keys(),
                key=lambda key: pull_jobs[key].started_at,
            )[0]
            if oldest_key != job_id:
                pull_jobs.pop(oldest_key, None)
    _start_pull_model_job(job_id=job_id, model=model)
    return {
        "job_id": job_id,
        "status": job.status,
        "detail": job.detail,
        "model": model,
    }


@app.get("/api/models/pull/{job_id}")
async def pull_model_status(job_id: str) -> dict[str, Any]:
    async with pull_jobs_lock:
        job = pull_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Pull job not found.")
    return {
        "job_id": job.job_id,
        "model": job.model,
        "status": job.status,
        "detail": job.detail,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "total": job.total,
        "completed": job.completed,
        "error": job.error,
    }


@app.post("/api/models/delete")
async def delete_model(request: ModelMutationRequest) -> dict[str, Any]:
    if not _feature_enabled("allow_model_delete"):
        raise HTTPException(status_code=403, detail="Model delete is disabled by admin policy.")
    model = _safe_text(request.model, field_name="model")
    payload = await _delete_model_on_ollama(model)
    return {"model": model, "result": payload}


@app.get("/api/model-stores")
async def model_stores() -> dict[str, Any]:
    return {"stores": DEFAULT_MODEL_STORES}


@app.get("/api/model-stores/search")
async def model_store_search(store_id: str, q: str) -> dict[str, Any]:
    if not _feature_enabled("allow_model_store_search"):
        raise HTTPException(status_code=403, detail="Model store search is disabled by admin policy.")
    store = _get_store_by_id(store_id.strip())
    if store is None:
        raise HTTPException(status_code=404, detail="Unknown store_id.")

    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="q cannot be empty.")
    if len(query) > 200:
        raise HTTPException(status_code=400, detail="q is too long.")

    if not store.get("supports_api_search"):
        raise HTTPException(status_code=400, detail="Selected store does not support API search.")

    api_template = str(store.get("api_url_template", "")).strip()
    if not api_template:
        raise HTTPException(status_code=400, detail="Store has no API search URL configured.")
    target_url = api_template.replace("{query}", quote_plus(query))

    timeout = httpx.Timeout(timeout=20.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(target_url)
    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Store API error {response.status_code}: {response.text[:300]}",
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Store API did not return valid JSON.") from exc

    results: list[dict[str, Any]] = []
    if isinstance(payload, list):
        for item in payload[:10]:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id", "")).strip()
            if not model_id:
                continue
            results.append(
                {
                    "id": model_id,
                    "name": model_id,
                    "downloads": item.get("downloads"),
                    "likes": item.get("likes"),
                    "updated_at": item.get("lastModified"),
                    "url": f"https://huggingface.co/{model_id}",
                }
            )
    elif isinstance(payload, dict):
        nested = payload.get("items", [])
        if isinstance(nested, list):
            for item in nested[:10]:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or item.get("id") or "").strip()
                if not name:
                    continue
                results.append(
                    {
                        "id": name,
                        "name": name,
                        "url": item.get("url"),
                    }
                )

    return {
        "store_id": store_id,
        "query": query,
        "count": len(results),
        "results": results,
    }


@app.get("/ws/chat")
async def chat_ws_http_hint() -> dict[str, Any]:
    return {
        "detail": "This path expects a WebSocket upgrade.",
        "how_to_connect": "Use a WebSocket client to ws://127.0.0.1:8765/ws/chat",
        "cli_client": "local-model-pro-cli --url ws://127.0.0.1:8765/ws/chat --model qwen2.5:7b",
        "message_types": ["hello", "chat", "set_model", "status", "reset"],
        "event_types": ["ready", "status", "start", "token", "done", "info", "error"],
        "local_tool_commands": ["/tools", "/ls", "/tree", "/find", "/read", "/summary", "/run", "/run!"],
        "chat_reasoning_mode": ["hidden", "summary", "full"],
    }


@app.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    session = ChatSession(
        session_id=str(uuid.uuid4()),
        model=runtime_default_model,
    )
    ollama = OllamaClient(base_url=runtime_ollama_base_url)
    tools: LocalWorkspaceTools | None = None
    try:
        tools = LocalWorkspaceTools(
            workspace_root=settings.workspace_root,
            read_max_bytes=settings.fs_read_max_bytes,
            list_max_entries=settings.fs_list_max_entries,
            find_max_results=settings.fs_find_max_results,
            summary_max_files=settings.fs_summary_max_files,
            summary_file_chars=settings.fs_summary_file_chars,
        )
    except WorkspaceToolError:
        tools = None

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
            "type": "info",
            "message": (
                "Local tools are available. Type /tools for filesystem and terminal commands. "
                f"Workspace root: {settings.workspace_root}"
                if tools is not None
                else "Local tools are unavailable due to workspace configuration."
            ),
        },
    )
    if tools is not None:
        platform = admin_profile_store.get_platform()
        if not bool(platform.get("allow_filesystem_tools", True)):
            await _send_json(
                websocket,
                {"type": "info", "message": "Filesystem tools are disabled by admin policy."},
            )
        if not bool(platform.get("allow_terminal_tools", True)):
            await _send_json(
                websocket,
                {"type": "info", "message": "Terminal tools are disabled by admin policy."},
            )
    await _send_json(
        websocket,
        {
            "type": "ready",
            "session_id": session.session_id,
            "actor_id": session.actor_id,
            "model": session.model,
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
                profile_snapshot = admin_profile_store.get_preferences(session.actor_id)
                system_prompt = incoming.get("system_prompt")
                if isinstance(system_prompt, str) and system_prompt.strip():
                    session.system_prompt = system_prompt.strip()
                    session.reset()
                elif not session.system_prompt:
                    default_system_prompt = str(
                        profile_snapshot.preferences.get("chat", {}).get("system_prompt", "")
                    ).strip()
                    if default_system_prompt:
                        session.system_prompt = default_system_prompt
                        session.reset()
                await _send_json(
                    websocket,
                    {
                        "type": "ready",
                        "session_id": session.session_id,
                        "actor_id": session.actor_id,
                        "model": session.model,
                    },
                )
                continue

            if msg_type == "status":
                profile_snapshot = admin_profile_store.get_preferences(session.actor_id)
                await _send_json(
                    websocket,
                    {
                        "type": "status",
                        "actor_id": session.actor_id,
                        "model": session.model,
                        "message_count": len(session.messages),
                        "reasoning_mode_default": profile_snapshot.preferences.get("chat", {}).get(
                            "reasoning_mode_default", "summary"
                        ),
                    },
                )
                continue

            if msg_type == "set_model":
                try:
                    session.model = _safe_text(incoming.get("model"), field_name="model")
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
                prompt = _safe_text(incoming.get("prompt"), field_name="prompt")
            except ValueError as exc:
                await _send_json(websocket, {"type": "error", "message": str(exc)})
                continue
            profile_snapshot = admin_profile_store.get_preferences(session.actor_id)
            default_reasoning_mode = str(
                profile_snapshot.preferences.get("chat", {}).get("reasoning_mode_default", "summary")
            )
            reasoning_mode = _safe_reasoning_mode(incoming.get("reasoning_mode") or default_reasoning_mode)
            terminal_require_confirm = bool(settings.terminal_require_confirm) or bool(
                profile_snapshot.preferences.get("tools", {}).get("terminal_require_confirm", True)
            )

            request_id = str(uuid.uuid4())
            session.messages.append({"role": "user", "content": prompt})

            await _send_json(websocket, {"type": "start", "request_id": request_id})

            assistant_chunks: list[str] = []
            if prompt.strip().startswith("/"):
                try:
                    if tools is None:
                        raise WorkspaceToolError("Local tools are unavailable in this session.")
                    tool_output = await _handle_local_tool_command(
                        prompt=prompt,
                        tools=tools,
                        model=session.model,
                        ollama=ollama,
                        terminal_require_confirm=terminal_require_confirm,
                    )
                except (WorkspaceToolError, WorkspaceSecurityError) as exc:
                    tool_output = f"Tool error: {exc}"
                except OllamaStreamError as exc:
                    tool_output = f"Summary generation failed: {exc}"
                except Exception as exc:  # pragma: no cover - safety net
                    tool_output = f"Unexpected tool failure: {exc}"

                for chunk in _chunks(tool_output):
                    assistant_chunks.append(chunk)
                    await _send_json(
                        websocket,
                        {"type": "token", "request_id": request_id, "text": chunk},
                    )

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
                continue

            try:
                async for chunk in ollama.stream_chat(
                    model=session.model,
                    messages=list(session.messages),
                    temperature=settings.default_temperature,
                    num_ctx=settings.default_num_ctx,
                    think=_resolve_think_setting(model=session.model, reasoning_mode=reasoning_mode),
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
