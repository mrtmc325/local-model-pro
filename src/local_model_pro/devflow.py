from __future__ import annotations

import asyncio
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable


ROLE_ORDER: list[str] = [
    "intent_reasoner",
    "intent_knowledge",
    "intent_feasibility",
    "code_model_1",
    "code_model_2",
    "code_model_3",
    "doc_inline",
    "doc_git",
    "doc_release",
]

CODING_ROLES: list[str] = ["code_model_1", "code_model_2", "code_model_3"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DevflowJob:
    job_id: str
    actor_id: str
    prompt: str
    selected_model: str
    role_models: dict[str, str]
    status: str = "queued"
    stage: str = "queued"
    percent: int = 0
    message: str = "Queued."
    started_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    finished_at: str | None = None
    error: str | None = None
    cancel_requested: bool = False
    run_dir: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    stages: list[dict[str, Any]] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)
    retries_by_role: dict[str, int] = field(default_factory=dict)


@dataclass
class DevflowRuntimeConfig:
    enabled: bool
    max_concurrent_jobs: int
    role_timeout_seconds: int
    run_retention: int
    artifact_dir: Path
    doc_inline_max_input_chars: int = 5000
    doc_git_max_input_chars: int = 3500
    doc_escalation_enabled: bool = True
    retry_count: int = 1


class DevflowError(RuntimeError):
    pass


def resolve_role_models(
    *,
    role_models: dict[str, str] | None,
    fallback_pool: list[str],
    fallback_selected_model: str,
) -> dict[str, str]:
    explicit = {k: str(v).strip() for k, v in (role_models or {}).items() if str(v).strip()}
    selected = fallback_selected_model.strip()
    pool = [item.strip() for item in fallback_pool if item and item.strip()]
    if not selected and pool:
        selected = pool[0]
    if not selected and explicit:
        selected = next(iter(explicit.values()))
    if not selected:
        raise DevflowError("No model available for devflow execution.")

    resolved: dict[str, str] = {}
    for role in ROLE_ORDER:
        picked = explicit.get(role, "")
        if picked:
            resolved[role] = picked
            continue
        resolved[role] = selected
    return resolved


def build_code_pack_markdown(
    *,
    prompt: str,
    outputs: dict[str, str],
) -> str:
    inline_doc_code = outputs.get("doc_inline_code", "").strip() or outputs.get("doc_inline", "").strip()
    lines = [
        "# Generated Code Pack",
        "",
        "## Source Prompt",
        "",
        prompt.strip(),
        "",
        "## Intent Synthesis",
        "",
        f"### intent_reasoner\n\n{outputs.get('intent_reasoner', '').strip()}",
        "",
        f"### intent_knowledge\n\n{outputs.get('intent_knowledge', '').strip()}",
        "",
        f"### intent_feasibility\n\n{outputs.get('intent_feasibility', '').strip()}",
        "",
        "## Coding Rounds",
        "",
        f"### round1.code_model_1\n\n{outputs.get('round1.code_model_1', '').strip()}",
        "",
        f"### round1.code_model_2\n\n{outputs.get('round1.code_model_2', '').strip()}",
        "",
        f"### round1.code_model_3\n\n{outputs.get('round1.code_model_3', '').strip()}",
        "",
        f"### round2.code_model_1\n\n{outputs.get('round2.code_model_1', '').strip()}",
        "",
        f"### round2.code_model_2\n\n{outputs.get('round2.code_model_2', '').strip()}",
        "",
        f"### round2.code_model_3\n\n{outputs.get('round2.code_model_3', '').strip()}",
        "",
        f"### round3.chain.code_model_1\n\n{outputs.get('round3.code_model_1', '').strip()}",
        "",
        f"### round3.chain.code_model_2\n\n{outputs.get('round3.code_model_2', '').strip()}",
        "",
        "## Final Canonical Output",
        "",
        outputs.get("final_code", "").strip(),
        "",
        "## Inline Documented Code Variant",
        "",
        inline_doc_code,
        "",
    ]
    return "\n".join(lines).strip() + "\n"


