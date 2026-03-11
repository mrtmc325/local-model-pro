from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import shlex
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote_plus

import httpx
import uvicorn
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from local_model_pro.admin_profile_store import (
    AdminProfileStore,
    PreferenceConflictError,
    PreferenceValidationError,
)
from local_model_pro.config import settings
from local_model_pro.devflow import (
    CODING_ROLES,
    ROLE_ORDER,
    DevflowError,
    DevflowJob,
    DevflowRuntimeConfig,
    build_code_pack_markdown,
    build_documentation_markdown,
    cleanup_old_runs,
    resolve_role_models,
    run_with_retries,
    trim_jobs,
    write_devflow_artifacts,
)
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
devflow_config = DevflowRuntimeConfig(
    enabled=settings.devflow_enabled,
    max_concurrent_jobs=max(1, settings.devflow_max_concurrent_jobs),
    role_timeout_seconds=max(5, settings.devflow_role_timeout_seconds),
    retry_count=max(0, settings.devflow_retry_count),
    run_retention=max(5, settings.devflow_run_retention),
    doc_inline_max_input_chars=max(1000, settings.devflow_doc_inline_max_input_chars),
    doc_git_max_input_chars=max(800, settings.devflow_doc_git_max_input_chars),
    doc_escalation_enabled=settings.devflow_doc_escalation_enabled,
    artifact_dir=Path(settings.devflow_artifact_dir),
)
devflow_jobs: dict[str, DevflowJob] = {}
devflow_jobs_lock = asyncio.Lock()
devflow_job_semaphore = asyncio.Semaphore(devflow_config.max_concurrent_jobs)
devflow_job_tasks: dict[str, asyncio.Task[Any]] = {}


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
class UploadedReviewContext:
    upload_id: str
    actor_id: str
    filename: str
    kind: str
    size_bytes: int
    file_count: int
    included_files: int
    skipped_files: int
    summary: str
    context_text: str
    created_at: str


uploaded_contexts: dict[str, UploadedReviewContext] = {}
uploaded_contexts_lock = asyncio.Lock()

_UPLOAD_TEXT_EXTENSIONS: set[str] = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".xml",
    ".csv",
    ".tsv",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".c",
    ".h",
    ".hpp",
    ".cpp",
    ".cc",
    ".swift",
    ".rb",
    ".php",
    ".pl",
    ".vue",
    ".svelte",
    ".env",
    ".dockerfile",
    ".makefile",
}


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


def _upload_payload(item: UploadedReviewContext) -> dict[str, Any]:
    return {
        "upload_id": item.upload_id,
        "actor_id": item.actor_id,
        "filename": item.filename,
        "kind": item.kind,
        "size_bytes": item.size_bytes,
        "file_count": item.file_count,
        "included_files": item.included_files,
        "skipped_files": item.skipped_files,
        "summary": item.summary,
        "created_at": item.created_at,
    }


def _trim_text_block(value: str, *, max_chars: int) -> str:
    text = value.strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}\n\n[truncated]"


def _looks_binary(raw_bytes: bytes) -> bool:
    return b"\x00" in raw_bytes[:4096]


def _decode_text(raw_bytes: bytes) -> str | None:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            decoded = raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
        if decoded:
            return decoded
    return None


def _is_text_path(name: str) -> bool:
    lowered = name.lower().strip()
    if lowered.endswith("dockerfile") or lowered.endswith("makefile"):
        return True
    suffix = Path(lowered).suffix
    return suffix in _UPLOAD_TEXT_EXTENSIONS


def _build_plain_file_context(filename: str, raw_bytes: bytes) -> tuple[str, int, int, int]:
    if _looks_binary(raw_bytes):
        summary = f"Binary file '{filename}' uploaded; binary content is not included in context."
        return summary, 1, 0, 1
    decoded = _decode_text(raw_bytes)
    if decoded is None:
        summary = f"File '{filename}' could not be decoded as text."
        return summary, 1, 0, 1
    body = _trim_text_block(decoded, max_chars=max(2000, settings.upload_max_context_chars))
    context = f"### FILE: {filename}\n```text\n{body}\n```"
    return context, 1, 1, 0


def _build_zip_context(filename: str, raw_bytes: bytes) -> tuple[str, int, int, int]:
    lines: list[str] = []
    file_count = 0
    included = 0
    skipped = 0
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                file_count += 1
                if file_count > max(1, settings.upload_max_files_in_zip):
                    skipped += 1
                    continue

                normalized_name = info.filename.replace("\\", "/").strip() or f"file_{file_count}"
                if info.file_size > max(1024, settings.upload_member_max_bytes):
                    skipped += 1
                    lines.append(
                        f"- skipped `{normalized_name}` (size {info.file_size} bytes exceeds member limit)"
                    )
                    continue
                if not _is_text_path(normalized_name):
                    skipped += 1
                    continue

                try:
                    member_bytes = archive.read(info)
                except Exception:
                    skipped += 1
                    lines.append(f"- skipped `{normalized_name}` (unable to read member)")
                    continue

                if _looks_binary(member_bytes):
                    skipped += 1
                    continue

                decoded = _decode_text(member_bytes)
                if decoded is None:
                    skipped += 1
                    continue

                included += 1
                body = _trim_text_block(decoded, max_chars=max(500, settings.upload_member_max_bytes))
                lines.append(f"### FILE: {normalized_name}\n```text\n{body}\n```")
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail=f"Invalid ZIP archive: {exc}") from exc

    if not lines:
        lines.append("No text files were extracted from this ZIP for context.")

    context = "\n\n".join(lines)
    context = _trim_text_block(context, max_chars=max(2000, settings.upload_max_context_chars))
    return context, file_count, included, skipped


async def _store_uploaded_context(item: UploadedReviewContext) -> None:
    async with uploaded_contexts_lock:
        uploaded_contexts[item.upload_id] = item
        if len(uploaded_contexts) > max(10, settings.upload_store_retention):
            keys = sorted(uploaded_contexts.keys(), key=lambda key: uploaded_contexts[key].created_at)
            remove_count = max(0, len(uploaded_contexts) - max(10, settings.upload_store_retention))
            for key in keys[:remove_count]:
                uploaded_contexts.pop(key, None)


async def _list_uploaded_contexts(*, actor_id: str) -> list[UploadedReviewContext]:
    async with uploaded_contexts_lock:
        items = [item for item in uploaded_contexts.values() if item.actor_id == actor_id]
    return sorted(items, key=lambda item: item.created_at, reverse=True)


async def _delete_uploaded_context(*, upload_id: str, actor_id: str) -> UploadedReviewContext | None:
    async with uploaded_contexts_lock:
        item = uploaded_contexts.get(upload_id)
        if item is None:
            return None
        if item.actor_id != actor_id:
            raise HTTPException(status_code=403, detail="Upload belongs to another actor.")
        uploaded_contexts.pop(upload_id, None)
        return item


def _normalize_attachment_ids(raw_value: Any) -> list[str]:
    if not isinstance(raw_value, list):
        return []
    normalized: list[str] = []
    for item in raw_value:
        candidate = str(item).strip()
        if not candidate:
            continue
        if candidate in normalized:
            continue
        normalized.append(candidate)
    return normalized


async def _resolve_attachment_context(
    *,
    actor_id: str,
    attachment_ids: list[str],
) -> tuple[str, list[str], list[str], list[UploadedReviewContext]]:
    if not attachment_ids:
        return "", [], [], []

    missing: list[str] = []
    forbidden: list[str] = []
    resolved: list[UploadedReviewContext] = []
    async with uploaded_contexts_lock:
        for upload_id in attachment_ids:
            item = uploaded_contexts.get(upload_id)
            if item is None:
                missing.append(upload_id)
                continue
            if item.actor_id != actor_id:
                forbidden.append(upload_id)
                continue
            resolved.append(item)

    blocks: list[str] = []
    for item in resolved:
        blocks.append(
            (
                f"[Upload {item.upload_id}] {item.summary}\n"
                f"Filename: {item.filename}\n"
                f"Context:\n{item.context_text}"
            )
        )
    context = _trim_text_block(
        "\n\n".join(blocks),
        max_chars=max(1500, settings.upload_max_context_chars),
    )
    return context, missing, forbidden, resolved


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


def _devflow_enabled_or_403() -> None:
    if not devflow_config.enabled:
        raise HTTPException(status_code=403, detail="Programming development flow is disabled.")


def _job_payload(job: DevflowJob) -> dict[str, Any]:
    output_sources = {
        key: value
        for key, value in {
            "doc_inline": str(job.outputs.get("doc_inline_source", "")).strip(),
            "doc_git": str(job.outputs.get("doc_git_source", "")).strip(),
            "doc_release": str(job.outputs.get("doc_release_source", "")).strip(),
        }.items()
        if value
    }
    output_errors = {
        key: value
        for key, value in {
            "doc_inline": str(job.outputs.get("doc_inline_error", "")).strip(),
            "doc_git": str(job.outputs.get("doc_git_error", "")).strip(),
            "doc_release": str(job.outputs.get("doc_release_error", "")).strip(),
        }.items()
        if value
    }
    return {
        "job_id": job.job_id,
        "actor_id": job.actor_id,
        "prompt": job.prompt,
        "selected_model": job.selected_model,
        "role_models": job.role_models,
        "status": job.status,
        "stage": job.stage,
        "percent": job.percent,
        "message": job.message,
        "started_at": job.started_at,
        "updated_at": job.updated_at,
        "finished_at": job.finished_at,
        "error": job.error,
        "cancel_requested": job.cancel_requested,
        "artifacts": job.artifacts,
        "stages": job.stages,
        "retries_by_role": job.retries_by_role,
        "output_sources": output_sources,
        "output_errors": output_errors,
    }


async def _upsert_devflow_job(job: DevflowJob) -> None:
    async with devflow_jobs_lock:
        devflow_jobs[job.job_id] = job
        trim_jobs(devflow_jobs, max_jobs=max(1, devflow_config.run_retention))
        keep_ids = set(devflow_jobs.keys())
    cleanup_old_runs(base_dir=devflow_config.artifact_dir, keep_job_ids=keep_ids)


async def _get_devflow_job(job_id: str) -> DevflowJob | None:
    async with devflow_jobs_lock:
        return devflow_jobs.get(job_id)


async def _request_devflow_cancel(job_id: str) -> DevflowJob | None:
    task_to_cancel: asyncio.Task[Any] | None = None
    async with devflow_jobs_lock:
        job = devflow_jobs.get(job_id)
        if job is None:
            return None
        job.cancel_requested = True
        job.updated_at = _utc_now_iso()
        job.message = "Cancellation requested."
        task_to_cancel = devflow_job_tasks.get(job_id)
    if task_to_cancel is not None and not task_to_cancel.done():
        task_to_cancel.cancel()
    return job


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
    temperature: float,
    num_ctx: int,
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
            temperature=temperature,
            num_ctx=num_ctx,
        )
        return summary.strip() or "No summary generated."

    raise WorkspaceToolError("Unknown tool command. Type /tools for available commands.")