def build_documentation_markdown(
    *,
    prompt: str,
    outputs: dict[str, str],
) -> str:
    inline_doc_code = outputs.get("doc_inline_code", "").strip() or outputs.get("doc_inline", "").strip()
    fallback_notes: list[str] = []
    doc_inline_source = str(outputs.get("doc_inline_source", "")).strip()
    doc_inline_error = str(outputs.get("doc_inline_error", "")).strip()
    if doc_inline_source == "fallback":
        fallback_notes.append("doc_inline used fallback annotator output after role failure.")
    elif doc_inline_source == "escalated":
        fallback_notes.append("doc_inline succeeded via escalation to code_model_3.")
    elif doc_inline_source == "role":
        fallback_notes.append("doc_inline succeeded on its assigned role model.")
    elif outputs.get("doc_inline_fallback_used") == "true":
        fallback_notes.append("doc_inline used fallback annotator output due to role timeout/failure.")
    if doc_inline_error:
        fallback_notes.append(f"doc_inline prior error: {doc_inline_error}")

    doc_git_source = str(outputs.get("doc_git_source", "")).strip()
    doc_git_error = str(outputs.get("doc_git_error", "")).strip()
    if doc_git_source == "fallback":
        fallback_notes.append("doc_git used fallback notes after role failure.")
    elif doc_git_source == "escalated":
        fallback_notes.append("doc_git succeeded via escalation to code_model_3.")
    elif doc_git_source == "role":
        fallback_notes.append("doc_git succeeded on its assigned role model.")
    elif outputs.get("doc_git_fallback_used") == "true":
        fallback_notes.append("doc_git used fallback notes due to role timeout/failure.")
    if doc_git_error:
        fallback_notes.append(f"doc_git prior error: {doc_git_error}")

    if outputs.get("doc_release_fallback_used") == "true":
        fallback_notes.append("doc_release used fallback notes due to role timeout/failure.")
    inline_notes = (
        "\n".join([f"- {note}" for note in fallback_notes])
        if fallback_notes
        else "Inline comments and function-level docstrings are embedded directly in the code block above."
    )
    lines = [
        "# Documentation Pack",
        "",
        "## Source Prompt",
        "",
        prompt.strip(),
        "",
        "## Inline Documented Code",
        "",
        inline_doc_code,
        "",
        "## Inline Documentation Notes",
        "",
        inline_notes,
        "",
        "## Git Notes",
        "",
        outputs.get("doc_git", "").strip(),
        "",
        "## Release Notes",
        "",
        outputs.get("doc_release", "").strip(),
        "",
    ]
    return "\n".join(lines).strip() + "\n"


def write_devflow_artifacts(
    *,
    base_dir: Path,
    job: DevflowJob,
    code_pack: str,
    documentation: str,
) -> dict[str, str]:
    run_dir = base_dir / job.job_id
    run_dir.mkdir(parents=True, exist_ok=True)

    code_file = run_dir / "code_pack.md"
    doc_file = run_dir / "documentation.md"
    zip_file = run_dir / "devflow_outputs.zip"

    code_file.write_text(code_pack, encoding="utf-8")
    doc_file.write_text(documentation, encoding="utf-8")
    with zipfile.ZipFile(zip_file, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(code_file, arcname="code_pack.md")
        archive.write(doc_file, arcname="documentation.md")

    return {
        "run_dir": str(run_dir),
        "code_pack": str(code_file),
        "documentation": str(doc_file),
        "zip": str(zip_file),
    }


def trim_jobs(jobs: dict[str, DevflowJob], *, max_jobs: int) -> None:
    if len(jobs) <= max_jobs:
        return
    keys = sorted(jobs.keys(), key=lambda key: jobs[key].started_at)
    for key in keys[: max(0, len(jobs) - max_jobs)]:
        jobs.pop(key, None)


def cleanup_old_runs(*, base_dir: Path, keep_job_ids: set[str]) -> None:
    if not base_dir.exists():
        return
    for child in base_dir.iterdir():
        if not child.is_dir():
            continue
        if child.name in keep_job_ids:
            continue
        try:
            for nested in child.iterdir():
                if nested.is_file():
                    nested.unlink(missing_ok=True)
            child.rmdir()
        except OSError:
            continue


async def run_with_retries(
    *,
    job: DevflowJob,
    role: str,
    role_model: str,
    role_prompt: str,
    role_call: Callable[[str, str], Awaitable[str]],
    retries: int,
) -> str:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        job.retries_by_role[role] = attempt
        try:
            output = await role_call(role_model, role_prompt)
            if not output.strip():
                raise DevflowError(f"Role '{role}' returned empty output.")
            return output.strip()
        except Exception as exc:  # pragma: no cover - retries path
            last_error = exc
            if attempt >= retries:
                break
            await asyncio.sleep(0.05)
    error_text = ""
    if last_error is not None:
        error_text = str(last_error).strip() or type(last_error).__name__
    raise DevflowError(f"Role '{role}' failed: {error_text or 'unknown error'}")