async def _run_devflow_job(
    *,
    job: DevflowJob,
    ollama: OllamaClient,
    emit_event: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    total_steps = 15
    completed_steps = 0
    max_doc_context_chars = 12000

    async def push_progress(
        *,
        stage: str,
        role: str | None,
        status: str,
        message: str,
        attempt_index: int | None = None,
        attempt_model: str | None = None,
        attempt_path: str | None = None,
    ) -> None:
        percent = int((completed_steps / total_steps) * 100)
        job.stage = stage
        job.percent = percent
        job.status = status
        job.message = message
        job.updated_at = _utc_now_iso()
        await _upsert_devflow_job(job)
        await emit_event(
            {
                "type": "devflow_progress",
                **_job_payload(job),
                "role": role,
                "attempt_index": attempt_index,
                "attempt_model": attempt_model,
                "attempt_path": attempt_path,
            }
        )

    def role_timeout_for(role_name: str) -> int:
        base = max(5, int(devflow_config.role_timeout_seconds))
        if role_name in CODING_ROLES:
            return max(base, int(base * 1.35))
        if role_name.startswith("doc_"):
            return max(45, int(base * 0.85))
        return base

    def role_num_ctx_for(role_name: str) -> int:
        if role_name in CODING_ROLES:
            return 6144
        if role_name.startswith("doc_"):
            return 4096
        return 4096

    async def call_role(role_name: str, model_name: str, role_prompt: str) -> str:
        return await asyncio.wait_for(
            ollama.chat(
                model=model_name,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are part of a strict multi-model software development workflow. "
                            "Return only role output content."
                        ),
                    },
                    {"role": "user", "content": role_prompt},
                ],
                temperature=0.2,
                num_ctx=role_num_ctx_for(role_name),
            ),
            timeout=role_timeout_for(role_name),
        )

    async def run_role(
        *,
        stage: str,
        role: str,
        output_key: str,
        role_prompt: str,
        status_message: str,
        retries: int | None = None,
        model_override: str | None = None,
        attempt_index: int = 1,
        attempt_path: str = "slot",
    ) -> str:
        nonlocal completed_steps
        if job.cancel_requested:
            raise DevflowError("Cancelled by user.")
        model_name = (
            str(model_override).strip()
            if isinstance(model_override, str) and str(model_override).strip()
            else job.role_models.get(role, job.selected_model)
        )
        normalized_attempt_index = max(1, int(attempt_index))
        normalized_attempt_path = str(attempt_path or "slot").strip() or "slot"
        await push_progress(
            stage=stage,
            role=role,
            status="running",
            message=f"{status_message} (model={model_name})",
            attempt_index=normalized_attempt_index,
            attempt_model=model_name,
            attempt_path=normalized_attempt_path,
        )
        effective_retries = devflow_config.retry_count if retries is None else max(0, retries)
        output = await run_with_retries(
            job=job,
            role=role,
            role_model=model_name,
            role_prompt=role_prompt,
            role_call=lambda active_model, active_prompt: call_role(role, active_model, active_prompt),
            retries=effective_retries,
        )
        job.outputs[output_key] = output
        completed_steps += 1
        job.stages.append(
            {
                "stage": stage,
                "role": role,
                "output_key": output_key,
                "model": model_name,
                "attempt_index": normalized_attempt_index,
                "attempt_path": normalized_attempt_path,
                "at": _utc_now_iso(),
            }
        )
        await emit_event(
            {
                "type": "devflow_stage_result",
                "job_id": job.job_id,
                "stage": stage,
                "role": role,
                "output_key": output_key,
                "model": model_name,
                "attempt_index": normalized_attempt_index,
                "attempt_model": model_name,
                "attempt_path": normalized_attempt_path,
                "status": "completed",
                "percent": int((completed_steps / total_steps) * 100),
                "output": output,
                "updated_at": _utc_now_iso(),
            }
        )
        return output

    async def run_role_with_fallback(
        *,
        stage: str,
        role: str,
        output_key: str,
        role_prompt: str,
        status_message: str,
        fallback_builder: Callable[[Exception], str],
        retries: int | None = None,
        escalate_model: str | None = None,
        escalate_enabled: bool = False,
    ) -> tuple[str, str, str]:
        nonlocal completed_steps
        slot_model = job.role_models.get(role, job.selected_model)
        first_error: Exception | None = None
        escalated_error: Exception | None = None
        escalation_candidate = str(escalate_model or "").strip()
        used_escalation_attempt = False

        try:
            result = await run_role(
                stage=stage,
                role=role,
                output_key=output_key,
                role_prompt=role_prompt,
                status_message=status_message,
                retries=retries,
                model_override=slot_model,
                attempt_index=1,
                attempt_path="slot",
            )
            return result, "role", ""
        except Exception as exc:
            first_error = exc

        if (
            escalate_enabled
            and devflow_config.doc_escalation_enabled
            and escalation_candidate
            and escalation_candidate != slot_model
        ):
            used_escalation_attempt = True
            try:
                result = await run_role(
                    stage=stage,
                    role=role,
                    output_key=output_key,
                    role_prompt=role_prompt,
                    status_message=f"{status_message} (escalated retry)",
                    retries=max(0, retries if retries is not None else 0),
                    model_override=escalation_candidate,
                    attempt_index=2,
                    attempt_path="escalated",
                )
                first_error_text = str(first_error).strip() if first_error is not None else ""
                return result, "escalated", first_error_text[:500]
            except Exception as exc:
                escalated_error = exc

        first_error_text = str(first_error).strip() if first_error is not None else ""
        if not first_error_text and first_error is not None:
            first_error_text = type(first_error).__name__
        escalated_error_text = str(escalated_error).strip() if escalated_error is not None else ""
        if not escalated_error_text and escalated_error is not None:
            escalated_error_text = type(escalated_error).__name__

        if escalated_error is not None:
            combined_error = (
                f"slot attempt failed ({slot_model}): {first_error_text or 'unknown error'}; "
                f"escalated attempt failed ({escalation_candidate}): {escalated_error_text or 'unknown error'}"
            )
            fallback_exception: Exception = DevflowError(combined_error)
        else:
            combined_error = f"slot attempt failed ({slot_model}): {first_error_text or 'unknown error'}"
            fallback_exception = first_error if first_error is not None else DevflowError(combined_error)

        fallback_output = fallback_builder(fallback_exception).strip()
        if not fallback_output:
            fallback_output = (
                f"Role '{role}' fallback output generated after failure: {combined_error[:300]}"
            )
        fallback_model = (
            escalation_candidate if used_escalation_attempt and escalation_candidate else slot_model
        )
        fallback_attempt_index = 3 if used_escalation_attempt else 2
        job.outputs[output_key] = fallback_output
        completed_steps += 1
        stage_time = _utc_now_iso()
        job.stages.append(
            {
                "stage": stage,
                "role": role,
                "output_key": output_key,
                "model": fallback_model,
                "attempt_index": fallback_attempt_index,
                "attempt_path": "fallback",
                "status": "fallback",
                "error": combined_error[:500],
                "at": stage_time,
            }
        )
        await emit_event(
            {
                "type": "devflow_stage_result",
                "job_id": job.job_id,
                "stage": stage,
                "role": role,
                "output_key": output_key,
                "model": fallback_model,
                "attempt_index": fallback_attempt_index,
                "attempt_model": fallback_model,
                "attempt_path": "fallback",
                "status": "fallback",
                "percent": int((completed_steps / total_steps) * 100),
                "output": fallback_output,
                "error": combined_error[:500],
                "updated_at": stage_time,
            }
        )
        await push_progress(
            stage=stage,
            role=role,
            status="running",
            message=f"{role} used fallback output after role failure (model={fallback_model}).",
            attempt_index=fallback_attempt_index,
            attempt_model=fallback_model,
            attempt_path="fallback",
        )
        return fallback_output, "fallback", combined_error[:500]

    def _trim_text(value: str, *, max_chars: int) -> str:
        normalized = value.strip()
        if len(normalized) <= max_chars:
            return normalized
        return f"{normalized[:max_chars].rstrip()}\n\n[truncated]"

    def _extract_first_fenced_code_block(value: str) -> tuple[str, str]:
        text = str(value or "")
        match = re.search(r"```([a-zA-Z0-9_+-]*)\s*\n([\s\S]*?)```", text)
        if not match:
            return "", text.strip()
        return match.group(1).strip().lower(), match.group(2).strip()

    def _normalize_model_inline_code(value: str) -> str:
        language, code = _extract_first_fenced_code_block(value)
        if code.strip():
            language_label = language or "python"
            return f"```{language_label}\n{code.strip()}\n```"
        raw = str(value or "").strip()
        if not raw:
            return "```python\npass\n```"
        return f"```python\n{raw}\n```"

    def _comment_prefix_for_language(language: str) -> str:
        lang = language.lower().strip()
        if lang in {"python", "py", "bash", "sh", "yaml", "yml", "toml", "ini", "ruby", "rb"}:
            return "#"
        return "//"

    def _annotate_python_code(code: str) -> str:
        lines = code.splitlines()
        out: list[str] = []

        def adjacent_comment_index() -> int | None:
            for index in range(len(out) - 1, -1, -1):
                stripped = out[index].strip()
                if not stripped:
                    continue
                if stripped.startswith("@"):
                    continue
                if stripped.startswith("#"):
                    return index
                return None
            return None

        def collect_decorators(start_index: int) -> list[str]:
            decorators: list[str] = []
            cursor = start_index - 1
            while cursor >= 0:
                probe = lines[cursor].strip()
                if not probe:
                    cursor -= 1
                    continue
                if probe.startswith("@"):
                    decorators.insert(0, probe)
                    cursor -= 1
                    continue
                if probe.startswith("#"):
                    cursor -= 1
                    continue
                break
            return decorators

        def collect_symbol_body(start_index: int, symbol_indent: int) -> list[str]:
            body: list[str] = []
            for look_ahead in range(start_index + 1, len(lines)):
                probe_raw = lines[look_ahead]
                probe = probe_raw.strip()
                if not probe:
                    body.append(probe_raw)
                    continue
                probe_indent = len(probe_raw) - len(probe_raw.lstrip())
                if probe_indent <= symbol_indent and re.match(r"^(async\s+def|def|class)\s+", probe):
                    break
                body.append(probe_raw)
            return body

        def infer_route_signature(decorators: list[str]) -> tuple[str, str] | None:
            for decorator in decorators:
                match = re.search(
                    r"""@\w+(?:\.\w+)*\.(get|post|put|delete|patch|options|head)\(\s*["']([^"']+)""",
                    decorator,
                    flags=re.IGNORECASE,
                )
                if match:
                    return match.group(1).upper(), match.group(2).strip()
            return None

        def infer_return_hint(body_lines: list[str]) -> str:
            body_blob = "\n".join(body_lines).lower()
            if "htmlresponse(" in body_blob:
                return "HTMLResponse: Rendered HTML content returned to the browser."
            if "jsonresponse(" in body_blob:
                return "JSONResponse: JSON payload for API callers."
            if "uvicorn.run(" in body_blob:
                return "None: Starts the ASGI server process."
            if re.search(r"\breturn\s+[{[]", body_blob):
                return "dict: JSON-serializable response payload."
            return "Any: Value produced by the function."

        def parse_function_args(function_line: str) -> list[str]:
            match = re.match(
                r"^\s*(?:async\s+def|def)\s+[A-Za-z_][A-Za-z0-9_]*\((.*?)\)\s*(?:->\s*[^:]+)?\s*:",
                function_line,
            )
            if not match:
                return []
            raw_args = match.group(1).strip()
            if not raw_args:
                return []
            parsed: list[str] = []
            for chunk in raw_args.split(","):
                token = chunk.strip()
                if not token or token in {"*", "/"}:
                    continue
                token = token.split(":", 1)[0].split("=", 1)[0].strip()
                token = token.lstrip("*")
                if token and token not in {"self", "cls"}:
                    parsed.append(token)
            return parsed

        def infer_symbol_comment(
            *,
            symbol_name: str,
            symbol_kind: str,
            decorators: list[str],
            body_lines: list[str],
        ) -> str:
            if symbol_kind == "class":
                return (
                    f"{symbol_name}: Define shared behavior and state for this component."
                )

            route_signature = infer_route_signature(decorators)
            body_blob = "\n".join(body_lines).lower()
            if route_signature:
                method, path = route_signature
                return (
                    f"{symbol_name}: Handle {method} {path} requests and produce the endpoint response."
                )
            if "htmlresponse(" in body_blob:
                return (
                    f"{symbol_name}: Build and return rendered HTML describing server behavior."
                )
            if "uvicorn.run(" in body_blob:
                return (
                    f"{symbol_name}: Start the ASGI application server with configured host and port."
                )
            return f"{symbol_name}: Execute application logic and return the computed result."

        def build_function_docstring(
            *,
            function_indent: str,
            function_name: str,
            decorators: list[str],
            body_lines: list[str],
            function_line: str,
        ) -> list[str]:
            route_signature = infer_route_signature(decorators)
            body_blob = "\n".join(body_lines).lower()
            if route_signature:
                method, path = route_signature
                summary = f"Handle {method} {path} requests for this API endpoint."
            elif "htmlresponse(" in body_blob:
                summary = "Render and return HTML content for browser clients."
            elif "uvicorn.run(" in body_blob:
                summary = "Start the ASGI server with the configured runtime options."
            else:
                summary = f"Execute {function_name} logic and return its result."

            args = parse_function_args(function_line)
            returns_hint = infer_return_hint(body_lines)
            doc_indent = f"{function_indent}    "
            doc_lines = [f'{doc_indent}"""{summary}']
            if args:
                doc_lines.extend(["", f"{doc_indent}Args:"])
                for arg in args:
                    doc_lines.append(f"{doc_indent}    {arg}: Input used to compute the result.")
            doc_lines.extend(["", f"{doc_indent}Returns:", f"{doc_indent}    {returns_hint}", f'{doc_indent}"""'])
            return doc_lines

        def has_upcoming_docstring(start_index: int, symbol_indent: int) -> bool:
            for look_ahead in range(start_index + 1, len(lines)):
                probe_raw = lines[look_ahead]
                probe = probe_raw.strip()
                if not probe:
                    continue
                probe_indent = len(probe_raw) - len(probe_raw.lstrip())
                if probe_indent <= symbol_indent and re.match(r"^(async\s+def|def|class)\s+", probe):
                    return False
                if probe.startswith("#"):
                    continue
                return probe.startswith('"""') or probe.startswith("'''")
            return False

        for idx, line in enumerate(lines):
            symbol_match = re.match(
                r"^(\s*)(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)",
                line,
            )
            function_match = re.match(
                r"^(\s*)(?:async\s+def|def)\s+([A-Za-z_][A-Za-z0-9_]*)",
                line,
            )
            if symbol_match:
                indent, symbol_name = symbol_match.groups()
                symbol_indent = len(indent)
                decorators = collect_decorators(idx)
                body_lines = collect_symbol_body(idx, symbol_indent)
                symbol_kind = "class" if re.match(r"^\s*class\s+", line) else "function"
                marker = infer_symbol_comment(
                    symbol_name=symbol_name,
                    symbol_kind=symbol_kind,
                    decorators=decorators,
                    body_lines=body_lines,
                )
                comment_index = adjacent_comment_index()
                if comment_index is None:
                    out.append(f"{indent}# {marker}")
                else:
                    existing_comment = out[comment_index].strip().lower()
                    if "inline documentation for behavior and intent" in existing_comment:
                        out[comment_index] = f"{indent}# {marker}"
                out.append(line)
                if function_match and not has_upcoming_docstring(idx, symbol_indent):
                    function_indent, function_name = function_match.groups()
                    out.extend(
                        build_function_docstring(
                            function_indent=function_indent,
                            function_name=function_name,
                            decorators=decorators,
                            body_lines=body_lines,
                            function_line=line,
                        )
                    )
                continue
            out.append(line)
        return "\n".join(out).strip()

    def _build_inline_documented_code(value: str, *, error_note: str | None = None) -> str:
        language, code = _extract_first_fenced_code_block(value)
        normalized_code = code.strip() or str(value or "").strip()
        if not normalized_code:
            normalized_code = "pass"
        target_language = language or "python"

        if target_language in {"python", "py"}:
            annotated_code = _annotate_python_code(normalized_code)
            comment_prefix = "#"
        else:
            comment_prefix = _comment_prefix_for_language(target_language)
            annotated_code = (
                f"{comment_prefix} Inline documentation fallback: preserve behavior and add intent comments.\n"
                f"{normalized_code}"
            )

        if error_note and "Inline documentation fallback after role error:" not in annotated_code:
            annotated_code = (
                f"{comment_prefix} Inline documentation fallback after role error: {error_note[:220]}\n"
                f"{annotated_code}"
            )

        language_label = target_language if target_language else "text"
        return f"```{language_label}\n{annotated_code.strip()}\n```"

    def _normalize_git_notes(value: str) -> str:
        text = str(value or "").strip()
        section_labels = [
            "Commit Title",
            "Commit Body",
            "Validation Checklist",
            "Risk Notes",
        ]
        has_required_sections = all(
            re.search(rf"(?im)^\s*(?:#+\s*)?{re.escape(label)}\s*:?", text) for label in section_labels
        )
        if has_required_sections:
            normalized = text
        else:
            extracted_lines = [line.strip() for line in text.splitlines() if line.strip()]
            commit_title = ""
            for line in extracted_lines:
                candidate = line.lstrip("-*# ").strip()
                if candidate:
                    commit_title = candidate.rstrip(".")
                    break
            if not commit_title:
                commit_title = "add generated implementation from devflow run"
            commit_title = commit_title[:72].strip() or "add generated implementation from devflow run"

            commit_body_items: list[str] = []
            for line in extracted_lines:
                cleaned = line.lstrip("-*# ").strip()
                if not cleaned or cleaned == commit_title:
                    continue
                commit_body_items.append(cleaned)
                if len(commit_body_items) >= 5:
                    break
            if not commit_body_items:
                commit_body_items = [
                    "Implement generated solution scaffold and core logic.",
                    "Align behavior with the original development request.",
                ]

            checklist_items = [
                "Run lint and formatting checks for generated code.",
                "Run test suite and verify expected pass state.",
                "Smoke-test startup command and core endpoint behavior.",
                "Review generated code for security and maintainability risks.",
            ]
            risk_items = [
                "Generated output still requires manual engineering review before merge.",
                "Dependency and runtime assumptions must be validated in target environment.",
            ]
            normalized = (
                f"Commit Title: {commit_title}\n\n"
                "Commit Body:\n"
                + "\n".join([f"- {item}" for item in commit_body_items])
                + "\n\nValidation Checklist:\n"
                + "\n".join([f"- {item}" for item in checklist_items])
                + "\n\nRisk Notes:\n"
                + "\n".join([f"- {item}" for item in risk_items])
            )

        if len(normalized) > 2200:
            normalized = f"{normalized[:2200].rstrip()}\n\n- [truncated]"
        return normalized.strip()

    def round_bundle(
        label: str,
        mapping: dict[str, str],
        *,
        max_chars_per_role: int = 2200,
        max_total_chars: int = 9000,
    ) -> str:
        lines = [f"{label}:"]
        for key in sorted(mapping.keys()):
            lines.append(f"- {key}:")
            lines.append(_trim_text(mapping[key], max_chars=max_chars_per_role))
            lines.append("")
        return _trim_text("\n".join(lines).strip(), max_chars=max_total_chars)

    scope_guard = (
        "Primary rule: the original user request is the source of truth. "
        "Do not drift scope, invent unrelated features, or ignore explicit constraints."
    )

    async with devflow_job_semaphore:
        try:
            job.status = "running"
            job.stage = "intent"
            job.percent = 0
            job.message = "Running intent stage."
            job.updated_at = _utc_now_iso()
            await _upsert_devflow_job(job)
            await push_progress(
                stage="intent",
                role=None,
                status="running",
                message="Running intent stage.",
            )

            intent_reasoner = await run_role(
                stage="intent",
                role="intent_reasoner",
                output_key="intent_reasoner",
                status_message="Analyzing request intent and logic.",
                role_prompt=(
                    "Explain what the user is asking for and decompose required logic into concise subparts.\n"
                    "Return 6-10 bullets maximum.\n"
                    f"{scope_guard}\n\n"
                    f"User request:\n{job.prompt}"
                ),
            )
            intent_knowledge = await run_role(
                stage="intent",
                role="intent_knowledge",
                output_key="intent_knowledge",
                status_message="Building general knowledge framing.",
                role_prompt=(
                    "Describe in concise technical terms what this programming request is about.\n"
                    "Return 5-8 bullets maximum.\n"
                    f"{scope_guard}\n\n"
                    f"User request:\n{job.prompt}"
                ),
            )
            intent_feasibility = await run_role(
                stage="intent",
                role="intent_feasibility",
                output_key="intent_feasibility",
                status_message="Synthesizing feasibility prompt.",
                role_prompt=(
                    "Convert the user request and analysis into a natural-language-to-code feasibility prompt. "
                    "Include constraints, architecture hints, and implementation goals.\n\n"
                    f"{scope_guard}\n\n"
                    f"Intent reasoner output:\n{intent_reasoner}\n\n"
                    f"Intent knowledge output:\n{intent_knowledge}\n\n"
                    f"Original request:\n{job.prompt}"
                ),
            )

            round1: dict[str, str] = {}
            for role in CODING_ROLES:
                round1[role] = await run_role(
                    stage="coding_round_1",
                    role=role,
                    output_key=f"round1.{role}",
                    status_message=f"{role} generating first code attempt.",
                    role_prompt=(
                        "Generate code solution attempt #1 from this feasibility prompt. "
                        "Return concrete code with brief notes if needed. Keep response concise.\n"
                        f"{scope_guard}\n\n"
                        f"Feasibility prompt:\n{intent_feasibility}"
                    ),
                )

            round2: dict[str, str] = {}
            round1_bundle = round_bundle(
                "Round 1 outputs",
                round1,
                max_chars_per_role=1800,
                max_total_chars=7000,
            )
            for role in CODING_ROLES:
                round2[role] = await run_role(
                    stage="coding_round_2",
                    role=role,
                    output_key=f"round2.{role}",
                    status_message=f"{role} revising against all round-1 outputs.",
                    role_prompt=(
                        "Generate code solution attempt #2 by reviewing and comparing all round-1 attempts. "
                        "Resolve conflicts and improve quality. Keep response concise.\n"
                        f"{scope_guard}\n\n"
                        f"{round1_bundle}\n\nOriginal request:\n{job.prompt}"
                    ),
                )

            round2_bundle = round_bundle(
                "Round 2 outputs",
                round2,
                max_chars_per_role=2000,
                max_total_chars=7800,
            )
            round3_model1 = await run_role(
                stage="coding_round_3",
                role="code_model_1",
                output_key="round3.code_model_1",
                status_message="Round-3 chain: model 1 isolating canonical solution.",
                role_prompt=(
                    "Round 3 chain step 1: ingest all round-2 outputs and isolate the best canonical code.\n"
                    f"{scope_guard}\n\n"
                    f"{round2_bundle}\n\nOriginal request:\n{job.prompt}"
                ),
            )
            round3_model2 = await run_role(
                stage="coding_round_3",
                role="code_model_2",
                output_key="round3.code_model_2",
                status_message="Round-3 chain: model 2 refining with model 1 output.",
                role_prompt=(
                    "Round 3 chain step 2: ingest all round-2 outputs plus model-1 round-3 output and produce improved code.\n\n"
                    f"{scope_guard}\n\n"
                    f"{round2_bundle}\n\nModel1 round3 output:\n{round3_model1}\n\nOriginal request:\n{job.prompt}"
                ),
            )
            round3_model3 = await run_role(
                stage="coding_round_3",
                role="code_model_3",
                output_key="round3.code_model_3",
                status_message="Round-3 chain: model 3 producing final canonical code.",
                role_prompt=(
                    "Round 3 chain step 3: ingest all round-2 outputs plus model-1 and model-2 round-3 outputs. "
                    "Produce the final canonical code.\n\n"
                    f"{scope_guard}\n\n"
                    f"{round2_bundle}\n\nModel1 round3 output:\n{round3_model1}\n\n"
                    f"Model2 round3 output:\n{round3_model2}\n\nOriginal request:\n{job.prompt}"
                ),
            )
            job.outputs["final_code"] = round3_model3

            trimmed_final_code = _trim_text(round3_model3, max_chars=max_doc_context_chars)
            canonical_language, canonical_code = _extract_first_fenced_code_block(round3_model3)
            canonical_code_text = canonical_code.strip() or round3_model3.strip() or "pass"
            code_language = canonical_language or "python"
            trimmed_inline_code = _trim_text(
                canonical_code_text,
                max_chars=devflow_config.doc_inline_max_input_chars,
            )
            trimmed_git_code = _trim_text(
                canonical_code_text,
                max_chars=devflow_config.doc_git_max_input_chars,
            )
            trimmed_request = _trim_text(job.prompt, max_chars=1500)
            final_code_context = (
                f"Final canonical code:\n{trimmed_final_code}\n\nOriginal request:\n{trimmed_request}"
            )
            inline_doc_context = (
                f"Canonical code to annotate:\n```{code_language}\n{trimmed_inline_code}\n```\n\n"
                f"Original request:\n{trimmed_request}"
            )
            git_notes_context = (
                f"Canonical code:\n```{code_language}\n{trimmed_git_code}\n```\n\n"
                f"Original request:\n{trimmed_request}"
            )
            doc_escalation_model = job.role_models.get("code_model_3", job.selected_model)

            doc_inline_raw, doc_inline_source, doc_inline_error = await run_role_with_fallback(
                stage="documentation",
                role="doc_inline",
                output_key="doc_inline",
                status_message="Generating inline-documented code variant.",
                role_prompt=(
                    "You are documenting existing code for maintainers. Preserve behavior exactly and return ONLY one fenced code block.\n"
                    "Hard requirements:\n"
                    "1) Keep runtime behavior unchanged (same endpoints, same port, same control flow).\n"
                    "2) Add specific inline comments above non-obvious blocks using symbol-aware language.\n"
                    "3) For every function/method, include a meaningful docstring with purpose and return value.\n"
                    "4) Add an Args section when parameters exist.\n"
                    "5) For FastAPI route handlers, explicitly mention HTTP method and route path in comment or docstring.\n"
                    "6) Do not emit placeholder text such as 'inline documentation for behavior and intent'.\n"
                    "7) Do not include prose outside the code block.\n"
                    f"{scope_guard}\n"
                    "Self-check before responding: no duplicate consecutive comment lines and no missing function docstrings.\n\n"
                    f"{inline_doc_context}"
                ),
                retries=0,
                escalate_model=doc_escalation_model,
                escalate_enabled=True,
                fallback_builder=lambda exc: _build_inline_documented_code(
                    round3_model3,
                    error_note=str(exc),
                ),
            )
            job.outputs["doc_inline_raw"] = doc_inline_raw
            job.outputs["doc_inline_source"] = doc_inline_source
            job.outputs["doc_inline_error"] = doc_inline_error
            job.outputs["doc_inline_code"] = _normalize_model_inline_code(doc_inline_raw)

            doc_git_raw, doc_git_source, doc_git_error = await run_role_with_fallback(
                stage="documentation",
                role="doc_git",
                output_key="doc_git",
                status_message="Generating git notes.",
                role_prompt=(
                    "Generate deterministic git notes for the generated code.\n"
                    "Return markdown with exactly these sections and labels:\n"
                    "Commit Title:\nCommit Body:\nValidation Checklist:\nRisk Notes:\n"
                    "Constraints:\n"
                    "- Commit title: single line, <=72 chars.\n"
                    "- Commit body: 3-6 bullets.\n"
                    "- Validation checklist: 4-8 bullets.\n"
                    "- Risk notes: 2-4 bullets.\n\n"
                    f"{scope_guard}\n\n"
                    f"{git_notes_context}"
                ),
                retries=0,
                escalate_model=doc_escalation_model,
                escalate_enabled=True,
                fallback_builder=lambda exc: (
                    "Git notes fallback (role failed):\n\n"
                    f"- Error: {str(exc)[:240]}\n"
                    "- Suggested commit title: add generated implementation from devflow run\n"
                    "- Suggested scope: app bootstrap, routes, server config, and docs\n"
                    "- Validation notes: run local smoke test and endpoint checks before merge"
                ),
            )
            doc_git = _normalize_git_notes(doc_git_raw)
            job.outputs["doc_git"] = doc_git
            job.outputs["doc_git_source"] = doc_git_source
            job.outputs["doc_git_error"] = doc_git_error

            doc_release, doc_release_source, doc_release_error = await run_role_with_fallback(
                stage="documentation",
                role="doc_release",
                output_key="doc_release",
                status_message="Generating release notes.",
                role_prompt=(
                    "Generate release notes for this generated code including highlights, compatibility, and risk notes.\n\n"
                    f"{scope_guard}\n\n"
                    f"{final_code_context}"
                ),
                retries=0,
                fallback_builder=lambda exc: (
                    "Release notes fallback (role failed):\n\n"
                    f"- Error: {str(exc)[:240]}\n"
                    "- Highlights: initial generated feature scaffold and runnable service entrypoint\n"
                    "- Compatibility: verify Python and dependency versions in your runtime\n"
                    "- Risks: generated code requires operator review before production rollout"
                ),
            )
            job.outputs["doc_release"] = doc_release
            job.outputs["doc_release_source"] = doc_release_source
            job.outputs["doc_release_error"] = doc_release_error
            job.outputs["doc_inline_fallback_used"] = "true" if doc_inline_source == "fallback" else "false"
            job.outputs["doc_git_fallback_used"] = "true" if doc_git_source == "fallback" else "false"
            job.outputs["doc_release_fallback_used"] = (
                "true" if doc_release_source == "fallback" else "false"
            )

            job.status = "completed"
            job.stage = "completed"
            job.percent = 100
            job.message = "Programming development workflow completed."
            job.updated_at = _utc_now_iso()
            job.finished_at = _utc_now_iso()
            code_pack = build_code_pack_markdown(prompt=job.prompt, outputs=job.outputs)
            documentation = build_documentation_markdown(prompt=job.prompt, outputs=job.outputs)
            artifacts = write_devflow_artifacts(
                base_dir=devflow_config.artifact_dir,
                job=job,
                code_pack=code_pack,
                documentation=documentation,
            )
            metadata_path = Path(artifacts["run_dir"]) / "run_metadata.json"
            metadata_path.write_text(
                json.dumps(_job_payload(job), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            artifacts["metadata"] = str(metadata_path)
            job.artifacts = artifacts
            job.run_dir = artifacts.get("run_dir")
            await _upsert_devflow_job(job)
            await emit_event(
                {
                    "type": "devflow_done",
                    **_job_payload(job),
                    "download_url": f"/api/devflow/jobs/{job.job_id}/download",
                }
            )
        except asyncio.CancelledError:
            cancel_reason = "Cancelled by user." if job.cancel_requested else "Cancelled."
            job.status = "failed"
            job.stage = "failed"
            job.message = f"Programming workflow cancelled: {cancel_reason}"
            job.error = cancel_reason
            job.updated_at = _utc_now_iso()
            job.finished_at = _utc_now_iso()
            if job.outputs:
                code_pack = build_code_pack_markdown(prompt=job.prompt, outputs=job.outputs)
                documentation = build_documentation_markdown(prompt=job.prompt, outputs=job.outputs)
                artifacts = write_devflow_artifacts(
                    base_dir=devflow_config.artifact_dir,
                    job=job,
                    code_pack=code_pack,
                    documentation=documentation,
                )
                job.artifacts = artifacts
                job.run_dir = artifacts.get("run_dir")
            if job.run_dir:
                metadata_path = Path(job.run_dir) / "run_metadata.json"
                metadata_path.write_text(
                    json.dumps(_job_payload(job), indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                job.artifacts["metadata"] = str(metadata_path)
            await _upsert_devflow_job(job)
            await emit_event(
                {
                    "type": "devflow_error",
                    **_job_payload(job),
                    "download_url": (
                        f"/api/devflow/jobs/{job.job_id}/download"
                        if job.artifacts.get("zip")
                        else None
                    ),
                }
            )
            return
        except Exception as exc:
            error_text = str(exc).strip() or "Unknown error"
            job.status = "failed"
            job.stage = "failed"
            job.message = f"Programming workflow failed: {error_text[:280]}"
            job.error = error_text[:1200]
            job.updated_at = _utc_now_iso()
            job.finished_at = _utc_now_iso()
            if job.outputs:
                code_pack = build_code_pack_markdown(prompt=job.prompt, outputs=job.outputs)
                documentation = build_documentation_markdown(prompt=job.prompt, outputs=job.outputs)
                artifacts = write_devflow_artifacts(
                    base_dir=devflow_config.artifact_dir,
                    job=job,
                    code_pack=code_pack,
                    documentation=documentation,
                )
                job.artifacts = artifacts
                job.run_dir = artifacts.get("run_dir")
            if job.run_dir:
                metadata_path = Path(job.run_dir) / "run_metadata.json"
                metadata_path.write_text(
                    json.dumps(_job_payload(job), indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                job.artifacts["metadata"] = str(metadata_path)
            await _upsert_devflow_job(job)
            await emit_event(
                {
                    "type": "devflow_error",
                    **_job_payload(job),
                    "download_url": (
                        f"/api/devflow/jobs/{job.job_id}/download"
                        if job.artifacts.get("zip")
                        else None
                    ),
                }
            )


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


@app.get("/api/devflow/jobs/{job_id}")
async def devflow_job_status(job_id: str) -> dict[str, Any]:
    _devflow_enabled_or_403()
    job = await _get_devflow_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Devflow job not found.")
    payload = _job_payload(job)
    payload["download_url"] = (
        f"/api/devflow/jobs/{job.job_id}/download" if job.artifacts.get("zip") else None
    )
    return payload


@app.get("/api/devflow/jobs/{job_id}/download")
async def devflow_job_download(job_id: str) -> FileResponse:
    _devflow_enabled_or_403()
    job = await _get_devflow_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Devflow job not found.")
    zip_path = Path(job.artifacts.get("zip", ""))
    if not zip_path.exists() or not zip_path.is_file():
        raise HTTPException(status_code=404, detail="No downloadable artifact for this job.")
    return FileResponse(
        path=str(zip_path),
        filename=f"devflow_{job.job_id}.zip",
        media_type="application/zip",
    )


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
            "uploads": "/api/uploads",
            "upload_delete": "/api/uploads/{upload_id}?actor_id=...",
            "profile_preferences": "/api/v1/profile/preferences",
            "profile_preferences_reset": "/api/v1/profile/preferences/reset",
            "admin_users": "/api/v1/admin/users",
            "admin_platform": "/api/v1/admin/platform",
            "admin_events": "/api/v1/admin/events",
            "devflow_job_status": "/api/devflow/jobs/{job_id}",
            "devflow_job_download": "/api/devflow/jobs/{job_id}/download",
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
            "programming_development_flow": devflow_config.enabled,
            "file_upload_review": True,
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


@app.post("/api/uploads")
async def upload_review_material(
    actor_id: str = Form(default=settings.default_actor_id),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    clean_actor_id = _safe_actor_id(actor_id)
    filename = Path(str(file.filename or "upload.bin")).name
    raw_bytes = await file.read()
    await file.close()

    if not filename:
        raise HTTPException(status_code=400, detail="filename is required")
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(raw_bytes) > max(1024, settings.upload_max_bytes):
        raise HTTPException(
            status_code=413,
            detail=(
                f"Upload exceeds max size ({settings.upload_max_bytes} bytes). "
                f"Received: {len(raw_bytes)} bytes."
            ),
        )

    is_zip = filename.lower().endswith(".zip")
    if is_zip:
        context_text, file_count, included, skipped = _build_zip_context(filename, raw_bytes)
        kind = "zip"
    else:
        context_text, file_count, included, skipped = _build_plain_file_context(filename, raw_bytes)
        kind = "file"

    upload_id = str(uuid.uuid4())
    summary = (
        f"{kind.upper()} '{filename}' uploaded. "
        f"files={file_count}, included={included}, skipped={skipped}"
    )
    item = UploadedReviewContext(
        upload_id=upload_id,
        actor_id=clean_actor_id,
        filename=filename,
        kind=kind,
        size_bytes=len(raw_bytes),
        file_count=file_count,
        included_files=included,
        skipped_files=skipped,
        summary=summary,
        context_text=context_text,
        created_at=_utc_now_iso(),
    )
    await _store_uploaded_context(item)

    return {"upload": _upload_payload(item)}


@app.get("/api/uploads")
async def list_uploaded_materials(
    actor_id: str = Query(default=settings.default_actor_id),
) -> dict[str, Any]:
    clean_actor_id = _safe_actor_id(actor_id)
    items = await _list_uploaded_contexts(actor_id=clean_actor_id)
    return {
        "actor_id": clean_actor_id,
        "count": len(items),
        "uploads": [_upload_payload(item) for item in items],
    }


@app.delete("/api/uploads/{upload_id}")
async def delete_uploaded_material(
    upload_id: str,
    actor_id: str = Query(default=settings.default_actor_id),
) -> dict[str, Any]:
    clean_actor_id = _safe_actor_id(actor_id)
    item = await _delete_uploaded_context(upload_id=upload_id.strip(), actor_id=clean_actor_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Upload not found.")
    return {"status": "deleted", "upload_id": item.upload_id}


@app.delete("/api/uploads")
async def clear_uploaded_materials(
    actor_id: str = Query(default=settings.default_actor_id),
) -> dict[str, Any]:
    clean_actor_id = _safe_actor_id(actor_id)
    async with uploaded_contexts_lock:
        to_delete = [key for key, item in uploaded_contexts.items() if item.actor_id == clean_actor_id]
        for key in to_delete:
            uploaded_contexts.pop(key, None)
    return {"status": "cleared", "actor_id": clean_actor_id, "deleted": len(to_delete)}


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
            "devflow_start",
            "devflow_status",
            "devflow_cancel",
        ],
        "event_types": [
            "ready",
            "status",
            "start",
            "token",
            "done",
            "info",
            "error",
            "devflow_started",
            "devflow_progress",
            "devflow_stage_result",
            "devflow_done",
            "devflow_error",
        ],
        "local_tool_commands": ["/tools", "/ls", "/tree", "/find", "/read", "/summary", "/run", "/run!"],
        "chat_reasoning_mode": ["hidden", "summary", "full"],
        "chat_optional_fields": {
            "attachments": ["upload_id_1", "upload_id_2"],
        },
    }


@app.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    ws_send_lock = asyncio.Lock()
    websocket_open = True

    async def ws_send(payload: dict[str, Any]) -> None:
        async with ws_send_lock:
            await _send_json(websocket, payload)

    session = ChatSession(
        session_id=str(uuid.uuid4()),
        model=runtime_default_model,
    )
    ollama = OllamaClient(base_url=runtime_ollama_base_url)
    active_devflow_job_id: str | None = None
    devflow_background_tasks: set[asyncio.Task[Any]] = set()
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

    await ws_send(
        {
            "type": "info",
            "message": "Connected. Send a hello payload to set model/system prompt.",
        },
    )
    await ws_send(
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
            await ws_send(
                {"type": "info", "message": "Filesystem tools are disabled by admin policy."},
            )
        if not bool(platform.get("allow_terminal_tools", True)):
            await ws_send(
                {"type": "info", "message": "Terminal tools are disabled by admin policy."},
            )
    await ws_send(
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
                await ws_send({"type": "error", "message": "Invalid JSON payload."})
                continue

            msg_type = incoming.get("type")

            if msg_type == "devflow_start":
                try:
                    _devflow_enabled_or_403()
                except HTTPException as exc:
                    await ws_send({"type": "error", "message": str(exc.detail)})
                    continue
                try:
                    prompt = _safe_text(incoming.get("prompt"), field_name="prompt")
                except ValueError as exc:
                    await ws_send({"type": "error", "message": str(exc)})
                    continue
                actor_id = _safe_actor_id(incoming.get("actor_id") or session.actor_id)
                session.actor_id = actor_id
                attachment_ids = _normalize_attachment_ids(incoming.get("attachments"))
                attachment_context = ""
                resolved_attachments: list[UploadedReviewContext] = []
                if attachment_ids:
                    (
                        attachment_context,
                        missing_attachment_ids,
                        forbidden_attachment_ids,
                        resolved_attachments,
                    ) = await _resolve_attachment_context(
                        actor_id=actor_id,
                        attachment_ids=attachment_ids,
                    )
                    if missing_attachment_ids:
                        await ws_send(
                            {
                                "type": "error",
                                "message": (
                                    "Attachment(s) not found: "
                                    + ", ".join(sorted(missing_attachment_ids))
                                ),
                            }
                        )
                        continue
                    if forbidden_attachment_ids:
                        await ws_send(
                            {
                                "type": "error",
                                "message": (
                                    "Attachment(s) are not accessible for this actor: "
                                    + ", ".join(sorted(forbidden_attachment_ids))
                                ),
                            }
                        )
                        continue
                    if attachment_context:
                        prompt = (
                            f"{prompt}\n\n"
                            "Uploaded project materials for review are attached below. "
                            "Use them as primary source context for this workflow.\n\n"
                            f"{attachment_context}"
                        )
                selected_model = (
                    _safe_text(incoming.get("selected_model"), field_name="selected_model")
                    if isinstance(incoming.get("selected_model"), str) and str(incoming.get("selected_model")).strip()
                    else session.model
                )
                if active_devflow_job_id:
                    active_job = await _get_devflow_job(active_devflow_job_id)
                    if active_job and active_job.status in {"queued", "running"}:
                        await ws_send(
                            {
                                "type": "error",
                                "message": f"Devflow job {active_devflow_job_id} is still running.",
                            }
                        )
                        continue
                role_models_raw = incoming.get("role_models")
                role_models = role_models_raw if isinstance(role_models_raw, dict) else {}
                fallback_models_raw = incoming.get("fallback_models")
                fallback_models = (
                    [str(item).strip() for item in fallback_models_raw if str(item).strip()]
                    if isinstance(fallback_models_raw, list)
                    else []
                )
                try:
                    resolved_role_models = resolve_role_models(
                        role_models=role_models,
                        fallback_pool=fallback_models,
                        fallback_selected_model=selected_model,
                    )
                except DevflowError as exc:
                    await ws_send({"type": "error", "message": str(exc)})
                    continue

                job = DevflowJob(
                    job_id=str(uuid.uuid4()),
                    actor_id=actor_id,
                    prompt=prompt,
                    selected_model=selected_model,
                    role_models=resolved_role_models,
                )
                await _upsert_devflow_job(job)
                active_devflow_job_id = job.job_id
                await ws_send(
                    {
                        "type": "devflow_started",
                        **_job_payload(job),
                    }
                )
                if resolved_attachments:
                    await ws_send(
                        {
                            "type": "info",
                            "message": (
                                f"Using {len(resolved_attachments)} uploaded file/ZIP context item(s) "
                                "for this devflow run."
                            ),
                        }
                    )

                async def emit_devflow(payload: dict[str, Any]) -> None:
                    if not websocket_open:
                        return
                    try:
                        await ws_send(payload)
                    except Exception:
                        return

                task = asyncio.create_task(
                    _run_devflow_job(
                        job=job,
                        ollama=ollama,
                        emit_event=emit_devflow,
                    )
                )
                devflow_background_tasks.add(task)
                devflow_job_tasks[job.job_id] = task

                def _on_task_done(done_task: asyncio.Task[Any]) -> None:
                    nonlocal active_devflow_job_id
                    devflow_background_tasks.discard(done_task)
                    devflow_job_tasks.pop(job.job_id, None)
                    if active_devflow_job_id == job.job_id:
                        active_devflow_job_id = None

                task.add_done_callback(_on_task_done)
                continue

            if msg_type == "devflow_status":
                try:
                    _devflow_enabled_or_403()
                except HTTPException as exc:
                    await ws_send({"type": "error", "message": str(exc.detail)})
                    continue
                requested_job_id = incoming.get("job_id")
                target_job_id = (
                    str(requested_job_id).strip()
                    if isinstance(requested_job_id, str) and requested_job_id.strip()
                    else active_devflow_job_id
                )
                if not target_job_id:
                    await ws_send({"type": "error", "message": "No devflow job id provided."})
                    continue
                job = await _get_devflow_job(target_job_id)
                if job is None:
                    await ws_send({"type": "error", "message": "Devflow job not found."})
                    continue
                event_type = "devflow_progress"
                if job.status == "completed":
                    event_type = "devflow_done"
                elif job.status == "failed":
                    event_type = "devflow_error"
                await ws_send(
                    {
                        "type": event_type,
                        **_job_payload(job),
                        "download_url": (
                            f"/api/devflow/jobs/{job.job_id}/download"
                            if job.artifacts.get("zip")
                            else None
                        ),
                    }
                )
                continue

            if msg_type == "devflow_cancel":
                try:
                    _devflow_enabled_or_403()
                except HTTPException as exc:
                    await ws_send({"type": "error", "message": str(exc.detail)})
                    continue
                requested_job_id = incoming.get("job_id")
                target_job_id = (
                    str(requested_job_id).strip()
                    if isinstance(requested_job_id, str) and requested_job_id.strip()
                    else active_devflow_job_id
                )
                if not target_job_id:
                    await ws_send({"type": "error", "message": "No devflow job id provided."})
                    continue
                job = await _request_devflow_cancel(target_job_id)
                if job is None:
                    await ws_send({"type": "error", "message": "Devflow job not found."})
                    continue
                await ws_send(
                    {
                        "type": "devflow_progress",
                        **_job_payload(job),
                        "download_url": (
                            f"/api/devflow/jobs/{job.job_id}/download"
                            if job.artifacts.get("zip")
                            else None
                        ),
                    }
                )
                continue

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
                await ws_send(
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
                await ws_send(
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
                    await ws_send({"type": "error", "message": str(exc)})
                    continue
                await ws_send({"type": "info", "message": f"Model set to {session.model}"})
                continue

            if msg_type == "reset":
                session.reset()
                await ws_send({"type": "info", "message": "Conversation reset."})
                continue

            if msg_type != "chat":
                await ws_send(
                    {"type": "error", "message": f"Unsupported message type: {msg_type}"},
                )
                continue

            try:
                prompt = _safe_text(incoming.get("prompt"), field_name="prompt")
            except ValueError as exc:
                await ws_send({"type": "error", "message": str(exc)})
                continue
            is_tool_prompt = prompt.strip().startswith("/")
            attachment_ids = _normalize_attachment_ids(incoming.get("attachments"))
            attachment_context = ""
            resolved_attachments: list[UploadedReviewContext] = []
            if attachment_ids and not is_tool_prompt:
                (
                    attachment_context,
                    missing_attachment_ids,
                    forbidden_attachment_ids,
                    resolved_attachments,
                ) = await _resolve_attachment_context(
                    actor_id=session.actor_id,
                    attachment_ids=attachment_ids,
                )
                if missing_attachment_ids:
                    await ws_send(
                        {
                            "type": "error",
                            "message": (
                                "Attachment(s) not found: "
                                + ", ".join(sorted(missing_attachment_ids))
                            ),
                        }
                    )
                    continue
                if forbidden_attachment_ids:
                    await ws_send(
                        {
                            "type": "error",
                            "message": (
                                "Attachment(s) are not accessible for this actor: "
                                + ", ".join(sorted(forbidden_attachment_ids))
                            ),
                        }
                    )
                    continue
            profile_snapshot = admin_profile_store.get_preferences(session.actor_id)
            default_reasoning_mode = str(
                profile_snapshot.preferences.get("chat", {}).get("reasoning_mode_default", "summary")
            )
            reasoning_mode = _safe_reasoning_mode(incoming.get("reasoning_mode") or default_reasoning_mode)
            terminal_require_confirm = bool(settings.terminal_require_confirm) or bool(
                profile_snapshot.preferences.get("tools", {}).get("terminal_require_confirm", True)
            )
            session_temperature = float(
                profile_snapshot.preferences.get("sessions_models", {}).get(
                    "default_temperature", settings.default_temperature
                )
            )
            session_num_ctx = int(
                profile_snapshot.preferences.get("sessions_models", {}).get(
                    "default_num_ctx", settings.default_num_ctx
                )
            )

            request_id = str(uuid.uuid4())
            prompt_for_model = prompt
            if attachment_context:
                prompt_for_model = (
                    f"{prompt}\n\n"
                    "Uploaded file/ZIP context for review:\n"
                    f"{attachment_context}\n\n"
                    "Use this attached context to answer or review code."
                )
            session.messages.append({"role": "user", "content": prompt_for_model})

            await ws_send({"type": "start", "request_id": request_id})
            if resolved_attachments:
                await ws_send(
                    {
                        "type": "info",
                        "message": (
                            f"Using {len(resolved_attachments)} uploaded file/ZIP context item(s) in this reply."
                        ),
                    }
                )

            assistant_chunks: list[str] = []
            if is_tool_prompt:
                try:
                    if tools is None:
                        raise WorkspaceToolError("Local tools are unavailable in this session.")
                    tool_output = await _handle_local_tool_command(
                        prompt=prompt,
                        tools=tools,
                        model=session.model,
                        ollama=ollama,
                        terminal_require_confirm=terminal_require_confirm,
                        temperature=session_temperature,
                        num_ctx=session_num_ctx,
                    )
                except (WorkspaceToolError, WorkspaceSecurityError) as exc:
                    tool_output = f"Tool error: {exc}"
                except OllamaStreamError as exc:
                    tool_output = f"Summary generation failed: {exc}"
                except Exception as exc:  # pragma: no cover - safety net
                    tool_output = f"Unexpected tool failure: {exc}"

                for chunk in _chunks(tool_output):
                    assistant_chunks.append(chunk)
                    await ws_send(
                        {"type": "token", "request_id": request_id, "text": chunk},
                    )

                assistant_text = "".join(assistant_chunks).strip()
                if assistant_text:
                    session.messages.append({"role": "assistant", "content": assistant_text})

                await ws_send(
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
                    temperature=session_temperature,
                    num_ctx=session_num_ctx,
                    think=_resolve_think_setting(model=session.model, reasoning_mode=reasoning_mode),
                ):
                    assistant_chunks.append(chunk)
                    await ws_send(
                        {"type": "token", "request_id": request_id, "text": chunk},
                    )
            except OllamaStreamError as exc:
                await ws_send({"type": "error", "message": str(exc)})
                if session.messages and session.messages[-1]["role"] == "user":
                    session.messages.pop()
                continue
            except Exception as exc:  # pragma: no cover - safety net
                await ws_send({"type": "error", "message": f"Unexpected error: {exc}"})
                if session.messages and session.messages[-1]["role"] == "user":
                    session.messages.pop()
                continue

            assistant_text = "".join(assistant_chunks).strip()
            if assistant_text:
                session.messages.append({"role": "assistant", "content": assistant_text})

            await ws_send(
                {
                    "type": "done",
                    "request_id": request_id,
                    "model": session.model,
                },
            )
    except WebSocketDisconnect:
        websocket_open = False
        for task in list(devflow_background_tasks):
            if not task.done():
                task.cancel()
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
